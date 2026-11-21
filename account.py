import ctypes
import json
import os
import re
import secrets
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlencode

import requests

from .pinterest_api import OFFICIAL_API_URLS, PinterestOfficialClient

ACCOUNT_PATH = "/pinterest_gallery/account"
CALLBACK_PATH = ACCOUNT_PATH + "/oauth/callback"
OAUTH_COOKIE = "pinterest_gallery_oauth"
OAUTH_SECONDS = 600
AUTHORIZE_URL = "https://www.pinterest.com/oauth/"
SCOPE = "boards:read,pins:read"
WRITE_SCOPE = "boards:read,boards:write,pins:read,pins:write"


class AccountError(Exception):
    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.status = status
        self.code = code


class _DataBlob(ctypes.Structure):
    _fields_ = [("length", ctypes.c_uint32), ("data", ctypes.c_void_p)]


def _dpapi(data, decrypt=False):
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    release = ctypes.WinDLL("kernel32", use_last_error=True).LocalFree
    release.argtypes = (ctypes.c_void_p,)
    release.restype = ctypes.c_void_p
    transform = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    transform.argtypes = (
        ctypes.POINTER(_DataBlob),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_uint32,
        ctypes.POINTER(_DataBlob),
    )
    transform.restype = ctypes.c_int
    input_buffer = ctypes.create_string_buffer(data)
    input_blob = _DataBlob(len(data), ctypes.cast(input_buffer, ctypes.c_void_p))
    output_blob = _DataBlob()
    if not transform(
        ctypes.byref(input_blob), None, None, None, None, 1, ctypes.byref(output_blob)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(output_blob.data, output_blob.length)
    finally:
        release(output_blob.data)


class DPAPIStore:
    def __init__(self, path):
        self.path = path

    @classmethod
    def local(cls):
        app_data = os.environ.get("LOCALAPPDATA") if os.name == "nt" else None
        if not app_data:
            return cls(None)
        base = Path(app_data)
        path = base / "ComfyUI" / "PinterestGallery" / "account.dpapi"
        legacy = base / "Soda" / "PinterestGallery" / "account.dpapi"
        return cls(legacy if legacy.is_file() and not path.exists() else path)

    @property
    def available(self):
        return self.path is not None

    def read(self):
        if self.path is None:
            return None
        try:
            with self.path.open("rb") as file:
                encrypted = file.read(65537)
        except FileNotFoundError:
            return None
        if len(encrypted) > 65536:
            raise ValueError("Invalid credential file")
        return json.loads(_dpapi(encrypted, decrypt=True))

    def write(self, record):
        if self.path is None:
            raise AccountError("当前系统不支持本机加密保存")
        encrypted = _dpapi(json.dumps(record, separators=(",", ":")).encode())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=self.path.parent, suffix=".tmp", delete=False
            ) as file:
                temporary = Path(file.name)
                file.write(encrypted)
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def clear(self):
        if self.path is not None:
            self.path.unlink(missing_ok=True)


@dataclass(frozen=True)
class Credential:
    token: str = field(repr=False)
    mode: str
    method: str
    expires_at: int | None = None
    persistent: bool = False
    write_authorized: bool = False

    @property
    def expired(self):
        return self.expires_at is not None and time.time() >= self.expires_at

    @property
    def pin_write(self):
        if self.method != "oauth":
            return "unknown"
        return "granted" if self.write_authorized else "read_only"


@dataclass(frozen=True)
class PendingOAuth:
    state: str = field(repr=False)
    browser: str = field(repr=False)
    client_id: str
    client_secret: str = field(repr=False)
    mode: str
    redirect_uri: str
    remember: bool
    expires_at: int
    deadline: float
    generation: int
    write_access: bool


def _mode(value):
    if not isinstance(value, str) or value not in OFFICIAL_API_URLS:
        raise AccountError("请选择 Production 或 Sandbox")
    return value


def _token(value):
    if not isinstance(value, str):
        raise AccountError("请填写有效的 Access Token")
    token = value.strip()
    if len(token) > 4096 or not re.fullmatch(r"[A-Za-z0-9._~+/=-]+", token):
        raise AccountError("请填写有效的 Access Token")
    return token


def _verification_client(token, mode):
    return PinterestOfficialClient(token=token, environment=mode)


def _verify_token(token, mode):
    client = _verification_client(token, mode)
    try:
        client.list_boards()
    finally:
        client.session.close()


