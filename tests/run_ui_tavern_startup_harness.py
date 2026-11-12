"""Offscreen run_ui.main tavern startup smoke test, with no backend traffic."""
import os
import sys
import traceback
from types import SimpleNamespace
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = "--no-sandbox --disable-gpu"

try:
    import requests
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication, QMessageBox
    import run_ui
    (Path.cwd() / "data" / "local_mode").mkdir(parents=True, exist_ok=True)
    run_ui.__file__ = str(Path.cwd() / "run_ui.py")

    run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, "api_server_process", None)
    run_ui.EchoGraphMainWindow.load_conversation_knowledge_graph = lambda self, conv_id: False

    def fake_get(url, **kwargs):
        if url.endswith("/system/liveness"):
            return SimpleNamespace(ok=True, status_code=200, json=lambda: {"ok": True})
        if url.endswith("/tavern/current_session"):
            return SimpleNamespace(ok=True, status_code=200, json=lambda: {"has_session": False})
        return SimpleNamespace(ok=True, status_code=200, json=lambda: {})

    def fake_post(url, **kwargs):
        return SimpleNamespace(ok=True, status_code=200, json=lambda: {"active": True})

    requests.get = fake_get
    requests.post = fake_post
    QMessageBox.warning = lambda *args: (_ for _ in ()).throw(AssertionError(args[-1]))
    QMessageBox.critical = QMessageBox.warning

    original_add = run_ui.logger.add
    def safe_add(sink, **kwargs):
        if isinstance(sink, str):
            return 0
        return original_add(sink, **kwargs)
    run_ui.logger.add = safe_add

    def enter_tavern():
        try:
            windows = [w for w in QApplication.topLevelWidgets() if isinstance(w, run_ui.EchoGraphMainWindow)]
            assert len(windows) == 1
            window = windows[0]
            window.play_page.tavern_mode_radio.click()
            QApplication.processEvents()
            assert not window.play_page.is_test_mode
            assert window.graph_page.showing_tavern_placeholder
            page = window.graph_page
            assert "正在从角色卡生成图谱" in page.entity_list.item(0).text()
            page._show_tavern_mode_placeholder("tavern_Test_12345678", {
                "graph_nodes": 0, "graph_edges": 0,
                "initialization_status": "failed",
                "initialization_reason": "stub extraction failed",
            })
            assert "stub extraction failed" in page.entity_list.item(0).text()
            page._show_tavern_mode_placeholder("tavern_Test_12345678", {
                "graph_nodes": 0, "graph_edges": 0,
                "initialization_status": "completed",
                "initialization_reason": "角色卡未提取到实体",
            })
            assert "角色卡未提取到实体" in page.entity_list.item(0).text()
            print("run_ui.main tavern startup: OK; pending/failed/empty states visible; no traceback", flush=True)
            os._exit(0)
        except BaseException:
            traceback.print_exc()
            os._exit(1)

    original_create = run_ui.create_app_and_window
    def create_and_schedule(*args, **kwargs):
        app, window = original_create(*args, **kwargs)
        QTimer.singleShot(300, enter_tavern)
        QTimer.singleShot(10000, lambda: os._exit(2))
        return app, window
    run_ui.create_app_and_window = create_and_schedule
    run_ui.main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
