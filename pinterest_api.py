import json
import os
import re
import time
from urllib.parse import quote, quote_plus

import requests


OFFICIAL_API_URLS = {
    "sandbox": "https://api-sandbox.pinterest.com/v5",
    "production": "https://api.pinterest.com/v5",
}
BOARD_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")


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


def _image_entries(pin):
    media = pin.get("media") or {}
    images = media.get("images") or pin.get("images") or {}
    entries = []
    for key, value in images.items():
        if not isinstance(value, dict) or not value.get("url"):
            continue
        width = value.get("width") or 0
        height = value.get("height") or 0
        try:
            area = int(width) * int(height)
        except (TypeError, ValueError):
            area = 0
        entries.append((str(key), value["url"], area))
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
        entries.sort(key=lambda entry: entry[2])
        image_url = entries[-1][1]
        preferred_thumbs = ("400x300", "236x", "150x150", "236x236")
        thumbnail_url = next(
            (url for key, url, _ in entries if key in preferred_thumbs),
            entries[0][1],
        )
        items.append(
            {
                "id": str(pin_id),
                "thumbnail_url": thumbnail_url,
                "image_url": image_url,
            }
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
        items.append(
            {
                "id": str(result.get("id")),
                "thumbnail_url": thumb["url"],
                "image_url": orig["url"],
            }
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
        self.token = (token if token is not None else os.getenv("PINTEREST_ACCESS_TOKEN", "")).strip()
        self.session = session or requests.Session()
        self.timeout = timeout
        self.environment = (environment or os.getenv("PINTEREST_API_ENV", "sandbox")).strip().lower()
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

    def _request(self, method, path, params=None):
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
            )
        except requests.Timeout as exc:
            raise PinterestTimeoutError("Pinterest API request timed out") from exc
        except requests.RequestException as exc:
            raise PinterestAPIError("Pinterest API request failed") from exc

        if response.status_code == 401:
            raise PinterestAuthError("Pinterest access token is invalid or expired", 401)
        if response.status_code == 403:
            raise PinterestPermissionError("Pinterest token lacks required permissions", 403)
        if response.status_code == 429:
            raise PinterestRateLimitError("Pinterest API rate limit reached", 429)
        if response.status_code >= 400:
            raise PinterestAPIError(
                f"Pinterest API returned HTTP {response.status_code}",
                response.status_code,
            )
        try:
            return response.json()
        except ValueError as exc:
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