def exchange_code(pending, code):
    try:
        response = requests.post(
            OFFICIAL_API_URLS[pending.mode] + "/oauth/token",
            auth=(pending.client_id, pending.client_secret),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": pending.redirect_uri,
            },
            timeout=12,
            allow_redirects=False,
        )
    except requests.RequestException:
        raise AccountError("Pinterest 授权服务暂不可用，请重试", 502) from None
    if not 200 <= response.status_code < 300:
        raise AccountError("Pinterest 没有接受授权，请检查 App 配置和回调地址", 400)
    try:
        data = response.json()
        token = _token(data["access_token"])
        seconds = data["expires_in"]
        if type(seconds) is not int or not 0 < seconds <= 31_536_000:
            raise ValueError
    except (ValueError, KeyError, TypeError, AccountError):
        raise AccountError("Pinterest 返回的授权结果不完整，请重试", 502) from None
    if pending.write_access:
        scope = data.get("scope")
        granted = set(re.split(r"[\s,]+", scope)) if isinstance(scope, str) else set()
        if not set(WRITE_SCOPE.split(",")).issubset(granted):
            raise AccountError(
                "Pinterest 本次未授予完整的画板保存权限，请重新授权", 403
            )
    return Credential(
        token,
        pending.mode,
        "oauth",
        int(time.time()) + seconds,
        pending.remember,
        write_authorized=pending.write_access,
    )


