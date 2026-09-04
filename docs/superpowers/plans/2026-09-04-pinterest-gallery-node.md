# Pinterest Gallery ComfyUI Node Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a ComfyUI custom node that lets a user search Pinterest by keyword, browse results as an in-node thumbnail grid with infinite scroll, click one thumbnail to select it, and get that pin's original-resolution image as a standard `IMAGE` output when the workflow runs.

**Architecture:** A Python aiohttp route (`/pinterest_gallery/search`) proxies keyword searches to Pinterest's internal `BaseSearchResource` JSON endpoint and returns thumbnail/original URLs plus a pagination `bookmark`. A frontend JS widget (`app.registerExtension` + `addDOMWidget`) renders the search box and grid inside the node, calls that route, and uses an `IntersectionObserver` to auto-load more results on scroll. The selected pin's data is written into a hidden `STRING` widget that ComfyUI serializes as a normal node input. At execution time, the node's Python `load()` method downloads the selected image and converts it to an `IMAGE` tensor.

**Tech Stack:** Python (`requests`, `aiohttp`, `PIL`, `numpy`, `torch` — all already present in a ComfyUI install except `requests`), vanilla JS (ComfyUI frontend extension API), `pytest` for backend tests.

**Spec:** `docs/superpowers/specs/2026-09-04-pinterest-gallery-node-design.md`

## Global Constraints

- No Pinterest login / no access to private boards (spec: 目標)
- Single-image selection only — no multi-select / batch output (spec: 非目標)
- No persistent local cache database — in-memory only during node lifetime (spec: 非目標)
- No headless browser (Playwright/Selenium) dependency (spec: 非目標)
- Infinite scroll only — no "load more" button / classic pagination UI (spec: 非目標, confirmed by user 2026-09-04)
- Selected image output must be the Pinterest "original" resolution, not a resized thumbnail (spec: 資料流 step 6)
- Deploy target for manual verification: Windows host `192.168.1.180`, ComfyUI at `E:\ComfyUI-aki-v2\ComfyUI` (aki portable build with its own embedded Python) — see [[remote-comfyui-env]] memory

---

## File Structure

```
pinterest_gallery/                  (repo root == deployed custom_nodes folder name)
├── __init__.py                     # NODE_CLASS_MAPPINGS, WEB_DIRECTORY, ComfyUI route registration
├── nodes.py                        # PinterestGalleryLoader node class
├── server.py                       # aiohttp route handler + setup_routes()
├── pinterest_api.py                # PinterestClient (network) + parse_search_response (pure)
├── web/
│   └── pinterest_gallery.js        # search box + grid + infinite scroll widget
├── conftest.py                     # makes the repo importable as the `pinterest_gallery` package in tests
├── pytest.ini
├── requirements.txt                # runtime deps beyond what ComfyUI already ships
├── requirements-dev.txt            # + test-only deps (pytest, aiohttp, pillow, numpy, torch)
├── .gitignore
└── tests/
    ├── fixtures/
    │   └── search_response.json
    ├── test_pinterest_api.py
    ├── test_server.py
    ├── test_nodes.py
    └── test_init.py
```

**Why relative imports + `conftest.py`:** ComfyUI loads a custom node folder as a real Python package (it sets `submodule_search_locations` to the folder when importing `__init__.py`), so internal modules must use relative imports (`from .pinterest_api import ...`) to work at runtime. `conftest.py` puts the repo's *parent* directory on `sys.path` so pytest can import the same code the same way, as `pinterest_gallery.<module>`, without needing a real ComfyUI install.

---

### Task 1: Search response parser + project scaffolding

**Files:**
- Create: `pinterest_gallery/__init__.py` (empty for now — filled in by Task 5)
- Create: `pinterest_gallery/pinterest_api.py`
- Create: `pinterest_gallery/conftest.py`
- Create: `pinterest_gallery/pytest.ini`
- Create: `pinterest_gallery/requirements.txt`
- Create: `pinterest_gallery/requirements-dev.txt`
- Create: `pinterest_gallery/.gitignore`
- Create: `pinterest_gallery/tests/fixtures/search_response.json`
- Test: `pinterest_gallery/tests/test_pinterest_api.py`

