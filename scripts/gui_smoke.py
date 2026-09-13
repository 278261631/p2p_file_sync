"""Headless smoke test for the PySide6 UI wiring.

Runs the real Qt event loop offscreen, clicks the buttons, and waits for the
resulting widget state to settle.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

import uvicorn  # noqa: E402
from PySide6.QtCore import Qt, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pfs.gui.async_runner import AsyncRunner  # noqa: E402
from pfs.gui.publish_tab import PublishTab  # noqa: E402
from pfs.gui.receive_tab import ReceiveTab  # noqa: E402
from server.signal_server import app as signal_app  # noqa: E402


async def _start_signal():
    config = uvicorn.Config(signal_app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)
    task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    return server, task, port


async def _stop_signal(server, task):
    server.should_exit = True
    try:
        await asyncio.wait_for(task, 5)
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(0.3)


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    runner = AsyncRunner()

    work = Path(tempfile.mkdtemp(prefix="pfs_gui_"))
    share = work / "share"
    dest = work / "dest"
    (share / "docs").mkdir(parents=True)
    dest.mkdir(parents=True)
    (share / "hello.txt").write_text("hello from gui", encoding="utf-8")
    (share / "docs" / "note.txt").write_text("gui note", encoding="utf-8")

    server, server_task, port = runner.submit(_start_signal()).result(timeout=20)

    publish = PublishTab(runner)
    receive = ReceiveTab(runner)
    publish.root_edit.setText(str(share))
    publish.host_edit.setText("127.0.0.1")
    publish.port_spin.setValue(port)

    state = {"ok": False, "phase": "publish", "ticks": 0}

    def tick() -> None:
        state["ticks"] += 1
        if state["ticks"] > 150:
            print("GUI SMOKE: TIMEOUT at", state["phase"])
            app.quit()
            return
        if state["phase"] == "publish":
            if publish.code_edit.text().startswith("PFS1."):
                receive.invite_edit.setText(publish.code_edit.text())
                receive.dest_edit.setText(str(dest))
                receive.connect_btn.click()
                state["phase"] = "connect"
        elif state["phase"] == "connect":
            if receive.tree.topLevelItemCount() > 0:
                for index in range(receive.tree.topLevelItemCount()):
                    receive.tree.topLevelItem(index).setCheckState(0, Qt.Checked)
                receive.download_btn.click()
                state["phase"] = "download"
        elif state["phase"] == "download":
            hello = dest / "hello.txt"
            note = dest / "docs" / "note.txt"
            if hello.exists() and note.exists():
                state["ok"] = hello.read_text(encoding="utf-8") == "hello from gui"
                app.quit()

    publish.start_btn.click()
    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(200)
    app.exec()
    timer.stop()

    try:
        runner.submit(_stop_signal(server, server_task)).result(timeout=10)
    except Exception:  # noqa: BLE001
        pass
    runner.stop()
    shutil.rmtree(work, ignore_errors=True)

    print("GUI SMOKE:", "PASS" if state["ok"] else "FAIL")
    return 0 if state["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
