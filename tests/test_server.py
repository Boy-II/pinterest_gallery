from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pinterest_gallery import server as pinterest_server
from pinterest_gallery.pinterest_api import PinterestAuthError


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


async def test_boards_handler_returns_items_and_bookmark(monkeypatch):
    monkeypatch.setattr(
        pinterest_server._official_client,
        "list_boards",
        lambda bookmark=None: ([{"id": "b1", "name": "Ideas"}], "next"),
    )
    client = await _make_client()
    async with client:
        resp = await client.get("/pinterest_gallery/boards")
        assert resp.status == 200
        assert await resp.json() == {"items": [{"id": "b1", "name": "Ideas"}], "bookmark": "next"}


async def test_board_pins_handler_passes_board_id_and_bookmark(monkeypatch):
    seen = {}

    def _list(board_id, bookmark=None):
        seen.update(board_id=board_id, bookmark=bookmark)
        return ([{"id": "p1", "thumbnail_url": "t", "image_url": "i"}], None)

    monkeypatch.setattr(pinterest_server._official_client, "list_board_pins", _list)
    client = await _make_client()
    async with client:
        resp = await client.get("/pinterest_gallery/boards/board_1/pins?bookmark=next")
        assert resp.status == 200
        assert seen == {"board_id": "board_1", "bookmark": "next"}


async def test_official_auth_error_does_not_leak_token(monkeypatch):
    secret = "super-secret-token"

    def _raise(bookmark=None):
        raise PinterestAuthError("Pinterest access token is invalid or expired", 401)

    monkeypatch.setattr(pinterest_server._official_client, "list_boards", _raise)
    client = await _make_client()
    async with client:
        resp = await client.get("/pinterest_gallery/boards")
        payload = await resp.json()
        assert resp.status == 401
        assert secret not in str(payload)
