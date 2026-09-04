import io
import json

import pytest
from PIL import Image

from pinterest_gallery.nodes import PinterestGalleryLoader


def _fake_png_bytes(width=4, height=4, color=(255, 0, 0)):
    img = Image.new("RGB", (width, height), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class _FakeResponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_load_downloads_and_converts_selected_image(monkeypatch):
    png_bytes = _fake_png_bytes()
    monkeypatch.setattr(
        "pinterest_gallery.nodes.requests.get",
        lambda url, timeout=20: _FakeResponse(png_bytes),
    )
    node = PinterestGalleryLoader()
    selected_pin = json.dumps(
        {"id": "1", "image_url": "https://i.pinimg.com/originals/x.jpg"}
    )

    (tensor,) = node.load(selected_pin)

    assert tensor.shape == (1, 4, 4, 3)
    assert str(tensor.dtype) == "torch.float32"
    assert tensor.max().item() <= 1.0
    assert tensor.min().item() >= 0.0


def test_load_raises_on_empty_selection():
    node = PinterestGalleryLoader()
    with pytest.raises(ValueError):
        node.load("")


def test_load_raises_on_invalid_json():
    node = PinterestGalleryLoader()
    with pytest.raises(ValueError):
        node.load("not json")


def test_input_types_declares_selected_pin_string():
    input_types = PinterestGalleryLoader.INPUT_TYPES()
    assert input_types["required"]["selected_pin"][0] == "STRING"