**Interfaces:**
- Produces: `parse_search_response(response_json: dict) -> tuple[list[dict], str | None]`. Each item dict has keys `id: str`, `thumbnail_url: str`, `image_url: str`. Second tuple element is the next-page `bookmark` cursor or `None`.

- [ ] **Step 1: Create scaffolding files**

`pinterest_gallery/__init__.py` (empty file, 0 bytes).

`pinterest_gallery/conftest.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

`pinterest_gallery/pytest.ini`:
```ini
[pytest]
testpaths = tests
asyncio_mode = auto
```

`pinterest_gallery/requirements.txt`:
```
requests
```

`pinterest_gallery/requirements-dev.txt`:
```
-r requirements.txt
pytest>=7
pytest-asyncio
aiohttp
pillow
numpy
torch
```

`pinterest_gallery/.gitignore`:
```
__pycache__/
*.pyc
.pytest_cache/
```

- [ ] **Step 2: Create the fixture**

`pinterest_gallery/tests/fixtures/search_response.json`:
```json
{
  "resource_response": {
    "status": "success",
    "data": {
      "results": [
        {
          "id": "111111111111111111",
          "images": {
            "236x": {"url": "https://i.pinimg.com/236x/aa/bb/cc/aabbccdd.jpg", "width": 236, "height": 354},
            "orig": {"url": "https://i.pinimg.com/originals/aa/bb/cc/aabbccdd.jpg", "width": 1000, "height": 1500}
          }
        },
        {
          "id": "222222222222222222",
          "images": {
            "236x": {"url": "https://i.pinimg.com/236x/ee/ff/gg/eeffgghh.jpg", "width": 236, "height": 236},
            "orig": {"url": "https://i.pinimg.com/originals/ee/ff/gg/eeffgghh.jpg", "width": 900, "height": 900}
          }
        }
      ],
      "bookmark": "Y2JvYXJkX2ZlZWQ6NTA="
    }
  }
}
```

- [ ] **Step 3: Write the failing test**

`pinterest_gallery/tests/test_pinterest_api.py`:
```python
import json
from pathlib import Path

from pinterest_gallery.pinterest_api import parse_search_response

FIXTURE = Path(__file__).parent / "fixtures" / "search_response.json"


def test_parse_search_response_extracts_items_and_bookmark():
    response_json = json.loads(FIXTURE.read_text())

    items, bookmark = parse_search_response(response_json)

    assert items == [
        {
            "id": "111111111111111111",
            "thumbnail_url": "https://i.pinimg.com/236x/aa/bb/cc/aabbccdd.jpg",
            "image_url": "https://i.pinimg.com/originals/aa/bb/cc/aabbccdd.jpg",
        },
        {
            "id": "222222222222222222",
            "thumbnail_url": "https://i.pinimg.com/236x/ee/ff/gg/eeffgghh.jpg",
            "image_url": "https://i.pinimg.com/originals/ee/ff/gg/eeffgghh.jpg",
        },
    ]
    assert bookmark == "Y2JvYXJkX2ZlZWQ6NTA="


def test_parse_search_response_handles_empty_results():
    items, bookmark = parse_search_response(
        {"resource_response": {"data": {"results": [], "bookmark": None}}}
    )

    assert items == []
    assert bookmark is None


def test_parse_search_response_skips_results_missing_image_urls():
    response_json = {
        "resource_response": {
            "data": {
                "results": [{"id": "1", "images": {}}],
                "bookmark": None,
            }
        }
    }

    items, bookmark = parse_search_response(response_json)

    assert items == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pinterest_gallery && pip install -r requirements-dev.txt && python -m pytest tests/test_pinterest_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pinterest_gallery.pinterest_api'` (or `ImportError`, since `pinterest_api.py` doesn't exist yet).

