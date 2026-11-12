"""Offscreen config screenshots and external-cwd main smoke check."""

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import traceback

ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(tempfile.gettempdir()) / "echograph-unit-shots"


def child(mode, name, env_path, scratch):
    try:
        import requests
        from PySide6.QtCore import QTimer
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtWidgets import QAbstractSpinBox, QMessageBox, QScrollArea, QStyle, QStyleOptionComboBox
        import run_ui
        from src.ui import theme

        def no_network(*_args, **_kwargs):
            raise requests.ConnectionError("offline UI harness")

        requests.get = requests.post = requests.request = no_network
        run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, "api_server_process", None)
        run_ui.EchoGraphMainWindow.load_conversation_knowledge_graph = lambda self, _id: False
        run_ui.GraphPage.refresh_graph = lambda self: None
        original_conversations = run_ui.ConversationManager.__init__
        run_ui.ConversationManager.__init__ = lambda self, _path: original_conversations(self, scratch)
        QMessageBox.critical = lambda *_args: (_ for _ in ()).throw(AssertionError(_args[-1]))

        if mode == "main":
            original_create = run_ui.create_app_and_window

            def create_for_main(*_args, **_kwargs):
                app, window = original_create(env_path=env_path, process_theme=None)

                def done():
                    print(f"main cwd={Path.cwd()} theme={theme.current_name()} visible={window.isVisible()}", flush=True)
                    os._exit(0)

                QTimer.singleShot(500, done)
                return app, window

            run_ui.create_app_and_window = create_for_main
            run_ui.main()
            raise AssertionError("main returned before timer")

        app, window = run_ui.create_app_and_window(env_path=env_path, process_theme=None)
        window.resize(1280, 900)
        window.tabs.setCurrentWidget(window.config_page)
        app.processEvents()
        page = window.config_page
        scroll = page.findChild(QScrollArea)
        spin_count = len(page.findChildren(QAbstractSpinBox))
        assert spin_count == 0
        for field in page.findChildren(run_ui.ValueUnitInput):
            combo = field.unit_combo
            if combo is None:
                continue
            option = QStyleOptionComboBox()
            option.initFrom(combo)
            edit_rect = combo.style().subControlRect(QStyle.CC_ComboBox, option, QStyle.SC_ComboBoxEditField, combo)
            longest = max(combo.fontMetrics().horizontalAdvance(unit.label) for unit in field.units)
            assert edit_rect.width() >= longest, (combo.currentText(), edit_rect.width(), longest)

        def shot(label):
            app.processEvents()
            output = SHOTS / f"{name}-{label}.png"
            assert window.grab().save(str(output))
            print(f"shot={output} scroll={scroll.verticalScrollBar().value()}", flush=True)

        scroll.verticalScrollBar().setValue(0)
        shot("top")
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum() // 2)
        shot("middle")
        scroll.verticalScrollBar().setValue(scroll.verticalScrollBar().maximum())
        shot("bottom")

        scroll.verticalScrollBar().setValue(0)
        page.model_input.addItems(["model-alpha", "model-beta", "model-gamma"])
        page.model_input.showPopup()
        app.processEvents()
        assert page.model_input.view().isVisible()
        # A popup is a separate top-level surface; compose both Qt grabs at
        # their actual screen positions so the screenshot includes its list.
        base = window.grab().toImage().convertToFormat(QImage.Format_ARGB32)
        popup = page.model_input.view().grab().toImage()
        painter = QPainter(base)
        pos = page.model_input.view().mapToGlobal(page.model_input.view().rect().topLeft()) - window.mapToGlobal(window.rect().topLeft())
        painter.drawImage(pos, popup)
        painter.end()
        output = SHOTS / f"{name}-model-popup.png"
        assert base.save(str(output))
        print(f"shot={output} popup_items={page.model_input.count()}", flush=True)
        page.model_input.hidePopup()

        page.request_timeout_input.number_edit.setText("999")
        app.processEvents()
        assert not page.request_timeout_input.isValid()
        shot("invalid")
        print(f"theme={theme.current_name()} combos={len(window.findChildren(run_ui.QComboBox))} config_spin_boxes={spin_count}", flush=True)
        if name == "sand":
            window.apply_theme("ink")
            app.processEvents()
            assert theme.current_name() == "ink"
            assert "chevron-down-ink.svg" in app.styleSheet()
            shot("switched-ink")
            print("live_switch=sand->ink arrow=chevron-down-ink.svg", flush=True)
        os._exit(0)
    except BaseException:
        traceback.print_exc()
        os._exit(1)


def parent():
    SHOTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="echograph-unit-harness-") as directory:
        scratch = Path(directory)
        other_cwd = scratch / "other-cwd"
        other_cwd.mkdir()
        for name in ("sand", "ink"):
            env_path = scratch / f"{name}.env"
            env_path.write_text(f"UI_THEME={name}\nOPENAI_API_KEY=\nOPENAI_API_BASE_URL=\n", encoding="utf-8")
            environment = os.environ.copy()
            environment.pop("UI_THEME", None)
            environment.update({
                "PYTHONPATH": str(ROOT), "QT_QPA_PLATFORM": "offscreen",
                "QTWEBENGINE_DISABLE_SANDBOX": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu",
            })
            for mode in ("shots", "main"):
                command = [sys.executable, str(Path(__file__).resolve()), "--child", mode, name, str(env_path), str(scratch)]
                result = subprocess.run(command, cwd=other_cwd, env=environment, capture_output=True, text=True, timeout=90)
                print(f"case={mode}/{name} exit={result.returncode}\n{result.stdout}", flush=True)
                if result.returncode:
                    print(result.stderr[-8000:], file=sys.stderr, flush=True)
                    raise RuntimeError(f"{mode}/{name} failed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3], Path(sys.argv[4]), Path(sys.argv[5]))
    else:
        parent()
