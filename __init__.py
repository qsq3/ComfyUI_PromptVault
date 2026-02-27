from .nodes import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS  # noqa: F401

# ComfyUI will serve files from this directory under /extensions/<folder_name>/
WEB_DIRECTORY = "./web/comfyui"

def _try_register_routes():
    # Allow importing this package outside ComfyUI (e.g. tooling) without crashing.
    try:
        import server  # type: ignore  # noqa: F401
    except Exception:
        return

    try:
        from .promptvault.api import setup_routes

        setup_routes()
    except Exception:
        return


_try_register_routes()

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "WEB_DIRECTORY"]
