import asyncio
import ipaddress
import json
import threading
import time
from collections import OrderedDict
from html import escape
from urllib.parse import urlsplit

from aiohttp import web

from .account import (
    ACCOUNT_PATH,
    CALLBACK_PATH,
    OAUTH_COOKIE,
    OAUTH_SECONDS,
    AccountError,
    DPAPIStore,
    PinterestAccount,
)
from .pinterest_api import (
    PinterestAPIError,
    PinterestAuthError,
    PinterestClient,
    PinterestOfficialClient,
    PinterestPermissionError,
    PinterestRateLimitError,
    PinterestTargetBoardError,
    PinterestTimeoutError,
    decimal_id,
)

_client = PinterestClient()
_account = PinterestAccount(DPAPIStore.local())
_verified_pins = OrderedDict()
_pin_lifetime = 60 * 60
_pin_limit = 4096
_save_lock = threading.Lock()
_in_progress = set()

try:
    _official_client = PinterestOfficialClient()
    _official_client_error = None
except ValueError as exc:
    # A bad PINTEREST_API_ENV must not take down module import — that would
    # also break the token-free Search path, which shares this module.
    _official_client = None
    _official_client_error = str(exc)


def _official_error_response(exc):
    if isinstance(exc, AccountError):
        return web.json_response({"error": str(exc)}, status=exc.status)
    if isinstance(exc, PinterestAuthError):
        return web.json_response({"error": str(exc)}, status=401)
    if isinstance(exc, PinterestPermissionError):
        return web.json_response({"error": str(exc)}, status=403)
    if isinstance(exc, PinterestRateLimitError):
        return web.json_response({"error": str(exc)}, status=429)
    if isinstance(exc, PinterestTimeoutError):
        return web.json_response({"error": str(exc)}, status=504)
    if isinstance(exc, ValueError):
        return web.json_response({"error": str(exc)}, status=400)
    if isinstance(exc, PinterestAPIError):
        return web.json_response({"error": str(exc)}, status=502)
    return web.json_response({"error": "Pinterest API request failed"}, status=502)


def _local_origin(request):
    try:
        if not ipaddress.ip_address(request.remote).is_loopback:
            return None
        origin = f"{request.scheme}://{request.host}"
        url = urlsplit(origin)
        if (
            url.scheme not in ("http", "https")
            or url.hostname not in ("localhost", "127.0.0.1", "::1")
            or url.username is not None
            or url.path
            or url.query
            or url.fragment
            or (url.port is not None and not 0 < url.port < 65536)
        ):
            return None
        return origin
    except ValueError:
        return None


def _same_origin_local(request):
    origin = _local_origin(request)
    return (
        origin is not None
        and request.headers.get("Origin", origin) == origin
        and request.headers.get("Sec-Fetch-Site") in (None, "none", "same-origin")
    )


async def _account_body(request):
    origin = _local_origin(request)
    if not _same_origin_local(request) or request.headers.get("Origin") != origin:
        raise AccountError("此操作仅允许由本机 ComfyUI 界面提交", 403)
    if request.content_type != "application/json":
        raise AccountError("请提交 JSON 格式的账号设置", 415)
    data = bytearray()
    async for chunk in request.content.iter_chunked(4096):
        data.extend(chunk)
        if len(data) > 32768:
            raise AccountError("账号设置内容过长", 413)
    try:
        body = json.loads(data)
    except (ValueError, UnicodeError, RecursionError):
        raise AccountError("账号设置格式无效") from None
    if not isinstance(body, dict):
        raise AccountError("账号设置格式无效")
    return origin, body


def _account_status(origin):
    return _account.status(origin, _official_client, _official_client_error)


def _account_json(data, status=200):
    return web.json_response(data, status=status, headers={"Cache-Control": "no-store"})


def _account_error(exc):
    if isinstance(exc, AccountError):
        return _account_json({"error": str(exc)}, status=exc.status)
    if isinstance(exc, PinterestAuthError):
        return _account_json(
            {"error": "Pinterest 拒绝了此 Access Token，请核对环境或更换令牌"},
            status=401,
        )
    if isinstance(exc, PinterestPermissionError):
        return _account_json(
            {"error": "此令牌没有读取 Pinterest 画板的权限"}, status=403
        )
    if isinstance(exc, PinterestRateLimitError):
        return _account_json(
            {"error": "Pinterest 请求过于频繁，请稍后重试"}, status=429
        )
    return _account_json(
        {"error": "暂时无法验证 Pinterest 连接，请稍后重试"}, status=502
    )