class PinterestAccount:
    def __init__(self, store):
        self.store = store
        self._lock = threading.RLock()
        self._loaded = False
        self._load_error = False
        self._suppress_environment = False
        self._invalid = False
        self._environment_invalid = False
        self._credential = None
        self._pending = None
        self._oauth_exchange = None
        self._oauth_error = None
        self._generation = 0

    def _load(self):
        if self._loaded:
            return
        self._loaded = True
        try:
            record = self.store.read()
            if record is None:
                return
            method, expiry = record["method"], record.get("expires_at")
            if method not in ("oauth", "token") or (
                expiry is not None and (type(expiry) is not int or expiry < 0)
            ):
                raise ValueError
            self._credential = Credential(
                _token(record["token"]),
                _mode(record["mode"]),
                method,
                expiry,
                persistent=True,
                write_authorized=method == "oauth"
                and record.get("write_authorized") is True,
            )
        except (OSError, ValueError, AttributeError, KeyError, TypeError, AccountError):
            self._load_error = True

    def _current_pending(self):
        if self._pending is not None and time.monotonic() >= self._pending.deadline:
            self._oauth_error = (
                self._pending.redirect_uri,
                "Pinterest 授权已超时，请重新开始",
            )
            self._pending = None
        return self._pending

    def snapshot(self):
        with self._lock:
            self._load()
            return self._credential, self._suppress_environment, self._invalid

    def status(self, origin, environment_client, environment_error):
        with self._lock:
            self._load()
            pending = self._current_pending()
            credential = self._credential
            mode = method = expires_at = None
            persistent = False
            state = "disconnected"
            if credential is not None:
                mode, method = credential.mode, credential.method
                persistent, expires_at = credential.persistent, credential.expires_at
                state = (
                    "expired"
                    if credential.expired
                    else ("invalid" if self._invalid else "connected")
                )
            elif not self._suppress_environment:
                if environment_client is not None and environment_client.configured:
                    mode, method = environment_client.environment, "environment"
                    state = "invalid" if self._environment_invalid else "connected"
                elif self._load_error or environment_error:
                    state = "error"
            return {
                "connected": state == "connected",
                "state": state,
                "mode": mode,
                "method": method,
                "pin_write": credential.pin_write
                if credential is not None
                else "unknown",
                "expires_at": expires_at,
                "persistent": persistent,
                "can_persist": self.store.available,
                "oauth_available": True,
                "redirect_uri": origin + CALLBACK_PATH,
                "oauth_pending": (
                    (
                        pending is not None
                        and pending.redirect_uri == origin + CALLBACK_PATH
                    )
                    or self._oauth_exchange == origin
                ),
                "oauth_error": (
                    self._oauth_error[1]
                    if self._oauth_error
                    and self._oauth_error[0] == origin + CALLBACK_PATH
                    else None
                ),
                "environment_suppressed": self._suppress_environment
                and credential is None,
            }

    def _start(self, remember):
        if type(remember) is not bool:
            raise AccountError("本机加密保存选项无效")
        if remember and not self.store.available:
            raise AccountError("当前系统不支持本机加密保存")
        self._generation += 1
        self._pending = None
        self._oauth_exchange = None
        self._oauth_error = None
        return self._generation

    def _commit(self, credential, generation):
        with self._lock:
            if generation != self._generation:
                raise AccountError("此连接操作已取消，请重试", 409)
            try:
                if credential.persistent:
                    record = {
                        "token": credential.token,
                        "mode": credential.mode,
                        "method": credential.method,
                        "expires_at": credential.expires_at,
                    }
                    if credential.write_authorized:
                        record["write_authorized"] = True
                    self.store.write(record)
                else:
                    self.store.clear()
            except OSError:
                raise AccountError("无法更新本机加密凭据，请重试", 500) from None
            self._loaded = True
            self._load_error = self._invalid = False
            self._credential = credential

    def connect_token(self, body):
        token, mode = _token(body.get("token")), _mode(body.get("mode"))
        remember = body.get("remember", False)
        with self._lock:
            generation = self._start(remember)
        _verify_token(token, mode)
        self._commit(Credential(token, mode, "token", persistent=remember), generation)

    def begin_oauth(self, body, origin):
        client_id, client_secret = body.get("client_id"), body.get("client_secret")
        if not isinstance(client_id, str) or not re.fullmatch(
            r"[A-Za-z0-9_-]{1,128}", client_id.strip()
        ):
            raise AccountError("请填写 Pinterest 开发者 App ID")
        if not isinstance(client_secret, str) or not re.fullmatch(
            r"[!-~]{1,4096}", client_secret.strip()
        ):
            raise AccountError("请填写 Pinterest 开发者 App Secret")
        mode = _mode(body.get("mode"))
        remember = body.get("remember", False)
        write_access = body.get("write_access", False)
        if type(write_access) is not bool:
            raise AccountError("Pinterest 保存权限选项无效")
        with self._lock:
            generation = self._start(remember)
            pending = PendingOAuth(
                secrets.token_urlsafe(32),
                secrets.token_urlsafe(32),
                client_id.strip(),
                client_secret.strip(),
                mode,
                origin + CALLBACK_PATH,
                remember,
                int(time.time()) + OAUTH_SECONDS,
                time.monotonic() + OAUTH_SECONDS,
                generation,
                write_access,
            )
            self._pending = pending
        query = urlencode(
            {
                "client_id": pending.client_id,
                "redirect_uri": pending.redirect_uri,
                "response_type": "code",
                "scope": WRITE_SCOPE if write_access else SCOPE,
                "state": pending.state,
            }
        )
        return {
            "authorize_url": AUTHORIZE_URL + "?" + query,
            "redirect_uri": pending.redirect_uri,
            "expires_at": pending.expires_at,
        }, pending.browser

    def finish_oauth(self, state, browser, origin, code, cancelled):
        with self._lock:
            pending = self._current_pending()
            if (
                pending is None
                or origin + CALLBACK_PATH != pending.redirect_uri
                or not isinstance(state, str)
                or not state.isascii()
                or not isinstance(browser, str)
                or not browser.isascii()
                or not secrets.compare_digest(state, pending.state)
                or not secrets.compare_digest(browser, pending.browser)
            ):
                raise AccountError("此授权已失效，请回画廊重新开始")
            self._pending = None
            self._oauth_exchange = origin
        try:
            if cancelled:
                raise AccountError("Pinterest 授权已取消")
            if not isinstance(code, str) or not re.fullmatch(r"[!-~]{1,4096}", code):
                raise AccountError("没有收到有效的 Pinterest 授权码")
            credential = exchange_code(pending, code)
            self._commit(credential, pending.generation)
        except AccountError as exc:
            with self._lock:
                if self._generation == pending.generation:
                    self._oauth_error = (pending.redirect_uri, str(exc))
            raise
        finally:
            with self._lock:
                if self._generation == pending.generation:
                    self._oauth_exchange = None

    def mark_invalid(self, credential):
        with self._lock:
            if credential is None:
                self._environment_invalid = True
            elif credential is self._credential:
                self._invalid = True

    def logout(self):
        with self._lock:
            self._start(False)
            try:
                self.store.clear()
            except OSError:
                raise AccountError("无法删除本机加密凭据，请重试", 500) from None
            self._credential = None
            self._loaded = True
            self._load_error = self._invalid = False
            self._suppress_environment = True
