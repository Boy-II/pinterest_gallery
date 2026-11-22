import unittest
from collections import OrderedDict
from unittest.mock import Mock, patch

import requests
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pinterest_gallery import account, pinterest_api, server

PIN = "90071992547409931234"
BOARD = "90071992547409939756"
SAVED_PIN = "90071992547409932221"
TOKEN = "synthetic-pinterest-token"
IMAGE_URLS = {
    "orig": {"url": "https://i.pinimg.com/originals/aa/bb/img.jpg"},
    "236x": {"url": "https://i.pinimg.com/236x/aa/bb/img.jpg"},
}
SAVE = "/pinterest_gallery/pins/save"


def search_items(*records):
    return pinterest_api.parse_search_response(
        {
            "resource_response": {
                "data": {
                    "results": [{"images": IMAGE_URLS, **record} for record in records],
                }
            }
        }
    )


def response(status, body=None):
    result = Mock(status_code=status)
    result.json.return_value = body
    return result


class PinIdentityTests(unittest.TestCase):
    def test_opaque_and_conflicting_ids_are_not_write_targets(self):
        items, _ = search_items(
            {"id": PIN, "type": "pin"},
            {
                "id": "opaque-hash",
                "url": f"https://www.pinterest.com.example/pin/{PIN}/",
            },
            {
                "id": "opaque-hash",
                "pin_id": PIN,
                "url": f"https://www.pinterest.com/pin/{SAVED_PIN}/",
            },
            {
                "id": "opaque-hash",
                "url": f"https://www.pinterest.com@other.example/pin/{PIN}/",
            },
            {"id": "opaque-hash", "url": IMAGE_URLS["orig"]["url"]},
        )
        for item in items:
            self.assertIsNone(item["pin_id"])
            self.assertIsNone(item["source_url"])
            self.assertEqual(item["source_image_url"], IMAGE_URLS["orig"]["url"])
        self.assertEqual(items[0]["id"], PIN)

    def test_official_and_canonical_id_keep_full_string_precision(self):
        items, _ = search_items(
            {"id": "opaque-hash", "pin_id": PIN},
            {
                "id": "opaque-hash",
                "canonical_url": f"https://www.pinterest.com/pin/{PIN}/?utm_source=test",
            },
            {"id": "opaque-hash", "pin_url": f"/pin/{PIN}/"},
        )
        official, _ = pinterest_api.parse_board_pins_response(
            {"items": [{"id": PIN, "images": IMAGE_URLS}]}
        )
        self.assertTrue(
            all(
                item["pin_id"] == PIN and type(item["pin_id"]) is str
                for item in items + official
            )
        )
        self.assertTrue(
            all(
                item["source_url"] == f"https://www.pinterest.com/pin/{PIN}/"
                for item in items + official
            )
        )


class SavePinRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Mock(available=False)
        self.store.read.return_value = None
        self.session = Mock(headers={})
        official = pinterest_api.PinterestOfficialClient(
            token=TOKEN, session=self.session, environment="production"
        )
        self.install = patch.multiple(
            server,
            _official_client=official,
            _official_client_error=None,
            _account=account.PinterestAccount(self.store),
            _verified_pins=OrderedDict(),
        )
        self.install.start()
        self.addCleanup(self.install.stop)
        routes = web.RouteTableDef()
        server.setup_routes(routes)
        app = web.Application()
        app.add_routes(routes)
        self.client = TestClient(TestServer(app))
        self.addAsyncCleanup(self.client.close)
        await self.client.start_server()
        self.origin = str(self.client.make_url("/")).rstrip("/")

    async def install_known_pin(self):
        results = search_items(
            {
                "id": "opaque-hash",
                "canonical_url": f"https://www.pinterest.com/pin/{PIN}/",
            }
        )
        with patch.object(server._client, "search", return_value=results):
            result = await self.client.post(
                "/pinterest_gallery/search", json={"query": "reference"}
            )
        self.assertEqual(result.status, 200)
        self.assertEqual((await result.json())["items"][0]["pin_id"], PIN)

    async def post(self, **changes):
        return await self.client.post(
            SAVE,
            headers={"Origin": self.origin},
            json={"pin_id": PIN, "board_id": BOARD, "confirm": True, **changes},
        )

    async def test_only_same_origin_confirmed_verified_string_ids_can_write(self):
        result = await self.post()
        self.assertEqual(result.status, 422)
        self.assertEqual((await result.json())["code"], "pin_unverified")
        await self.install_known_pin()
        for body, code in (
            ({"pin_id": int(PIN)}, "pin_unverified"),
            ({"pin_id": "opaque-hash"}, "pin_unverified"),
            ({"board_id": "foreign/board"}, "board_invalid"),
            ({"confirm": 1}, "confirmation_required"),
        ):
            result = await self.post(**body)
            self.assertEqual((await result.json())["code"], code)
        result = await self.client.post(
            SAVE,
            headers={"Origin": "https://other.example"},
            json={
                "pin_id": PIN,
                "board_id": BOARD,
                "confirm": True,
            },
        )
        self.assertEqual(result.status, 403)
        self.session.request.assert_not_called()

    async def test_expired_pin_requires_a_fresh_gallery_result(self):
        with patch.object(server, "_pin_lifetime", -1):
            await self.install_known_pin()
        result = await self.post()
        self.assertEqual(result.status, 422)
        self.assertEqual((await result.json())["code"], "pin_unverified")
        self.session.request.assert_not_called()

    async def test_save_uses_official_pin_endpoint_and_exact_board_body(self):
        await self.install_known_pin()
        self.session.request.side_effect = [
            response(200, {"id": BOARD, "privacy": "PUBLIC"}),
            response(201, {"id": SAVED_PIN, "board_id": BOARD, "images": IMAGE_URLS}),
        ]
        result = await self.post()
        payload = await result.json()
        self.assertEqual(result.status, 200)
        self.assertEqual(payload["board_id"], BOARD)
        self.assertEqual(payload["pin_id"], SAVED_PIN)
        self.assertEqual(payload["item"]["pin_id"], SAVED_PIN)
        get, save = self.session.request.call_args_list
        self.assertEqual(
            get.args, ("GET", f"https://api.pinterest.com/v5/boards/{BOARD}")
        )
        self.assertEqual(
            save.args, ("POST", f"https://api.pinterest.com/v5/pins/{PIN}/save")
        )
        self.assertEqual(save.kwargs["json"], {"board_id": BOARD})
        self.assertIsNone(save.kwargs["params"])
        self.assertIs(save.kwargs["allow_redirects"], False)

    async def test_inaccessible_protected_or_ad_only_boards_never_write(self):
        await self.install_known_pin()
        for invalid_board in (
            response(404),
            response(200, {"id": BOARD, "privacy": "SECRET"}),
            response(200, {"id": BOARD, "privacy": "PROTECTED"}),
            response(200, {"id": BOARD, "privacy": "PUBLIC", "is_ads_only": True}),
            response(200, {"id": PIN, "privacy": "PUBLIC"}),
        ):
            with self.subTest():
                self.session.request.reset_mock()
                self.session.request.return_value = invalid_board
                result = await self.post()
                self.assertEqual(result.status, 403)
                self.assertEqual((await result.json())["code"], "board_unavailable")
                self.session.request.assert_called_once()
                self.assertEqual(self.session.request.call_args.args[0], "GET")

    async def test_read_only_oauth_never_attempts_network_write(self):
        self.store.read.return_value = {
            "token": TOKEN,
            "mode": "production",
            "method": "oauth",
        }
        await self.install_known_pin()
        result = await self.post()
        self.assertEqual(result.status, 403)
        self.assertEqual((await result.json())["code"], "write_scope_required")
        self.session.request.assert_not_called()

    async def test_upstream_failure_does_not_expose_body_or_retry(self):
        await self.install_known_pin()
        board = response(200, {"id": BOARD, "privacy": "PUBLIC"})
        for upstream, status, code in (
            (response(403, {"sensitive": TOKEN}), 403, "write_forbidden"),
            (response(404, {"sensitive": TOKEN}), 404, "pin_not_found"),
            (requests.Timeout(TOKEN), 504, "save_unconfirmed"),
        ):
            self.session.request.reset_mock()
            self.session.request.side_effect = [board, upstream]
            result = await self.post()
            self.assertEqual(result.status, status)
            self.assertEqual((await result.json())["code"], code)
            self.assertNotIn(TOKEN, await result.text())
            self.assertEqual(self.session.request.call_count, 2)
