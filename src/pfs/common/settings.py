"""File-based GUI settings.

Never touches the Windows registry.  By default the settings live in the
project directory (``pfs.ini`` next to ``pyproject.toml``); if the project is
not writable it falls back to the per-user config directory.  ``PFS_CONFIG``
overrides the location entirely.
"""

from __future__ import annotations

import os
from pathlib import Path


def _project_root() -> Path | None:
    """Walk up from this file to the directory containing ``pyproject.toml``."""
    for parent in Path(__file__).resolve().parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    return None


def _user_config_path() -> Path:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "pfs" / "settings.ini"


def config_path() -> Path:
    """Location of the INI file used for GUI settings."""
    override = os.environ.get("PFS_CONFIG")
    if override:
        return Path(override).expanduser()

    root = _project_root()
    if root is not None and os.access(root, os.W_OK):
        return root / "pfs.ini"
    return _user_config_path()


def load_settings():
    """Return a ``QSettings`` backed by the INI file (imports Qt lazily)."""
    from PySide6.QtCore import QSettings

    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(path), QSettings.IniFormat)
