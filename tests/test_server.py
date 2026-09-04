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
