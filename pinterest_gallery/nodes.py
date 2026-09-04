import io
import json

import numpy as np
import requests
import torch
from PIL import Image


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

        resp = requests.get(image_url, timeout=20)
        resp.raise_for_status()

        image = Image.open(io.BytesIO(resp.content)).convert("RGB")
        array = np.array(image).astype(np.float32) / 255.0
        tensor = torch.from_numpy(array)[None,]
        return (tensor,)


NODE_CLASS_MAPPINGS = {"PinterestGalleryLoader": PinterestGalleryLoader}
NODE_DISPLAY_NAME_MAPPINGS = {"PinterestGalleryLoader": "Pinterest Gallery Loader"}
