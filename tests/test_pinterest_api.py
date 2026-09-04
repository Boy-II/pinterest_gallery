import json
from pathlib import Path

import pytest

from pinterest_gallery.pinterest_api import (
    PinterestAuthError,
    PinterestOfficialClient,
    parse_board_pins_response,
    parse_boards_response,
    parse_search_response,
)

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


def test_parse_boards_response_extracts_items_and_bookmark():
    items, bookmark = parse_boards_response(
        {
            "items": [{"id": "b1", "name": "Ideas", "privacy": "PUBLIC", "pin_count": 3}],
            "bookmark": "next",
        }
    )
    assert items == [{"id": "b1", "name": "Ideas", "privacy": "PUBLIC", "pin_count": 3}]
    assert bookmark == "next"


def test_parse_board_pins_chooses_largest_image_and_skips_missing_media():
    items, bookmark = parse_board_pins_response(
        {
            "items": [
                {
                    "id": "p1",
                    "media": {
                        "images": {
                            "150x150": {"url": "https://i.pinimg.com/150.jpg", "width": 150, "height": 150},
                            "orig": {"url": "https://i.pinimg.com/orig.jpg", "width": 1000, "height": 800},
                        }
                    },
                },
                {"id": "p2", "media": {"images": {}}},
            ],
            "bookmark": None,
        }
    )
    assert items == [{"id": "p1", "thumbnail_url": "https://i.pinimg.com/150.jpg", "image_url": "https://i.pinimg.com/orig.jpg"}]
    assert bookmark is None


def test_official_client_without_token_fails_without_network(monkeypatch):
    monkeypatch.delenv("PINTEREST_ACCESS_TOKEN", raising=False)
    with pytest.raises(PinterestAuthError, match="not configured"):
        PinterestOfficialClient().list_boards()


def test_official_client_selects_sandbox_endpoint(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"items": [], "bookmark": None}

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self.url = None

        def request(self, method, url, **kwargs):
            self.url = url
            return FakeResponse()

    session = FakeSession()
    PinterestOfficialClient(token="test", session=session).list_boards()
    assert session.url == "https://api-sandbox.pinterest.com/v5/boards"
