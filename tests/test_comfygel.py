import importlib
import sys
import types

import pytest


class _Routes:
    def get(self, _path):
        return lambda handler: handler

    def post(self, _path):
        return lambda handler: handler


class _FakeResponse:
    status_code = 403
    text = "<html>Forbidden</html>"
    headers = {"content-type": "text/html; charset=utf-8"}

    def json(self):
        raise ValueError("Expecting value: line 1 column 1 (char 0)")


def _load_comfygel(monkeypatch):
    server_module = types.SimpleNamespace(
        PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=_Routes()))
    )
    comfy_module = types.SimpleNamespace(
        utils=types.SimpleNamespace(common_upscale=lambda *args, **kwargs: None)
    )
    monkeypatch.setitem(sys.modules, "server", server_module)
    monkeypatch.setitem(sys.modules, "comfy", comfy_module)
    monkeypatch.setitem(sys.modules, "boto3", types.SimpleNamespace(client=lambda *_args, **_kwargs: None))
    sys.modules.pop("comfygel", None)
    return importlib.import_module("comfygel")


def test_gelbooru_random_reports_non_json_api_response(monkeypatch):
    comfygel = _load_comfygel(monkeypatch)
    requests_seen = []

    def fake_get(*_args, **kwargs):
        requests_seen.append(kwargs)
        return _FakeResponse()

    monkeypatch.setattr(comfygel.requests, "get", fake_get)
    monkeypatch.setattr(comfygel.time, "sleep", lambda *_args, **_kwargs: None)
    node = comfygel.GelbooruRandom()

    with pytest.raises(ValueError, match="Gelbooru API returned non-JSON response") as excinfo:
        node.get_value(api_credentials="&api_key=test&user_id=123", add_good_tags=False, remove_bad_tags=False)

    message = str(excinfo.value)
    assert "HTTP 403" in message
    assert "text/html; charset=utf-8" in message
    assert "<html>Forbidden</html>" in message
    assert requests_seen[0]["headers"] == {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
    }
