import logging

from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: F401
from .promptvault.constants import APP_NAME, SCHEMA_VERSION

WEB_DIRECTORY = "./web/comfyui"

VERSION = "1.0.0"

logger = logging.getLogger(__name__)

_banner = f" {APP_NAME} Initialization "
logger.info("=" * 40 + _banner + "=" * 40)
logger.info(f"Plugin version: {VERSION}")
logger.info(f"Schema version: {SCHEMA_VERSION}")
logger.info(f"Nodes: {', '.join(NODE_CLASS_MAPPINGS.keys())}")
logger.info(f"Display names: {', '.join(NODE_DISPLAY_NAME_MAPPINGS.values())}")


def _try_register_routes():
    try:
        import server  # type: ignore  # noqa: F401
    except Exception:
        return

    try:
        from .promptvault.api import setup_routes

        setup_routes()
        logger.info("API routes registered successfully")
    except Exception:
        logger.exception("Route registration failed")


_try_register_routes()

logger.info("=" * (80 + len(_banner)))

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
