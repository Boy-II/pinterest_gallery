import json
import os
import re
import time
from urllib.parse import quote, quote_plus, urlsplit

import requests


OFFICIAL_API_URLS = {
    "sandbox": "https://api-sandbox.pinterest.com/v5",
    "production": "https://api.pinterest.com/v5",
}
BOARD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
DECIMAL_ID_RE = re.compile(r"[0-9]{1,64}")
PIN_PATH_RE = re.compile(r"/pin/([0-9]{1,64})/?")


class PinterestAPIError(RuntimeError):
    """Safe, user-facing error from the official Pinterest API."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


class PinterestAuthError(PinterestAPIError):
    pass


class PinterestPermissionError(PinterestAPIError):
    pass


class PinterestRateLimitError(PinterestAPIError):
    pass


class PinterestTimeoutError(PinterestAPIError):
    pass


class PinterestTargetBoardError(PinterestAPIError):
    pass


def decimal_id(value):
    return value if isinstance(value, str) and DECIMAL_ID_RE.fullmatch(value) else None


def _pin_url_id(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (url.netloc or url.scheme) and (
            url.scheme not in ("", "http", "https")
            or url.hostname not in ("pinterest.com", "www.pinterest.com")
            or url.username is not None
            or url.port not in (None, 80 if url.scheme == "http" else 443)
        ):
            return None
        match = PIN_PATH_RE.fullmatch(url.path)
        return match[1] if match else None
    except ValueError:
        return None


def _search_pin_id(result):
    # The generic search ID can be an opaque identifier. The explicit pin
    # field and a canonical Pinterest Pin URL carry identity independently.
    candidates = {decimal_id(result.get("pin_id"))}
    candidates.update(
        _pin_url_id(result.get(key)) for key in ("pin_url", "canonical_url", "url")
    )
    candidates.discard(None)
    return candidates.pop() if len(candidates) == 1 else None


def _source_image_url(value):
    if not isinstance(value, str):
        return None
    try:
        url = urlsplit(value)
        if (
            url.scheme == "https"
            and url.hostname == "i.pinimg.com"
            and url.username is None
            and url.port in (None, 443)
            and url.path.startswith("/")
        ):
            return value
    except ValueError:
        pass
    return None


def _page_bookmark(response_json):
    bookmark = response_json.get("bookmark")
    return bookmark if isinstance(bookmark, str) and bookmark else None


def parse_boards_response(response_json):
    items = []
    for board in response_json.get("items") or []:
        board_id = board.get("id")
        if not board_id:
            continue
        items.append(
            {
                "id": str(board_id),
                "name": str(board.get("name") or "Unnamed board"),
                "privacy": board.get("privacy"),
                "pin_count": board.get("pin_count"),
            }
        )
    return items, _page_bookmark(response_json)


def _image_dimensions(image):
    try:
        width, height = int(image.get("width") or 0), int(image.get("height") or 0)
    except (TypeError, ValueError, OverflowError):
        return 0, 0
    return max(width, 0), max(height, 0)


def _pin_item(item_id, thumbnail_url, image_url, width, height, title, pin_id):
    item = {
        "id": str(item_id),
        "thumbnail_url": thumbnail_url,
        "image_url": image_url,
        "pin_id": pin_id,
        "source_url": f"https://www.pinterest.com/pin/{pin_id}/" if pin_id else None,
        "source_image_url": _source_image_url(image_url),
    }
    if width and height:
        item.update(width=width, height=height)
    if isinstance(title, str) and title.strip():
        item["title"] = title.strip()
    return item


def _image_entries(pin):
    media = pin.get("media") or {}
    images = media.get("images") or pin.get("images") or {}
    entries = []
    for key, value in images.items():
        if not isinstance(value, dict) or not value.get("url"):
            continue
        width, height = _image_dimensions(value)
        entries.append((str(key), value["url"], width, height))
    return entries


def parse_board_pins_response(response_json):
    items = []
    for pin in response_json.get("items") or []:
        pin_id = pin.get("id")
        if not pin_id:
            continue
        entries = _image_entries(pin)
        if not entries:
            continue
        entries.sort(key=lambda entry: entry[2] * entry[3])
        _, image_url, width, height = entries[-1]
        preferred_thumbs = ("400x300", "236x", "150x150", "236x236")
        urls_by_size = {key: url for key, url, _, _ in entries}
        thumbnail_url = next(
            (urls_by_size[key] for key in preferred_thumbs if key in urls_by_size),
            entries[0][1],
        )
        items.append(
            _pin_item(
                pin_id,
                thumbnail_url,
                image_url,
                width,
                height,
                pin.get("title"),
                decimal_id(pin_id),
            )
        )
    return items, _page_bookmark(response_json)


def parse_search_response(response_json):
    resource_response = response_json.get("resource_response", {})
    data = resource_response.get("data", {})
    results = data.get("results") or []

    items = []
    for result in results:
        images = result.get("images") or {}
        orig = images.get("orig") or {}
        thumb = images.get("236x") or orig
        if not orig.get("url") or not thumb.get("url"):
            continue
        width, height = _image_dimensions(orig)
        title = result.get("title") or result.get("grid_title")
        items.append(
            _pin_item(
                result.get("id"),
                thumb["url"],
                orig["url"],
                width,
                height,
                title,
                _search_pin_id(result),
            )
        )

    bookmark = data.get("bookmark") or resource_response.get("bookmark")
    if isinstance(bookmark, list):
        bookmark = bookmark[0] if bookmark else None
    return items, bookmark


SEARCH_URL = "https://www.pinterest.com/resource/BaseSearchResource/get/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class PinterestClient:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._bootstrapped = False

    def _bootstrap(self, query):
        # A cookie-less request to the search endpoint gets rejected; loading
        # the search page first gives us the csrftoken cookie Pinterest expects.
        if self._bootstrapped:
            return
        resp = self.session.get(
            f"https://www.pinterest.com/search/pins/?q={quote(query)}", timeout=10
        )
        resp.raise_for_status()
        self._bootstrapped = True

    def search(self, query, bookmark=None):
        self._bootstrap(query)

        options = {"query": query, "bookmarks": [bookmark or ""]}

        params = {
            "data": json.dumps({"options": options, "context": {}}),
            "_": str(int(time.time() * 1000)),
        }
        headers = {
            "Accept": "application/json, text/javascript, */*, q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": self.session.cookies.get("csrftoken", ""),
            "X-Pinterest-AppState": "active",
            "X-Pinterest-Source-Url": "/ideas/",
            "X-Pinterest-PWS-Handler": "www/ideas.js",
            "Referer": f"https://www.pinterest.com/search/pins/?q={quote(query)}",
        }

        resp = self.session.get(SEARCH_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return parse_search_response(resp.json())


class PinterestOfficialClient:
    """Small authenticated client for Pinterest API v5 Boards/Pins endpoints."""

    def __init__(self, token=None, session=None, timeout=10, environment=None):
        self.token = (
            token if token is not None else os.getenv("PINTEREST_ACCESS_TOKEN", "")
        ).strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.environment = (
            (environment or os.getenv("PINTEREST_API_ENV", "sandbox")).strip().lower()
        )
        if self.environment not in OFFICIAL_API_URLS:
            raise ValueError("PINTEREST_API_ENV must be sandbox or production")
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
            }
        )

    @property
    def configured(self):
        return bool(self.token)

    def _request(self, method, path, params=None, *, data=None):
        if not self.token:
            raise PinterestAuthError(
                "PINTEREST_ACCESS_TOKEN is not configured", status=401
            )
        try:
            response = self.session.request(
                method,
                f"{OFFICIAL_API_URLS[self.environment]}{path}",
                params=params,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout,
                **(
                    {"json": data, "allow_redirects": False} if data is not None else {}
                ),
            )
        except requests.Timeout as exc:
            raise PinterestTimeoutError("Pinterest API request timed out") from exc
        except requests.RequestException as exc:
            raise PinterestAPIError("Pinterest API request failed") from exc

        if response.status_code == 401:
            raise PinterestAuthError(
                "Pinterest access token is invalid or expired", 401
            )
        if response.status_code == 403:
            raise PinterestPermissionError(
                "Pinterest token lacks required permissions", 403
            )
        if response.status_code == 429:
            raise PinterestRateLimitError("Pinterest API rate limit reached", 429)
        if not 200 <= response.status_code < 300:
            raise PinterestAPIError(
                f"Pinterest API returned HTTP {response.status_code}",
                response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
            if data is not None:
                # A successful write status is authoritative even when the
                # response does not carry usable gallery metadata.
                return None
            raise PinterestAPIError("Pinterest API returned invalid JSON") from exc

    def list_boards(self, bookmark=None):
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        return parse_boards_response(self._request("GET", "/boards", params=params))

    def list_board_pins(self, board_id, bookmark=None):
        board_id = str(board_id or "")
        if not BOARD_ID_RE.fullmatch(board_id):
            raise ValueError("invalid board id")
        params = {"page_size": 100}
        if bookmark:
            params["bookmark"] = bookmark
        path = f"/boards/{quote_plus(board_id)}/pins"
        return parse_board_pins_response(self._request("GET", path, params=params))

    def save_pin(self, pin_id, board_id):
        if decimal_id(pin_id) is None or decimal_id(board_id) is None:
            raise ValueError("Invalid Pinterest Pin or board ID")
        try:
            board = self._request("GET", f"/boards/{board_id}")
        except PinterestAPIError as exc:
            if exc.status in (403, 404):
                raise PinterestTargetBoardError(
                    "Target board unavailable", 403
                ) from None
            raise
        if (
            not isinstance(board, dict)
            or board.get("id") != board_id
            or board.get("privacy") != "PUBLIC"
            or board.get("is_ads_only", False) is not False
        ):
            raise PinterestTargetBoardError("Target board unavailable", 403)
        # Pinterest enforces ownership on this operation. Omitting
        # ad_account_id means the operation user is the token's user.
        data = self._request(
            "POST", f"/pins/{pin_id}/save", data={"board_id": board_id}
        )
        if not isinstance(data, dict):
            return {"item": None, "pin_id": pin_id, "board_id": board_id}
        items, _ = parse_board_pins_response({"items": [data]})
        return {
            "item": items[0] if items else None,
            "pin_id": decimal_id(data.get("id")) or pin_id,
            "board_id": board_id,
        }
