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
        """Let already-submitted work finish, then stop the loop.

        Stopping the loop while a ``service.close()`` (or any other coroutine) is
        still pending tears down the SSL transport mid-write, which surfaces as
        "Task was destroyed but it is pending" / "Fatal error on SSL transport".
        """
        if self._loop.is_running():
            try:
                asyncio.run_coroutine_threadsafe(self._drain(), self._loop).result(timeout=8)
            except Exception:  # noqa: BLE001 - best effort during shutdown
                pass
            self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout=3)

    async def _drain(self, grace: float = 5.0) -> None:
        """Wait for pending tasks to settle, then cancel whatever is left."""
        current = asyncio.current_task()
        loop = asyncio.get_event_loop()
        deadline = loop.time() + grace
        while True:
            pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
            if not pending:
                return
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            await asyncio.wait(pending, timeout=remaining)
        pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)


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
