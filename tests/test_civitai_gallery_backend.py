import importlib
import json
import sys
import types

import aiohttp
import pytest


class _Routes:
    def get(self, _path):
        return lambda handler: handler

    def post(self, _path):
        return lambda handler: handler


def _load_civitai_gallery(monkeypatch):
    server_module = types.SimpleNamespace(
        PromptServer=types.SimpleNamespace(instance=types.SimpleNamespace(routes=_Routes()))
    )
    folder_paths_module = types.SimpleNamespace(get_folder_paths=lambda _key: [])
    monkeypatch.setitem(sys.modules, "server", server_module)
    monkeypatch.setitem(sys.modules, "folder_paths", folder_paths_module)
    sys.modules.pop("Civitai_Gallery", None)
    return importlib.import_module("Civitai_Gallery")


def test_build_image_params_uses_base_model_without_username_or_tag_id(monkeypatch):
    module = _load_civitai_gallery(monkeypatch)

    params = module._build_image_params(
        nsfw="None",
        sort="Newest",
        period="Day",
        base_model="Krea 2",
        cursor=None,
        model_id=None,
        model_version_id=None,
    )

    assert params["baseModels"] == "Krea 2"
    assert "type" not in params
    assert "tags" not in params
    assert "username" not in params


def test_build_model_search_params_uses_keyword_and_base_model(monkeypatch):
    module = _load_civitai_gallery(monkeypatch)

    params = module._build_model_search_params("robot girl", "Flux.2 Klein 9B", "next")

    assert params == {
        "limit": 8,
        "query": "robot girl",
        "baseModels": "Flux.2 Klein 9B",
        "cursor": "next",
    }


def test_civitai_node_outputs_video_url_and_native_video(monkeypatch):
    module = _load_civitai_gallery(monkeypatch)
    fake_video = object()
    monkeypatch.setattr(module, "_video_from_url", lambda url: fake_video)
    node = module.CivitaiGalleryNode()
    selection_data = json.dumps(
        {
            "item": {
                "url": "https://image.civitai.com/example.mp4",
                "type": "video",
                "meta": {"prompt": "positive", "negativePrompt": "negative"},
            },
            "download_image": False,
            "download_video": True,
        }
    )

    result = node.get_selected_data(unique_id="1", selection_data=selection_data)

    assert module.CivitaiGalleryNode.RETURN_TYPES == ("STRING", "STRING", "IMAGE", "STRING", "STRING", "VIDEO")
    assert module.CivitaiGalleryNode.RETURN_NAMES == ("positive_prompt", "negative_prompt", "image", "info", "video_url", "video")
    assert result[0] == "positive"
    assert result[1] == "negative"
    assert result[4] == "https://image.civitai.com/example.mp4"
    assert result[5] is fake_video


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.mark.asyncio
async def test_keyword_route_returns_json_response(monkeypatch):
    module = _load_civitai_gallery(monkeypatch)
    monkeypatch.setattr(module, "load_config", lambda: {})
    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda timeout: _FakeSession())

    async def fake_fetch(*_args):
        return {"items": [{"id": 1, "name": "Moody"}], "metadata": {}}

    monkeypatch.setattr(module, "_fetch_keyword_images", fake_fetch)
    request = types.SimpleNamespace(
        query={
            "query": "Moody",
            "nsfw": "None",
            "sort": "Most Reactions",
            "period": "Day",
            "domain": "civitai.red",
        }
    )

    response = await module.get_civitai_images(request)

    assert response is not None
    assert response.status == 200
    assert json.loads(response.text)["items"][0]["name"] == "Moody"


@pytest.mark.asyncio
async def test_keyword_route_uses_retry_after_for_503(monkeypatch):
    module = _load_civitai_gallery(monkeypatch)
    sleeps = []
    monkeypatch.setattr(module, "load_config", lambda: {})
    monkeypatch.setattr(module.aiohttp, "ClientSession", lambda timeout: _FakeSession())

    async def fake_sleep(delay):
        sleeps.append(delay)

    monkeypatch.setattr(module.asyncio, "sleep", fake_sleep)

    async def overloaded(*_args):
        raise aiohttp.ClientResponseError(
            request_info=types.SimpleNamespace(real_url="https://civitai.red/api/v1/models"),
            history=(),
            status=503,
            message="Service Unavailable",
            headers={"Retry-After": "2"},
        )

    monkeypatch.setattr(module, "_fetch_keyword_images", overloaded)
    request = types.SimpleNamespace(
        query={
            "query": "Moody",
            "nsfw": "None",
            "sort": "Most Reactions",
            "period": "Day",
            "domain": "civitai.red",
        }
    )

    response = await module.get_civitai_images(request)

    assert sleeps == [2.0, 2.0]
    assert response.status == 503
    assert "temporarily overloaded" in json.loads(response.text)["error"]
