"""Run asyncio on a background thread and marshal UI updates onto the Qt thread.

qasync is intentionally avoided: its Qt timer integration is unreliable across
PySide6 versions, which makes scheduled coroutines silently never run.  Instead
the Qt event loop owns the main thread and a dedicated thread runs asyncio.
Widgets must only be touched from the Qt thread, so async code posts closures
through :class:`GuiBridge`.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any, Callable, Coroutine

from PySide6.QtCore import QObject, Signal


class AsyncRunner(QObject):
    """Owns a background event loop; submit coroutines and cancel via the future."""

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="pfs-asyncio", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]):
        """Schedule ``coro`` on the background loop.

        The returned ``concurrent.futures.Future`` can be cancelled from the Qt
        thread; cancellation propagates to the underlying asyncio task.
        """
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def stop(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)


class GuiBridge(QObject):
    """Emit a callable from any thread; it runs on the object's (Qt) thread."""

    _invoke = Signal(object)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._invoke.connect(self._run)

    def _run(self, fn: Callable[[], Any]) -> None:
        fn()

    def post(self, fn: Callable[[], Any]) -> None:
        self._invoke.emit(fn)
