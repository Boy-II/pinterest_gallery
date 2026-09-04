from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "web"

try:
    from server import PromptServer  # only present inside a running ComfyUI process
except ImportError:
    PromptServer = None

if PromptServer is not None:
    from .server import setup_routes

    setup_routes(PromptServer.instance.routes)

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
