from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "web"

try:
    # Only present inside a running ComfyUI process; lets this package be
    # imported (e.g. by pytest) without a real ComfyUI install.
    from server import PromptServer

    from .server import setup_routes

    setup_routes(PromptServer.instance.routes)
except ImportError:
    pass

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
