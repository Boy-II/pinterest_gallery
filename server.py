import asyncio

from aiohttp import web

from .pinterest_api import (
    PinterestAPIError,
    PinterestAuthError,
    PinterestClient,
    PinterestOfficialClient,
    PinterestPermissionError,
    PinterestRateLimitError,
    PinterestTimeoutError,
)

_client = PinterestClient()
_official_client = PinterestOfficialClient()


def _official_error_response(exc):
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


async def boards_handler(request):
    try:
        items, bookmark = await asyncio.to_thread(
            _official_client.list_boards, request.query.get("bookmark")
        )
    except Exception as exc:
        return _official_error_response(exc)
    return web.json_response({"items": items, "bookmark": bookmark})


async def board_pins_handler(request):
    board_id = request.match_info["board_id"]
    try:
        items, bookmark = await asyncio.to_thread(
            _official_client.list_board_pins,
            board_id,
            request.query.get("bookmark"),
        )
    except Exception as exc:
        return _official_error_response(exc)
    return web.json_response({"items": items, "bookmark": bookmark})


def setup_routes(routes):
    routes.post("/pinterest_gallery/search")(search_handler)
    routes.get("/pinterest_gallery/boards")(boards_handler)
    routes.get("/pinterest_gallery/boards/{board_id}/pins")(board_pins_handler)
