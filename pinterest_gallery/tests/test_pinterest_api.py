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