- [ ] **Step 4: Write minimal implementation**

`pinterest_gallery/pinterest_api.py`:
```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_pinterest_api.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Commit**

```bash
cd pinterest_gallery
git add __init__.py pinterest_api.py conftest.py pytest.ini requirements.txt requirements-dev.txt .gitignore tests/
git commit -m "feat: add Pinterest search response parser with scaffolding"
```

---

### Task 2: PinterestClient — live search against Pinterest

**Files:**
- Modify: `pinterest_gallery/pinterest_api.py`
- Create: `pinterest_gallery/scripts/manual_search_check.py`

**Interfaces:**
- Consumes: `parse_search_response` from Task 1 (same file).
- Produces: `PinterestClient` class with `.search(query: str, bookmark: str | None = None) -> tuple[list[dict], str | None]` (same return shape as `parse_search_response`).

- [ ] **Step 1: Add `PinterestClient` to `pinterest_api.py`**

Append to `pinterest_gallery/pinterest_api.py`:
```python
import json
import time
from urllib.parse import quote

import requests

SEARCH_URL = "https://www.pinterest.com/resource/BaseSearchResource/get/"
HOME_URL = "https://www.pinterest.com/"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


class PinterestClient:
    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self._bootstrapped = False

    def _bootstrap(self):
        # A cookie-less request to the search endpoint gets rejected; loading
        # the homepage first gives us the csrftoken cookie Pinterest expects.
        if self._bootstrapped:
            return
        resp = self.session.get(HOME_URL, timeout=10)
        resp.raise_for_status()
        self._bootstrapped = True

    def search(self, query, bookmark=None):
        self._bootstrap()

        options = {"query": query, "scope": "pins", "rs": "typed"}
        if bookmark:
            options["bookmarks"] = [bookmark]

        params = {
            "source_url": f"/search/pins/?q={quote(query)}",
            "data": json.dumps({"options": options, "context": {}}),
            "_": str(int(time.time() * 1000)),
        }
        headers = {
            "Accept": "application/json, text/javascript, */*, q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "X-CSRFToken": self.session.cookies.get("csrftoken", ""),
            "Referer": f"https://www.pinterest.com/search/pins/?q={quote(query)}",
        }

        resp = self.session.get(SEARCH_URL, params=params, headers=headers, timeout=10)
        resp.raise_for_status()
        return parse_search_response(resp.json())
```

Move the existing `parse_search_response` function above this new code if needed so it's defined before use (Python only needs it defined before *call* time, not before this class definition, so no reordering is actually required — leave `parse_search_response` where it is from Task 1).

- [ ] **Step 2: Write the manual verification script**

`pinterest_gallery/scripts/manual_search_check.py`:
```python
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from pinterest_gallery.pinterest_api import PinterestClient


def main():
    query = sys.argv[1] if len(sys.argv) > 1 else "cyberpunk city"
    client = PinterestClient()
    items, bookmark = client.search(query)
    print(f"query={query!r} got {len(items)} items, bookmark={bookmark!r}")
    for item in items[:3]:
        print(item)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the manual check against the real Pinterest site**

Run: `python pinterest_gallery/scripts/manual_search_check.py "cyberpunk city"`

Expected: prints `got N items` with `N > 0`, and each printed item has non-empty `thumbnail_url`/`image_url` fields.

**If it fails or returns 0 items:** Pinterest's response shape may not match the `resource_response.data.results[].images["orig"|"236x"].url` / `resource_response.data.bookmark` structure assumed in Task 1 — this is expected fragility called out in the spec's Risks section, not a bug in this plan's logic. Debug by temporarily adding `print(resp.json())` (or `print(resp.status_code, resp.text[:2000])` if it's not valid JSON) inside `search()`, inspect the real payload, then:
1. Update `parse_search_response` in `pinterest_api.py` to match the real field paths.
2. Update `tests/fixtures/search_response.json` to reflect the real shape (with the same 2-item/bookmark structure as the fixture above, values redacted/replaced with the real field paths but placeholder-looking URLs are fine).
3. Re-run `python -m pytest tests/test_pinterest_api.py -v` to confirm it still passes.
4. Re-run this manual script to confirm it now returns real items.