async def account_status_handler(request):
    if not _same_origin_local(request):
        return _account_error(AccountError("账号状态仅在本机 ComfyUI 显示", 403))
    return _account_json(
        await asyncio.to_thread(_account_status, _local_origin(request))
    )


async def account_token_handler(request):
    try:
        origin, body = await _account_body(request)
        await asyncio.to_thread(_account.connect_token, body)
        return _account_json(await asyncio.to_thread(_account_status, origin))
    except (AccountError, PinterestAPIError) as exc:
        return _account_error(exc)


async def account_oauth_start_handler(request):
    try:
        origin, body = await _account_body(request)
        values, browser = _account.begin_oauth(body, origin)
    except AccountError as exc:
        return _account_error(exc)
    response = _account_json(values)
    response.set_cookie(
        OAUTH_COOKIE,
        browser,
        path=CALLBACK_PATH,
        max_age=OAUTH_SECONDS,
        httponly=True,
        secure=origin.startswith("https://"),
        samesite="Lax",
    )
    return response


def _callback_page(message, status):
    return web.Response(
        text=f"""<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pinterest · ComfyUI</title><main><h1>Pinterest</h1>
<p>{escape(message)}</p><p>可以关闭此标签页，回到 ComfyUI 画廊。</p></main></html>""",
        status=status,
        content_type="text/html",
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


async def account_oauth_callback_handler(request):
    origin = _local_origin(request)
    if origin is None:
        return _callback_page("此回调仅接受本机浏览器请求", 403)
    try:
        await asyncio.to_thread(
            _account.finish_oauth,
            request.query.get("state"),
            request.cookies.get(OAUTH_COOKIE),
            origin,
            request.query.get("code"),
            "error" in request.query,
        )
    except AccountError as exc:
        return _callback_page(str(exc), exc.status)
    response = _callback_page("Pinterest 已连接。", 200)
    response.del_cookie(OAUTH_COOKIE, path=CALLBACK_PATH)
    return response


async def account_logout_handler(request):
    try:
        origin, _ = await _account_body(request)
        await asyncio.to_thread(_account.logout)
        response = _account_json(await asyncio.to_thread(_account_status, origin))
        response.del_cookie(OAUTH_COOKIE, path=CALLBACK_PATH)
        return response
    except AccountError as exc:
        return _account_error(exc)


def _official_call(local, method, *args):
    credential, suppressed, invalid = _account.snapshot()
    if credential is not None or suppressed:
        if not local:
            raise AccountError("此 Pinterest 连接仅供本机 ComfyUI 使用", 403)
        if credential is None:
            raise AccountError("尚未连接 Pinterest", 401)
        if credential.expired or invalid:
            raise AccountError("Pinterest 连接已失效，请重新连接", 401)
        if method == "save_pin" and credential.pin_write == "read_only":
            raise AccountError(
                "请先授权 Pinterest 画板保存权限", 403, "write_scope_required"
            )
        client = PinterestOfficialClient(
            token=credential.token, environment=credential.mode
        )
    else:
        if _official_client is None:
            raise AccountError(_official_client_error, 500)
        client = _official_client
    try:
        return getattr(client, method)(*args)
    except PinterestAuthError:
        _account.mark_invalid(credential)
        raise
    finally:
        if credential is not None:
            client.session.close()


def _remember_pin_ids(items):
    deadline = time.monotonic() + _pin_lifetime
    for item in items:
        pin_id = decimal_id(item.get("pin_id"))
        if pin_id is not None:
            _verified_pins[pin_id] = deadline
            _verified_pins.move_to_end(pin_id)
    while len(_verified_pins) > _pin_limit:
        _verified_pins.popitem(last=False)


def _save_pin(pin_id, board_id):
    key = (pin_id, board_id)
    with _save_lock:
        if key in _in_progress:
            raise AccountError("此图片正在保存到该画板", 409, "save_in_progress")
        _in_progress.add(key)
    try:
        return _official_call(True, "save_pin", pin_id, board_id)
    finally:
        with _save_lock:
            _in_progress.remove(key)


def _save_error(exc):
    if isinstance(exc, AccountError):
        return _account_json(
            {
                "error": str(exc),
                "code": exc.code
                or ("auth_required" if exc.status == 401 else "invalid_request"),
            },
            status=exc.status,
        )
    if isinstance(exc, PinterestAuthError):
        message, code, status = "Pinterest 连接已失效，请重新连接", "auth_required", 401
    elif isinstance(exc, PinterestTargetBoardError):
        message, code, status = "请选择账号可写的现有普通画板", "board_unavailable", 403
    elif isinstance(exc, PinterestPermissionError):
        message, code, status = (
            "Pinterest 拒绝保存，请核对画板归属和写入权限",
            "write_forbidden",
            403,
        )
    elif isinstance(exc, PinterestTimeoutError):
        message, code, status = (
            "Pinterest 保存请求超时，请先检查画板再重试",
            "save_unconfirmed",
            504,
        )
    elif isinstance(exc, PinterestRateLimitError):
        message, code, status = (
            "Pinterest 请求过于频繁，请稍后重试",
            "rate_limited",
            429,
        )
    elif isinstance(exc, PinterestAPIError) and exc.status == 404:
        message, code, status = (
            "Pinterest 找不到这个 Pin，或当前账号无法访问",
            "pin_not_found",
            404,
        )
    elif isinstance(exc, PinterestAPIError) and exc.status == 400:
        message, code, status = (
            "Pinterest 不接受这次保存请求",
            "pinterest_rejected",
            400,
        )
    else:
        message, code, status = (
            "Pinterest 未确认保存，请先检查画板再重试",
            "save_unconfirmed",
            502,
        )
    return _account_json({"error": message, "code": code}, status=status)


async def search_handler(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON body"}, status=400)

    query = (body.get("query") or "").strip()
    if not query:
        return web.json_response({"error": "query is required"}, status=400)
    bookmark = body.get("bookmark")

    try:
        items, next_bookmark = await asyncio.to_thread(_client.search, query, bookmark)
    except Exception as exc:
        return web.json_response(
            {"error": f"Pinterest search failed: {exc}"}, status=502
        )

    _remember_pin_ids(items)
    return web.json_response({"items": items, "bookmark": next_bookmark})


async def boards_handler(request):
    try:
        items, bookmark = await asyncio.to_thread(
            _official_call,
            _same_origin_local(request),
            "list_boards",
            request.query.get("bookmark"),
        )
    except Exception as exc:
        return _official_error_response(exc)
    return _account_json({"items": items, "bookmark": bookmark})


async def board_pins_handler(request):
    board_id = request.match_info["board_id"]
    try:
        items, bookmark = await asyncio.to_thread(
            _official_call,
            _same_origin_local(request),
            "list_board_pins",
            board_id,
            request.query.get("bookmark"),
        )
    except Exception as exc:
        return _official_error_response(exc)
    _remember_pin_ids(items)
    return _account_json({"items": items, "bookmark": bookmark})


async def save_pin_handler(request):
    try:
        _, body = await _account_body(request)
        if body.get("confirm") is not True:
            raise AccountError("请先确认本次保存", 400, "confirmation_required")
        pin_id = decimal_id(body.get("pin_id"))
        if pin_id is None or _verified_pins.get(pin_id, 0) <= time.monotonic():
            raise AccountError(
                "没有可验证的 Pinterest Pin ID，请重新打开或刷新画廊",
                422,
                "pin_unverified",
            )
        board_id = decimal_id(body.get("board_id"))
        if board_id is None:
            raise AccountError("请选择有效的 Pinterest 画板", 400, "board_invalid")
        result = await asyncio.to_thread(_save_pin, pin_id, board_id)
        if result["item"] is not None:
            _remember_pin_ids([result["item"]])
        return _account_json(result)
    except (AccountError, PinterestAPIError, ValueError) as exc:
        return _save_error(exc)


def setup_routes(routes):
    routes.post("/pinterest_gallery/search")(search_handler)
    routes.get("/pinterest_gallery/boards")(boards_handler)
    routes.get("/pinterest_gallery/boards/{board_id}/pins")(board_pins_handler)
    routes.post("/pinterest_gallery/pins/save")(save_pin_handler)
    routes.get(ACCOUNT_PATH + "/status")(account_status_handler)
    routes.post(ACCOUNT_PATH + "/token")(account_token_handler)
    routes.post(ACCOUNT_PATH + "/oauth/start")(account_oauth_start_handler)
    routes.get(CALLBACK_PATH)(account_oauth_callback_handler)
    routes.post(ACCOUNT_PATH + "/logout")(account_logout_handler)
