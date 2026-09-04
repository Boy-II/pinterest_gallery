import asyncio

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
        items, next_bookmark = await asyncio.to_thread(
            _client.search, query, bookmark
        )
    except Exception as exc:
        return web.json_response(
            {"error": f"Pinterest search failed: {exc}"}, status=502
        )

    return web.json_response({"items": items, "bookmark": next_bookmark})


def setup_routes(routes):
    routes.post("/pinterest_gallery/search")(search_handler)