If outbound HTTPS to pinterest.com isn't reachable from this machine, run the same script from a machine that does have internet access (e.g. copy `pinterest_api.py` to the Windows ComfyUI host and run it there with its embedded Python, since that host will need working internet access anyway for the deployed node to function).

- [ ] **Step 4: Commit**

```bash
cd pinterest_gallery
git add pinterest_api.py scripts/manual_search_check.py
git commit -m "feat: add PinterestClient for live Pinterest search"
```

---

### Task 3: `/pinterest_gallery/search` aiohttp route

**Files:**
- Create: `pinterest_gallery/server.py`
- Test: `pinterest_gallery/tests/test_server.py`

**Interfaces:**
- Consumes: `PinterestClient` from Task 2 (`pinterest_gallery.pinterest_api.PinterestClient`), with `.search(query, bookmark=None) -> (items, bookmark)`.
- Produces: `setup_routes(routes: aiohttp.web.RouteTableDef) -> None`, registering `POST /pinterest_gallery/search`. Module-level `_client: PinterestClient` instance (tests monkeypatch its `.search` method).

- [ ] **Step 1: Write the failing tests**

`pinterest_gallery/tests/test_server.py`:
```python
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pinterest_gallery import server as pinterest_server


async def _make_client():
    routes = web.RouteTableDef()
    pinterest_server.setup_routes(routes)
    app = web.Application()
    app.add_routes(routes)
    return TestClient(TestServer(app))


async def test_search_handler_returns_items(monkeypatch):
    monkeypatch.setattr(
        pinterest_server._client,
        "search",
        lambda query, bookmark=None: (
            [{"id": "1", "thumbnail_url": "t", "image_url": "i"}],
            "next",
        ),
    )
    client = await _make_client()
    async with client:
        resp = await client.post(
            "/pinterest_gallery/search", json={"query": "cats", "bookmark": None}
        )
        assert resp.status == 200
        payload = await resp.json()
        assert payload == {
            "items": [{"id": "1", "thumbnail_url": "t", "image_url": "i"}],
            "bookmark": "next",
        }


async def test_search_handler_rejects_empty_query():
    client = await _make_client()
    async with client:
        resp = await client.post("/pinterest_gallery/search", json={"query": "   "})
        assert resp.status == 400
        payload = await resp.json()
        assert "error" in payload


async def test_search_handler_returns_502_on_client_error(monkeypatch):
    def _raise(query, bookmark=None):
        raise RuntimeError("boom")

    monkeypatch.setattr(pinterest_server._client, "search", _raise)
    client = await _make_client()
    async with client:
        resp = await client.post("/pinterest_gallery/search", json={"query": "cats"})
        assert resp.status == 502
        payload = await resp.json()
        assert "boom" in payload["error"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pinterest_gallery && python -m pytest tests/test_server.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pinterest_gallery.server'`

- [ ] **Step 3: Write minimal implementation**

`pinterest_gallery/server.py`:
```python
from aiohttp import web

from .pinterest_api import PinterestClient

_client = PinterestClient()


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
        items, next_bookmark = _client.search(query, bookmark)
    except Exception as exc:
        return web.json_response(
            {"error": f"Pinterest search failed: {exc}"}, status=502
        )

    return web.json_response({"items": items, "bookmark": next_bookmark})


def setup_routes(routes):
    routes.post("/pinterest_gallery/search")(search_handler)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_server.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd pinterest_gallery
git add server.py tests/test_server.py
git commit -m "feat: add /pinterest_gallery/search aiohttp route"
```

---

### Task 4: `PinterestGalleryLoader` node — download + tensor output

**Files:**
- Create: `pinterest_gallery/nodes.py`
- Test: `pinterest_gallery/tests/test_nodes.py`

