import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.parse import parse_qs, urlsplit

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from pinterest_gallery import account as pinterest_account
from pinterest_gallery import server as pinterest_server
from pinterest_gallery.pinterest_api import PinterestAuthError, PinterestOfficialClient

ACCOUNT = pinterest_account.ACCOUNT_PATH
CALLBACK = pinterest_account.CALLBACK_PATH
TOKEN = "synthetic-test-access-token"
APP_SECRET = "synthetic-test-app-secret"


class AccountRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store = Mock(available=True)
        self.store.read.return_value = None
        self.manager = pinterest_account.PinterestAccount(self.store)
        self.environment = PinterestOfficialClient(token="", environment="sandbox")
        patcher = patch.multiple(
            pinterest_server,
            _account=self.manager,
            _official_client=self.environment,
            _official_client_error=None,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        routes = web.RouteTableDef()
        pinterest_server.setup_routes(routes)
        app = web.Application()
        app.add_routes(routes)
        self.client = TestClient(TestServer(app))
        self.addAsyncCleanup(self.client.close)
        await self.client.start_server()
        self.origin = str(self.client.make_url("/")).rstrip("/")
        self.headers = {"Origin": self.origin}

    async def test_token_requires_local_same_origin_json(self):
        body = {"token": TOKEN, "mode": "production", "remember": True}
        path = ACCOUNT + "/token"
        with patch.object(pinterest_account, "_verify_token") as verify:
            response = await self.client.post(path, json=body)
            self.assertEqual(response.status, 403)
            response = await self.client.post(
                path, json=body, headers={"Origin": "https://elsewhere.example"}
            )
            self.assertEqual(response.status, 403)
            response = await self.client.post(
                path,
                json=body,
                headers={
                    "Origin": "http://not-local.example",
                    "Host": "not-local.example",
                },
            )
            self.assertEqual(response.status, 403)
            response = await self.client.post(path, data=body, headers=self.headers)
            self.assertEqual(response.status, 415)
        verify.assert_not_called()
        self.store.write.assert_not_called()

    async def test_connected_token_is_validated_before_saving_and_never_returned(self):
        with patch.object(pinterest_account, "_verify_token") as verify:
            response = await self.client.post(
                ACCOUNT + "/token",
                headers=self.headers,
                json={"token": TOKEN, "mode": "production", "remember": True},
            )
        verify.assert_called_once_with(TOKEN, "production")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        status = await response.json()
        self.assertTrue(status["connected"])
        self.assertEqual(status["mode"], "production")
        self.assertTrue(status["persistent"])
        self.assertNotIn(TOKEN, await response.text())
        self.store.write.assert_called_once_with(
            {
                "token": TOKEN,
                "mode": "production",
                "method": "token",
                "expires_at": None,
            }
        )

        managed = Mock()
        managed.list_boards.return_value = ([{"id": "board", "name": "Ideas"}], "next")
        with patch.object(
            pinterest_server, "PinterestOfficialClient", return_value=managed
        ) as factory:
            response = await self.client.get("/pinterest_gallery/boards")
            self.assertEqual(
                await response.json(),
                {"items": [{"id": "board", "name": "Ideas"}], "bookmark": "next"},
            )
            self.assertEqual(
                (
                    await self.client.get(
                        "/pinterest_gallery/boards",
                        headers={"Origin": "https://elsewhere.example"},
                    )
                ).status,
                403,
            )
        factory.assert_called_once_with(token=TOKEN, environment="production")

    async def test_failed_token_response_redacts_upstream_message(self):
        with patch.object(
            pinterest_account, "_verify_token", side_effect=PinterestAuthError(TOKEN)
        ):
            response = await self.client.post(
                ACCOUNT + "/token",
                headers=self.headers,
                json={"token": TOKEN, "mode": "production", "remember": True},
            )
        self.assertEqual(response.status, 401)
        self.assertNotIn(TOKEN, await response.text())
        self.store.write.assert_not_called()

    async def begin_oauth(self, remember=False, write_access=False):
        response = await self.client.post(
            ACCOUNT + "/oauth/start",
            headers=self.headers,
            json={
                "client_id": "123456",
                "client_secret": APP_SECRET,
                "mode": "sandbox",
                "remember": remember,
                **({"write_access": True} if write_access else {}),
            },
        )
        self.assertEqual(response.status, 200)
        self.assertNotIn(APP_SECRET, await response.text())
        data = await response.json()
        location = urlsplit(data["authorize_url"])
        self.assertEqual(
            (location.scheme, location.netloc, location.path),
            ("https", "www.pinterest.com", "/oauth/"),
        )
        params = parse_qs(location.query)
        self.assertEqual(
            params["scope"],
            [
                "boards:read,boards:write,pins:read,pins:write"
                if write_access
                else "boards:read,pins:read"
            ],
        )
        self.assertEqual(params["response_type"], ["code"])
        self.assertEqual(params["redirect_uri"], [self.origin + CALLBACK])
        cookie = response.cookies[pinterest_account.OAUTH_COOKIE]
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        return params["state"][0], {pinterest_account.OAUTH_COOKIE: cookie.value}

    async def test_oauth_rejects_missing_browser_cookie_and_replay(self):
        state, cookie = await self.begin_oauth(remember=True)
        response = await self.client.get(ACCOUNT + "/status")
        self.assertTrue((await response.json())["oauth_pending"])
        token_response = Mock(status_code=200)
        token_response.json.return_value = {"access_token": TOKEN, "expires_in": 3600}
        with patch.object(
            pinterest_account.requests, "post", return_value=token_response
        ) as exchange:
            response = await self.client.get(
                CALLBACK,
                params={"state": state, "code": "oauth-code"},
                cookies={
                    pinterest_account.OAUTH_COOKIE: "different-browser",
                },
            )
            self.assertEqual(response.status, 400)
            exchange.assert_not_called()
            response = await self.client.get(
                CALLBACK, params={"state": state, "code": "oauth-code"}, cookies=cookie
            )
            self.assertEqual(response.status, 200)
            self.assertNotIn("Location", response.headers)
            self.assertNotIn(TOKEN, await response.text())
            exchange.assert_called_once_with(
                "https://api-sandbox.pinterest.com/v5/oauth/token",
                auth=("123456", APP_SECRET),
                data={
                    "grant_type": "authorization_code",
                    "code": "oauth-code",
                    "redirect_uri": self.origin + CALLBACK,
                },
                timeout=12,
                allow_redirects=False,
            )
            response = await self.client.get(
                CALLBACK, params={"state": state, "code": "oauth-code"}, cookies=cookie
            )
            self.assertEqual(response.status, 400)
        status = await (await self.client.get(ACCOUNT + "/status")).json()
        self.assertEqual(status["method"], "oauth")
        self.assertFalse(status["oauth_pending"])
        self.assertIsInstance(status["expires_at"], int)
        self.assertNotIn(APP_SECRET, str(self.store.write.call_args))

    async def test_oauth_state_expires_and_logout_suppresses_environment(self):
        self.environment.token = TOKEN
        state, cookie = await self.begin_oauth()
        with patch.object(pinterest_account, "OAUTH_SECONDS", 0):
            expired_state, expired_cookie = await self.begin_oauth()
        with patch.object(pinterest_account.requests, "post") as exchange:
            response = await self.client.get(
                CALLBACK, params={"state": state, "code": "old"}, cookies=cookie
            )
            self.assertEqual(response.status, 400)
            response = await self.client.get(
                CALLBACK,
                params={"state": expired_state, "code": "old"},
                cookies=expired_cookie,
            )
            self.assertEqual(response.status, 400)
        exchange.assert_not_called()
        status = await (await self.client.get(ACCOUNT + "/status")).json()
        self.assertEqual(status["method"], "environment")
        response = await self.client.post(
            ACCOUNT + "/logout", headers=self.headers, json={}
        )
        status = await response.json()
        self.assertFalse(status["connected"])
        self.assertTrue(status["environment_suppressed"])
        self.assertEqual(
            (await self.client.get("/pinterest_gallery/boards")).status, 401
        )
        self.store.clear.assert_called_once()

    async def test_expired_oauth_credential_requires_reconnection(self):
        self.store.read.return_value = {
            "token": TOKEN,
            "mode": "sandbox",
            "method": "oauth",
            "expires_at": 1,
        }
        status = await (await self.client.get(ACCOUNT + "/status")).json()
        self.assertEqual(status["state"], "expired")
        self.assertFalse(status["connected"])
        self.assertEqual(
            (await self.client.get("/pinterest_gallery/boards")).status, 401
        )

    async def test_cancelled_reauthorization_keeps_existing_connection(self):
        self.store.read.return_value = {
            "token": TOKEN,
            "mode": "production",
            "method": "oauth",
            "expires_at": None,
        }
        state, cookie = await self.begin_oauth()
        with patch.object(pinterest_account.requests, "post") as exchange:
            response = await self.client.get(
                CALLBACK,
                params={"state": state, "error": "access_denied"},
                cookies=cookie,
            )
            self.assertEqual(response.status, 400)
        exchange.assert_not_called()
        status = await (await self.client.get(ACCOUNT + "/status")).json()
        self.assertTrue(status["connected"])
        self.assertEqual(status["mode"], "production")
        self.assertFalse(status["oauth_pending"])
        self.assertIsInstance(status["oauth_error"], str)

    async def test_save_oauth_requires_opt_in_and_every_granted_scope(self):
        state, cookie = await self.begin_oauth()
        all_scopes = "boards:read boards:write pins:read pins:write"
        token = Mock(status_code=200)
        token.json.return_value = {
            "access_token": TOKEN,
            "expires_in": 3600,
            "scope": all_scopes,
        }
        with patch.object(pinterest_account.requests, "post", return_value=token):
            response = await self.client.get(
                CALLBACK, params={"state": state, "code": "read"}, cookies=cookie
            )
        self.assertEqual(response.status, 200)
        status = await (await self.client.get(ACCOUNT + "/status")).json()
        self.assertEqual(status["pin_write"], "read_only")

        state, cookie = await self.begin_oauth(write_access=True)
        token.json.return_value["scope"] = "boards:read boards:write pins:read"
        with patch.object(pinterest_account.requests, "post", return_value=token):
            response = await self.client.get(
                CALLBACK, params={"state": state, "code": "partial"}, cookies=cookie
            )
        self.assertEqual(response.status, 403)
        status = await (await self.client.get(ACCOUNT + "/status")).json()
        self.assertEqual(status["pin_write"], "read_only")
        self.assertTrue(status["connected"])

        state, cookie = await self.begin_oauth(write_access=True, remember=True)
        token.json.return_value["scope"] = all_scopes
        with patch.object(pinterest_account.requests, "post", return_value=token):
            response = await self.client.get(
                CALLBACK, params={"state": state, "code": "write"}, cookies=cookie
            )
        self.assertEqual(response.status, 200)
        status = await (await self.client.get(ACCOUNT + "/status")).json()
        self.assertEqual(status["pin_write"], "granted")
        self.assertIs(self.store.write.call_args.args[0]["write_authorized"], True)


@unittest.skipUnless(os.name == "nt", "Windows DPAPI applies to the local Windows user")
class DPAPIStoreTests(unittest.TestCase):
    def test_local_store_keeps_an_existing_legacy_connection(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            current = base / "ComfyUI" / "PinterestGallery" / "account.dpapi"
            legacy = base / "Soda" / "PinterestGallery" / "account.dpapi"
            with patch.dict(os.environ, {"LOCALAPPDATA": directory}):
                self.assertEqual(pinterest_account.DPAPIStore.local().path, current)
                legacy.parent.mkdir(parents=True)
                legacy.touch()
                self.assertEqual(pinterest_account.DPAPIStore.local().path, legacy)
                current.parent.mkdir(parents=True)
                current.touch()
                self.assertEqual(pinterest_account.DPAPIStore.local().path, current)

    def test_credential_is_encrypted_at_rest_and_can_be_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "account.dpapi"
            store = pinterest_account.DPAPIStore(path)
            record = {
                "token": TOKEN,
                "mode": "production",
                "method": "token",
                "expires_at": None,
            }
            store.write(record)
            self.assertEqual(store.read(), record)
            self.assertNotIn(TOKEN.encode(), path.read_bytes())
            self.assertEqual(list(path.parent.iterdir()), [path])
            store.clear()
            self.assertIsNone(store.read())
