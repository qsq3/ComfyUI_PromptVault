import os


def get_data_dir():
    # Prefer ComfyUI user directory to avoid overwriting on plugin updates.
    try:
        import folder_paths  # type: ignore

        base = folder_paths.get_user_directory()
    except Exception:
        base = os.path.dirname(os.path.dirname(__file__))

    data_dir = os.path.join(base, "promptvault")
    os.makedirs(data_dir, exist_ok=True)
    return data_dir


def get_db_path():
    return os.path.join(get_data_dir(), "promptvault.db")