**Interfaces:**
- Produces: `PinterestGalleryLoader` class with `INPUT_TYPES()`, `RETURN_TYPES = ("IMAGE",)`, `FUNCTION = "load"`, `CATEGORY = "image/pinterest"`, and `load(self, selected_pin: str) -> tuple[torch.Tensor]`. `NODE_CLASS_MAPPINGS = {"PinterestGalleryLoader": PinterestGalleryLoader}` and `NODE_DISPLAY_NAME_MAPPINGS = {"PinterestGalleryLoader": "Pinterest Gallery Loader"}`.
- The `selected_pin` widget value is a JSON string `{"id": str, "image_url": str}`, written by the frontend widget in Task 6.

- [ ] **Step 1: Write the failing tests**

`pinterest_gallery/tests/test_nodes.py`:
```python
import io
import json

import pytest
from PIL import Image

from pinterest_gallery.nodes import PinterestGalleryLoader


def _fake_png_bytes(width=4, height=4, color=(255, 0, 0)):
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_load_downloads_and_converts_selected_image(monkeypatch):
    png_bytes = _fake_png_bytes()
    monkeypatch.setattr(
        "pinterest_gallery.nodes.requests.get",
        lambda url, timeout=20: _FakeResponse(png_bytes),
    )
    node = PinterestGalleryLoader()
    selected_pin = json.dumps(
        {"id": "1", "image_url": "https://i.pinimg.com/originals/x.jpg"}
    )

    (tensor,) = node.load(selected_pin)

    assert tensor.shape == (1, 4, 4, 3)
    assert str(tensor.dtype) == "torch.float32"
    assert tensor.max().item() <= 1.0
    assert tensor.min().item() >= 0.0


def test_load_raises_on_empty_selection():
    node = PinterestGalleryLoader()
    with pytest.raises(ValueError):
        node.load("")


def test_load_raises_on_invalid_json():
    node = PinterestGalleryLoader()
    with pytest.raises(ValueError):
        node.load("not json")


def test_input_types_declares_selected_pin_string():
    input_types = PinterestGalleryLoader.INPUT_TYPES()
    assert input_types["required"]["selected_pin"][0] == "STRING"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd pinterest_gallery && python -m pytest tests/test_nodes.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pinterest_gallery.nodes'`

- [ ] **Step 3: Write minimal implementation**

`pinterest_gallery/nodes.py`:
```python
import io
import json

import numpy as np
import requests
import torch
from PIL import Image


class PinterestGalleryLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "selected_pin": ("STRING", {"default": "", "multiline": False}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "load"
    CATEGORY = "image/pinterest"

    def load(self, selected_pin):
        if not selected_pin:
            raise ValueError(
                "No Pinterest image selected. Search and click a thumbnail "
                "on the node before running the workflow."
            )
        try:
            pin = json.loads(selected_pin)
            image_url = pin["image_url"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"Invalid selected_pin value: {selected_pin!r}") from exc

        resp = requests.get(image_url, timeout=20)
        resp.raise_for_status()

        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
        array = np.array(image).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array)[None,]
        return (tensor,)


NODE_CLASS_MAPPINGS = {"PinterestGalleryLoader": PinterestGalleryLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"PinterestGalleryLoader": "Pinterest Gallery Loader"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_nodes.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
cd pinterest_gallery
git add nodes.py tests/test_nodes.py
git commit -m "feat: add PinterestGalleryLoader node"
```

---

### Task 5: Package wiring — `__init__.py`

**Files:**
- Modify: `pinterest_gallery/__init__.py`
- Test: `pinterest_gallery/tests/test_init.py`

**Interfaces:**
- Consumes: `NODE_CLASS_MAPPINGS`, `NODE_DISPLAY_NAME_MAPPINGS` from Task 4 (`pinterest_gallery.nodes`); `setup_routes` from Task 3 (`pinterest_gallery.server`).
- Produces: package-level `pinterest_gallery.NODE_CLASS_MAPPINGS`, `pinterest_gallery.NODE_DISPLAY_NAME_MAPPINGS`, `pinterest_gallery.WEB_DIRECTORY` — the three names ComfyUI's loader looks for on a custom node package.

