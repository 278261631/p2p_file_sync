"""Console + rotating file logging shared by the CLI, GUI and signal server.

File logging is opt-in via ``PFS_LOG_DIR``.  Rotation is time based by default
(daily) and switches to size based when ``PFS_LOG_MAX_BYTES`` is set.  The
handlers installed here are tagged, so calling :func:`setup_logging` again
replaces them instead of duplicating output.

Environment variables::

    PFS_LOG_DIR           directory for log files (unset => console only)
    PFS_LOG_LEVEL         DEBUG / INFO / WARNING / ERROR (default INFO)
    PFS_LOG_BACKUP_COUNT  rotated files to keep (default 7)
    PFS_LOG_WHEN          TimedRotatingFileHandler 'when' (default midnight)
    PFS_LOG_MAX_BYTES     if > 0, rotate by size instead of time
    PFS_LOG_UTC           1 to use UTC timestamps for time-based rotation
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path

_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_MARKER = "_pfs_handler"
# uvicorn installs its own loggers with propagate disabled; attach the file
# handler to them directly so access/error lines are captured too.
_EXTRA_LOGGERS = ("uvicorn", "uvicorn.error", "uvicorn.access")


def _truthy(value: str | None) -> bool:
    return bool(value) and value.strip().lower() in ("1", "true", "yes", "on")


def _resolve_level(level: int | str | None) -> int:
    if isinstance(level, int):
        return level
    text = str(level or os.environ.get("PFS_LOG_LEVEL", "INFO")).upper()
    return getattr(logging, text, logging.INFO)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _targets() -> list[logging.Logger]:
    return [logging.getLogger()] + [logging.getLogger(name) for name in _EXTRA_LOGGERS]


def _remove_marked(loggers: list[logging.Logger]) -> None:
    seen: set[int] = set()
    for logger in loggers:
        for handler in [h for h in logger.handlers if getattr(h, _MARKER, False)]:
            logger.removeHandler(handler)
            if id(handler) not in seen:
                seen.add(id(handler))
                handler.close()


def setup_logging(
    name: str = "pfs",
    *,
    level: int | str | None = None,
    log_dir: str | os.PathLike | None = None,
    console: bool = True,
) -> str | None:
    """Configure logging; return the log file path when file logging is enabled."""
    loggers = _targets()
    _remove_marked(loggers)

    root = loggers[0]
    root.setLevel(_resolve_level(level))
    formatter = logging.Formatter(_FORMAT)

    if console:
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        setattr(stream, _MARKER, True)
        root.addHandler(stream)

    directory = log_dir if log_dir is not None else os.environ.get("PFS_LOG_DIR")
    if not directory:
        return None

    path = Path(directory).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    log_path = path / f"{name}.log"

    backup_count = _env_int("PFS_LOG_BACKUP_COUNT", 7)
    max_bytes = _env_int("PFS_LOG_MAX_BYTES", 0)
    if max_bytes > 0:
        file_handler: logging.Handler = RotatingFileHandler(
            log_path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
        )
    else:
        file_handler = TimedRotatingFileHandler(
            log_path,
            when=os.environ.get("PFS_LOG_WHEN", "midnight"),
            backupCount=backup_count,
            encoding="utf-8",
            utc=_truthy(os.environ.get("PFS_LOG_UTC")),
        )
    file_handler.setFormatter(formatter)
    setattr(file_handler, _MARKER, True)
    for logger in loggers:
        logger.addHandler(file_handler)

    return str(log_path)
