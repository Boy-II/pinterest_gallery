import io
import json
from urllib.parse import urlparse

import numpy as np
import requests
import torch
from PIL import Image, ImageOps, UnidentifiedImageError


class PinterestGalleryLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "selected_pin": ("STRING", {"default": "", "multiline": False}),
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "load"
    CATEGORY = "image/pinterest"

    def load(self, selected_pin):
        if not selected_pin:
            raise ValueError(
                "No Pinterest image selected. Search and click a thumbnail "
                "on the node before running the workflow."
            )
        try:
            pin = json.loads(selected_pin)
            image_url = pin["image_url"]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ValueError(f"Invalid selected_pin value: {selected_pin!r}") from exc

        host = (urlparse(image_url).hostname or "")
        if not (host == "pinimg.com" or host.endswith(".pinimg.com")):
            raise ValueError(f"Refusing to download non-Pinterest URL: {image_url!r}")

        try:
            resp = requests.get(image_url, timeout=20)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Failed to download Pinterest image from {image_url}: {exc}"
            ) from exc

        try:
            image = Image.open(io.BytesIO(resp.content)).convert("RGB")
        except UnidentifiedImageError as exc:
            raise RuntimeError(
                f"Downloaded data from {image_url} is not a valid image"
            ) from exc
        image = ImageOps.exif_transpose(image)
        array = np.array(image).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array)[None,]
        return (tensor,)


NODE_CLASS_MAPPINGS = {"PinterestGalleryLoader": PinterestGalleryLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"PinterestGalleryLoader": "Pinterest Gallery Loader"}