- [ ] **Step 1: Write the failing test**

`pinterest_gallery/tests/test_init.py`:
```python
import pinterest_gallery
from pinterest_gallery.nodes import PinterestGalleryLoader


def test_package_exports_node_mappings():
    assert pinterest_gallery.NODE_CLASS_MAPPINGS == {
        "PinterestGalleryLoader": PinterestGalleryLoader
    }
    assert pinterest_gallery.NODE_DISPLAY_NAME_MAPPINGS == {
        "PinterestGalleryLoader": "Pinterest Gallery Loader"
    }
    assert pinterest_gallery.WEB_DIRECTORY == "web"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd pinterest_gallery && python -m pytest tests/test_init.py -v`
Expected: FAIL — `AttributeError: module 'pinterest_gallery' has no attribute 'NODE_CLASS_MAPPINGS'`

- [ ] **Step 3: Write the implementation**

`pinterest_gallery/__init__.py`:
```python
from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "web"

try:
    # Only present inside a running ComfyUI process; lets this package be
    # imported (e.g. by pytest) without a real ComfyUI install.
    from server import PromptServer

    from .server import setup_routes

    setup_routes(PromptServer.instance.routes)
except ImportError:
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_init.py -v`
Expected: PASS

- [ ] **Step 5: Run the full test suite**

Run: `python -m pytest -v`
Expected: all tests across `test_pinterest_api.py`, `test_server.py`, `test_nodes.py`, `test_init.py` PASS.

- [ ] **Step 6: Commit**

```bash
cd pinterest_gallery
git add __init__.py tests/test_init.py
git commit -m "feat: wire node mappings and route registration into __init__"
```

---

### Task 6: Frontend gallery widget

**Files:**
- Create: `pinterest_gallery/web/pinterest_gallery.js`

**Interfaces:**
- Consumes: `POST /pinterest_gallery/search` from Task 3, request body `{query: string, bookmark: string|null}`, response `{items: [{id, thumbnail_url, image_url}], bookmark: string|null}` or `{error: string}`.
- Produces: sets the value of the node's `selected_pin` widget (declared in Task 4's `INPUT_TYPES`) to a JSON string `{"id": string, "image_url": string}` when a thumbnail is clicked.

- [ ] **Step 1: Write the widget**

