"""Offscreen real-window smoke test. Run directly, not through pytest."""

import os
import re
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(tempfile.gettempdir()) / "echograph-theme-shots"


def child(env_path: Path, expected: str, shot: Path, switch: str | None):
    try:
        from dotenv import dotenv_values
        from PySide6.QtGui import QPalette
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication, QMessageBox
        import requests
        import run_ui
        from src.ui import theme

        run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, "api_server_process", None)
        # The window's conversation migration writes user data during startup.
        run_ui.EchoGraphMainWindow.load_conversation_knowledge_graph = lambda self, conv_id: False
        requests.post = lambda *args, **kwargs: None
        requests.get = lambda *args, **kwargs: None
        messages = []
        QMessageBox.information = lambda *args: messages.append(args[-1])
        QMessageBox.critical = lambda *args: (_ for _ in ()).throw(AssertionError(args[-1]))
        QMessageBox.warning = QMessageBox.critical

        app, window = run_ui.create_app_and_window(env_path)
        app.processEvents()
        assert window.config_page.env_path.resolve() == env_path.resolve()
        assert window.config_page.window() is window

        def check(name, screenshot):
            QTest.qWait(250)
            app.processEvents()
            expected_color = theme.PALETTES[name]["BG_BASE"].lower()
            actual_color = app.palette().color(QPalette.Window).name().lower()
            assert theme.current_name() == name, (theme.current_name(), name)
            assert actual_color == expected_color, (actual_color, expected_color)
            assert window.config_page.theme_combo.currentData() == name
            pixmap = window.grab()
            pixel_color = pixmap.toImage().pixelColor(1100, 300).name().lower()
            assert pixel_color == expected_color, (pixel_color, expected_color)
            assert pixmap.save(str(screenshot))
            print(f"{name}: palette={actual_color} pixel={pixel_color} visible={window.isVisible()} size={window.size().width()}x{window.size().height()} screenshot={screenshot}", flush=True)

        check(expected, shot)
        if switch:
            window.config_page.theme_combo.setCurrentIndex(window.config_page.theme_combo.findData(switch))
            window.config_page.save_button.click()
            app.processEvents()
            check(switch, SHOTS / "startup-after-live-switch.png")
            assert dotenv_values(env_path)["UI_THEME"] == switch
            graph_file = window.graph_page.graph_file_path
            if graph_file.exists():
                assert f"--bg-base: {theme.current()['BG_BASE']};" in graph_file.read_text(encoding="utf-8")
            assert messages and "\u91cd\u542f" not in messages[-1], messages
            print(f"save: UI_THEME={switch}, message={messages[-1]}", flush=True)
        os._exit(0)
    except BaseException:
        traceback.print_exc()
        os._exit(1)


def parent():
    from dotenv import set_key

    SHOTS.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="echograph-theme-startup-") as temp_dir:
        temp = Path(temp_dir)
        launch_dir = temp / "other-cwd"
        launch_dir.mkdir()
        original = ROOT / ".env"
        for name in ("sand", "ink", "missing"):
            path = temp / f"{name}.env"
            shutil.copyfile(original, path)
            if name == "missing":
                text = path.read_text(encoding="utf-8")
                text = re.sub(r"(?m)^UI_THEME=.*(?:\n|$)", "", text)
                path.write_text(text, encoding="utf-8")
            else:
                set_key(path, "UI_THEME", name)
            expected = "sand" if name == "missing" else name
            switch = "ink" if name == "sand" else None
            shot = SHOTS / f"startup-{name}.png"
            env = os.environ.copy()
            env.pop("UI_THEME", None)
            env.update({
                "PYTHONPATH": str(ROOT),
                "QT_QPA_PLATFORM": "offscreen",
                "QTWEBENGINE_DISABLE_SANDBOX": "1",
                "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu",
            })
            command = [sys.executable, str(Path(__file__).resolve()), "--child", str(path), expected, str(shot), switch or "-"]
            result = subprocess.run(command, cwd=launch_dir, env=env, capture_output=True, text=True, timeout=90)
            print(f"case={name} cwd={launch_dir} exit={result.returncode}\n{result.stdout}", flush=True)
            if result.returncode:
                print(result.stderr[-6000:], file=sys.stderr)
                raise RuntimeError(f"Startup case {name} failed")
            if switch:
                fresh_shot = SHOTS / "startup-saved-ink.png"
                command = [sys.executable, str(Path(__file__).resolve()), "--child", str(path), "ink", str(fresh_shot), "-"]
                result = subprocess.run(command, cwd=launch_dir, env=env, capture_output=True, text=True, timeout=90)
                print(f"case=fresh-saved cwd={launch_dir} exit={result.returncode}\n{result.stdout}", flush=True)
                if result.returncode:
                    print(result.stderr[-6000:], file=sys.stderr)
                    raise RuntimeError("Fresh saved startup failed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(Path(sys.argv[2]), sys.argv[3], Path(sys.argv[4]), None if sys.argv[5] == "-" else sys.argv[5])
    else:
        parent()
