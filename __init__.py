from .nodes import (
    NODE_CLASS_MAPPINGS as _PINTEREST_NODES,
    NODE_DISPLAY_NAME_MAPPINGS as _PINTEREST_DISPLAY,
)

NODE_CLASS_MAPPINGS = dict(_PINTEREST_NODES)
NODE_DISPLAY_NAME_MAPPINGS = dict(_PINTEREST_DISPLAY)

WEB_DIRECTORY = "web"

try:
    from server import PromptServer  # only present inside a running ComfyUI process
except ImportError:
    PromptServer = None

if PromptServer is not None:
    from .server import setup_routes as _setup_pinterest_routes

    _setup_pinterest_routes(PromptServer.instance.routes)

    # Civitai_Gallery.py and comfygel.py import ComfyUI-only modules (server,
    # folder_paths, comfy) at the top level and register their own routes on
    # import, so they can only be imported inside a running ComfyUI process —
    # importing them unconditionally would break the Pinterest-only test
    # suite, which runs outside ComfyUI.
    from .Civitai_Gallery import (
        NODE_CLASS_MAPPINGS as _CIVITAI_NODES,
        NODE_DISPLAY_NAME_MAPPINGS as _CIVITAI_DISPLAY,
    )

    NODE_CLASS_MAPPINGS.update(_CIVITAI_NODES)
    NODE_DISPLAY_NAME_MAPPINGS.update(_CIVITAI_DISPLAY)

    # comfygel.py doesn't define NODE_CLASS_MAPPINGS itself — upstream builds
    # it by hand in its own __init__.py, so we do the same here.
    from .comfygel import GelbooruID, GelbooruRandom, UrlsToImage

    NODE_CLASS_MAPPINGS.update(
        {
            "Gelbooru (Random)": GelbooruRandom,
            "Gelbooru (ID)": GelbooruID,
            "UrlsToImage": UrlsToImage,
        }
    )

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
