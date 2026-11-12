"""Offscreen real-window model UI and external-cwd startup checks.

Run directly with the project Python interpreter. Child processes use os._exit
so the window's close handler cannot affect a user's backend.
"""

import json
import os
import subprocess
import sys
import tempfile
import threading
import traceback
from types import SimpleNamespace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SHOTS = Path(tempfile.gettempdir()) / "echograph-model-shots"


def child(mode, workdir):
    try:
        import requests
        from PySide6.QtCore import QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QMessageBox, QGroupBox
        import run_ui
        from src.ui import theme

        workdir = Path(workdir)
        real_get = requests.get
        original_memory = run_ui.GRAGMemory
        original_conversations = run_ui.ConversationManager

        def temporary_memory(*args, **kwargs):
            kwargs["graph_save_path"] = str(workdir / "local_graph.graphml")
            kwargs["entities_json_path"] = str(workdir / "entities.json")
            return original_memory(*args, **kwargs)

        run_ui.GRAGMemory = temporary_memory
        run_ui.ConversationManager = lambda _path: original_conversations(workdir)
        run_ui.GraphPage.refresh_graph = lambda self: None
        run_ui.EchoGraphMainWindow.load_conversation_knowledge_graph = lambda self, _id: False
        run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, "api_server_process", None)
        requests.post = lambda *_args, **_kwargs: SimpleNamespace(
            ok=True, status_code=200, json=lambda: {"ok": True, "llm_configured": True})
        QMessageBox.critical = lambda *_args: (_ for _ in ()).throw(AssertionError(_args[-1]))
        messages = []
        QMessageBox.information = lambda *_args: messages.append(_args[-1])

        if mode == "main":
            env_path = workdir / ".env"
            env_path.write_text("UI_THEME=ink\nOPENAI_API_KEY=fake-key\nOPENAI_API_BASE_URL=http://127.0.0.1:1/v1\n", encoding="utf-8")
            original_create = run_ui.create_app_and_window

            def create_for_main(**kwargs):
                app, window = original_create(env_path=env_path, **kwargs)
                QTimer.singleShot(800, lambda: (print(f"main outside cwd: theme={theme.current_name()} cwd={Path.cwd()} key_set={bool(os.getenv('OPENAI_API_KEY'))}", flush=True), os._exit(0)))
                return app, window

            run_ui.create_app_and_window = create_for_main
            run_ui.main()
            raise AssertionError("main returned before timer")

        class ModelsHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path != "/v1/models" or self.headers.get("Authorization") != "Bearer fake-key":
                    self.send_response(404)
                    self.end_headers()
                    return
                data = {"data": [{"id": "alpha", "context_length": 128000,
                                  "top_provider": {"max_completion_tokens": 8192},
                                  "architecture": {"input_modalities": ["text", "image"]},
                                  "supported_parameters": ["tools", "reasoning"],
                                  "owned_by": "local-fake", "pricing": {"prompt": "0.001", "completion": "0.002"}}]}
                body = json.dumps(data).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), ModelsHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        port = server.server_address[1]

        def local_get(url, *args, **kwargs):
            if url.startswith(f"http://127.0.0.1:{port}/"):
                return real_get(url, *args, **kwargs)
            raise requests.ConnectionError("test backend unavailable")

        requests.get = local_get
        env_path = workdir / ".env"
        env_path.write_text(f"UI_THEME=sand\nOPENAI_API_KEY=fake-key\nOPENAI_API_BASE_URL=http://127.0.0.1:{port}/v1\nDEFAULT_MODEL=alpha\nAPI_SERVER_PORT=19543\n", encoding="utf-8")
        app, window = run_ui.create_app_and_window(env_path=env_path)
        window.resize(1150, 850)
        window.tabs.setCurrentWidget(window.config_page)
        app.processEvents()
        page = window.config_page
        page.api_key_input.setText("")
        page.fetch_models_button.click()
        assert "密钥不能为空" in page.model_status_label.text()
        print(f"empty key: {page.model_status_label.text()}", flush=True)
        page.api_key_input.setText("fake-key")
        page.fetch_models_button.click()
        for _ in range(300):
            QTest.qWait(20)
            if page.fetch_models_button.isEnabled():
                break
        assert page.fetch_models_button.isEnabled(), "model worker did not finish"
        assert page.model_input.itemText(0) == "alpha"
        page.model_input.setCurrentText("alpha")
        app.processEvents()
        print(f"fetch: {page.model_status_label.text()}", flush=True)
        for name, label in page.model_detail_labels.items():
            print(f"{name}: {label.text()}", flush=True)
        group = next(group for group in page.findChildren(QGroupBox) if group.title() == "LLM模型配置")
        SHOTS.mkdir(exist_ok=True)
        for name in ("sand", "ink"):
            run_ui.WindowManager.apply_theme(app, name)
            app.processEvents()
            path = SHOTS / f"llm-{name}.png"
            assert group.grab().save(str(path))
            print(f"screenshot {name}: {path}", flush=True)
        page.theme_combo.setCurrentIndex(page.theme_combo.findData("ink"))
        page.model_input.setCurrentText("typed-model")
        page.save_button.click()
        for _ in range(300):
            QTest.qWait(20)
            if page.save_button.isEnabled() and messages:
                break
        from dotenv import dotenv_values
        from src.utils.config import config
        assert config.llm.model == dotenv_values(env_path)["DEFAULT_MODEL"] == "typed-model"
        assert messages and "后端已加载新 LLM 设置" in messages[-1]
        print(f"save: model={config.llm.model} message={messages[-1]}", flush=True)
        os._exit(0)
    except BaseException:
        traceback.print_exc()
        os._exit(1)


def parent():
    with tempfile.TemporaryDirectory(prefix="echograph-model-harness-") as folder:
        workdir = Path(folder)
        env = os.environ.copy()
        env.pop("UI_THEME", None)
        env.update({"PYTHONPATH": str(ROOT), "QT_QPA_PLATFORM": "offscreen",
                    "QT_QPA_FONTDIR": "C:/Windows/Fonts", "QTWEBENGINE_DISABLE_SANDBOX": "1",
                    "QTWEBENGINE_CHROMIUM_FLAGS": "--no-sandbox --disable-gpu"})
        for mode in ("models", "main"):
            result = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--child", mode, str(workdir)],
                                    cwd=workdir, env=env, capture_output=True, text=True, timeout=90)
            print(f"{mode}: exit={result.returncode}\n{result.stdout}", flush=True)
            if result.returncode:
                print(result.stderr[-6000:], file=sys.stderr)
                raise RuntimeError(f"{mode} harness failed")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--child":
        child(sys.argv[2], sys.argv[3])
    else:
        parent()
