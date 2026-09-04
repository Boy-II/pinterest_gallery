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
