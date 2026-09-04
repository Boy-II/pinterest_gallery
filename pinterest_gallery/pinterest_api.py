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


import json
import time
from urllib.parse import quote

import requests

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
