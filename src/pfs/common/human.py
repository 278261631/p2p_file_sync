"""Human-friendly formatting helpers shared by CLI and GUI."""

from __future__ import annotations

import asyncio


def exc_text(exc: BaseException) -> str:
    """Readable message for an exception, even when ``str(exc)`` is empty.

    Network failures such as a bare ``ConnectionResetError`` or
    ``asyncio.TimeoutError`` stringify to an empty string, which would
    otherwise surface as a blank error dialog.
    """
    text = str(exc).strip()
    if text:
        return text
    if isinstance(exc, (asyncio.TimeoutError, TimeoutError)):
        return "连接超时"
    return f"{type(exc).__name__}（无详细信息）"


def fmt_size(num: float) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(value) < 1024 or unit == "GiB":
            return f"{int(value)}B" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}GiB"


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m{seconds % 60:02d}s"
    return f"{seconds // 3600}h{(seconds % 3600) // 60:02d}m"