`pinterest_gallery/web/pinterest_gallery.js`:
```javascript
import { app } from "../../scripts/app.js";

const CSS = `
.pinterest-gallery-wrap { display:flex; flex-direction:column; gap:4px; width:100%; }
.pinterest-gallery-search { width:100%; box-sizing:border-box; }
.pinterest-gallery-grid { display:grid; grid-template-columns:repeat(3,1fr); gap:4px; max-height:260px; overflow-y:auto; background:#1a1a1a; padding:4px; border-radius:4px; }
.pinterest-gallery-thumb { width:100%; aspect-ratio:1/1; object-fit:cover; cursor:pointer; border:2px solid transparent; border-radius:3px; display:block; }
.pinterest-gallery-thumb.selected { border-color:#4caf50; }
.pinterest-gallery-status { font-size:11px; color:#aaa; min-height:14px; }
`;

function injectCss() {
  if (document.getElementById("pinterest-gallery-css")) return;
  const style = document.createElement("style");
  style.id = "pinterest-gallery-css";
  style.textContent = CSS;
  document.head.appendChild(style);
}

app.registerExtension({
  name: "pinterest_gallery.widget",
  async beforeRegisterNodeDef(nodeType, nodeData) {
    if (nodeData.name !== "PinterestGalleryLoader") return;

    const onNodeCreated = nodeType.prototype.onNodeCreated;
    nodeType.prototype.onNodeCreated = function () {
      onNodeCreated?.apply(this, arguments);
      injectCss();

      const node = this;
      const selectedWidget = node.widgets.find((w) => w.name === "selected_pin");
      if (selectedWidget) {
        // Keep it as a real serialized widget (so its value ships with the
        // prompt) but stop LiteGraph from drawing/sizing it.
        selectedWidget.computeSize = () => [0, -4];
        selectedWidget.draw = () => {};
      }

      const wrap = document.createElement("div");
      wrap.className = "pinterest-gallery-wrap";

      const input = document.createElement("input");
      input.className = "pinterest-gallery-search";
      input.type = "text";
      input.placeholder = "Search Pinterest...";

      const status = document.createElement("div");
      status.className = "pinterest-gallery-status";

      const grid = document.createElement("div");
      grid.className = "pinterest-gallery-grid";

      const sentinel = document.createElement("div");
      sentinel.style.height = "1px";
      grid.appendChild(sentinel);

      wrap.appendChild(input);
      wrap.appendChild(status);
      wrap.appendChild(grid);

      let currentQuery = "";
      let bookmark = null;
      let loading = false;
      let debounceTimer = null;

      const setSelected = (item, imgEl) => {
        grid
          .querySelectorAll(".pinterest-gallery-thumb.selected")
          .forEach((el) => el.classList.remove("selected"));
        imgEl.classList.add("selected");
        if (selectedWidget) {
          selectedWidget.value = JSON.stringify({
            id: item.id,
            image_url: item.image_url,
          });
        }
      };

      const addItems = (items) => {
        for (const item of items) {
          const img = document.createElement("img");
          img.className = "pinterest-gallery-thumb";
          img.src = item.thumbnail_url;
          img.loading = "lazy";
          img.addEventListener("click", () => setSelected(item, img));
          grid.insertBefore(img, sentinel);
        }
      };

      const runSearch = async (query, nextBookmark) => {
        if (loading) return;
        loading = true;
        status.textContent = "Loading...";
        try {
          const resp = await fetch("/pinterest_gallery/search", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ query, bookmark: nextBookmark }),
          });
          const data = await resp.json();
          if (!resp.ok) {
            status.textContent = data.error || "Search failed";
            bookmark = null;
            return;
          }
          addItems(data.items || []);
          bookmark = data.bookmark || null;
          status.textContent = data.items && data.items.length ? "" : "No results";
        } catch (err) {
          status.textContent = "Search failed: " + err.message;
          bookmark = null;
        } finally {
          loading = false;
        }
      };

      input.addEventListener("input", () => {
        clearTimeout(debounceTimer);
        const query = input.value.trim();
        debounceTimer = setTimeout(() => {
          if (!query || query === currentQuery) return;
          currentQuery = query;
          bookmark = null;
          grid.querySelectorAll(".pinterest-gallery-thumb").forEach((el) => el.remove());
          runSearch(query, null);
        }, 500);
      });

      const observer = new IntersectionObserver(
        (entries) => {
          if (entries[0].isIntersecting && bookmark && !loading && currentQuery) {
            runSearch(currentQuery, bookmark);
          }
        },
        { root: grid }
      );
      observer.observe(sentinel);

      node.addDOMWidget("pinterest_gallery_ui", "div", wrap, { serialize: false });

      const onRemoved = node.onRemoved;
      node.onRemoved = function () {
        observer.disconnect();
        onRemoved?.apply(this, arguments);
      };
    };
  },
});
```

- [ ] **Step 2: Syntax-check the file**

Run: `node --check pinterest_gallery/web/pinterest_gallery.js`
Expected: no output, exit code 0. If `node` isn't installed locally, skip this step — it will be exercised for real in Task 7's browser verification.

- [ ] **Step 3: Commit**

```bash
cd pinterest_gallery
git add web/pinterest_gallery.js
git commit -m "feat: add Pinterest gallery search/select frontend widget"
```

---

### Task 7: Deploy to the remote ComfyUI host and verify end-to-end

**Files:** none (deployment + manual verification only)

**Interfaces:**
- Consumes: every file produced by Tasks 1–6.

- [ ] **Step 1: Confirm the remote `custom_nodes` path and embedded Python**

```bash
ssh <ssh-user>@192.168.1.180 "dir \"E:\\ComfyUI-aki-v2\\ComfyUI\\custom_nodes\""
```
Expected: lists the existing custom node folders, confirming the path from [[remote-comfyui-env]] is correct. Adjust the path in the remaining steps if it differs.

```bash
ssh <ssh-user>@192.168.1.180 "\"E:\\ComfyUI-aki-v2\\python\\python.exe\" -c \"import requests; print(requests.__version__)\""
```
Expected: prints a version string. If it errors with `ModuleNotFoundError`, install it first:
```bash
ssh <ssh-user>@192.168.1.180 "\"E:\\ComfyUI-aki-v2\\python\\python.exe\" -m pip install requests"
```
(If the embedded Python isn't at `E:\ComfyUI-aki-v2\python\python.exe`, use `dir E:\ComfyUI-aki-v2` over SSH first to locate it — aki-style builds commonly name this folder `python` or `python_embeded`.)

- [ ] **Step 2: Copy the runtime files (not tests/docs/dev tooling)**

```bash
ssh <ssh-user>@192.168.1.180 "mkdir \"E:\\ComfyUI-aki-v2\\ComfyUI\\custom_nodes\\pinterest_gallery\\web\""
scp /Volumes/Data/Hub/pinterest_gallery/__init__.py \
    /Volumes/Data/Hub/pinterest_gallery/nodes.py \
    /Volumes/Data/Hub/pinterest_gallery/server.py \
    /Volumes/Data/Hub/pinterest_gallery/pinterest_api.py \
    /Volumes/Data/Hub/pinterest_gallery/requirements.txt \
    <ssh-user>@192.168.1.180:"E:/ComfyUI-aki-v2/ComfyUI/custom_nodes/pinterest_gallery/"
scp /Volumes/Data/Hub/pinterest_gallery/web/pinterest_gallery.js \
    <ssh-user>@192.168.1.180:"E:/ComfyUI-aki-v2/ComfyUI/custom_nodes/pinterest_gallery/web/"
```
Expected: both `scp` commands complete without error.

- [ ] **Step 3: Restart ComfyUI on the remote host**

Use the `starting-comfyui-over-windows-ssh` skill to restart the ComfyUI process on `192.168.1.180` so it picks up the new custom node.

- [ ] **Step 4: Manual browser verification**

Open the ComfyUI web UI and check each of the following:

1. Right-click canvas → Add Node → find **Pinterest Gallery Loader** under the `image/pinterest` category, add it.
2. Type a search query (e.g. "cyberpunk city") into the node's search box. Within a few seconds, thumbnails appear in the grid.
   - If instead the status line shows an error, re-run `python scripts/manual_search_check.py` locally (Task 2) to check whether Pinterest's response shape changed and needs a `parse_search_response` fix — then redeploy `pinterest_api.py`.
3. Scroll the thumbnail grid down to the bottom. More thumbnails load automatically without any button click (infinite scroll).
4. Click a thumbnail. It gets a green highlight border, and clicking a different one moves the highlight (single selection).
5. Connect the node's `IMAGE` output into a **Preview Image** node and queue the prompt. The previewed image matches the selected pin, at its full original resolution (not a small/blurry thumbnail).
6. Queue the prompt again with no thumbnail ever selected (fresh node, empty `selected_pin`) — confirm ComfyUI shows a clear red node error (from the `ValueError` in `load()`), not a silent failure or crash of the whole server.

- [ ] **Step 5: Record final status**

If all six checks pass, the feature is complete. If any check fails, fix the relevant task's code locally, re-run that task's `pytest` suite, redeploy the changed file(s) via Step 2, restart via Step 3, and re-verify.
