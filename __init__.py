import logging

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: F401

WEB_DIRECTORY = "./web/comfyui"

_logger = logging.getLogger("PromptVault")

def _try_register_routes():
    try:
        import server  # type: ignore  # noqa: F401
    except Exception:
        return

    try:
        from .promptvault.api import setup_routes

        setup_routes()
    except Exception:
        _logger.exception("PromptVault route registration failed")


_try_register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
