"""Offscreen P0 startup smoke test. Run from an outside working directory."""

import os
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMessageBox, QScrollArea

import requests
import run_ui


class StubNetworkReply(QObject):
    finished = Signal()

    def error(self):
        return QNetworkReply.NoError

    def attribute(self, attribute):
        assert attribute == QNetworkRequest.HttpStatusCodeAttribute
        return 200

    def readAll(self):
        return b'{"connected": true}'


class StubNetworkManager:
    def __init__(self, parent):
        self.parent = parent

    def get(self, request):
        assert request.url().toString() == 'http://127.0.0.1:9543/system/plugin_status'
        reply = StubNetworkReply()
        QTimer.singleShot(0, reply.finished.emit)
        return reply


def stub_get(url, **kwargs):
    assert '9543' in url and url.startswith(('http://127.0.0.1:', 'http://localhost:')), url
    return SimpleNamespace(status_code=200, ok=True, json=lambda: {'connected': True})


def stub_post(url, **kwargs):
    assert '9543' in url and url.startswith(('http://127.0.0.1:', 'http://localhost:')), url
    return SimpleNamespace(status_code=200, ok=True, json=lambda: {})


requests.get = stub_get
requests.post = stub_post
run_ui.QNetworkAccessManager = StubNetworkManager
original_log_add = run_ui.logger.add
run_ui.logger.add = lambda sink, **kwargs: original_log_add(sink, **kwargs) if sink is sys.stderr else 0
run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, 'api_server_process', None)
run_ui.EchoGraphMainWindow.load_conversation_knowledge_graph = lambda self, conv_id: False
run_ui.GraphPage.save_graph_layout = lambda self, positions: None
QMessageBox.critical = lambda *_args: (_ for _ in ()).throw(AssertionError(_args[-1]))
QMessageBox.warning = QMessageBox.critical
QMessageBox.question = lambda *_args: QMessageBox.No

original_create = run_ui.create_app_and_window


def create_and_capture(*args, **kwargs):
    app, window = original_create(*args, **kwargs)

    def capture():
        try:
            window.tabs.setCurrentWidget(window.config_page)
            window.config_page.refresh_connection_status()
            scroll = window.config_page.findChild(QScrollArea)
            scroll.verticalScrollBar().setValue(650)
            app.processEvents()
            assert window.isVisible()
            assert window.config_page.plugin_status_label.text() == '已连接'
            assert window.config_page.backend_status_label.text() == '运行中'
            shot_dir = Path(tempfile.gettempdir()) / 'echograph-p0-shots'
            shot_dir.mkdir(exist_ok=True)
            shot = shot_dir / 'config-page.png'
            assert window.grab().save(str(shot))
            print(f'OK cwd={Path.cwd()} screenshot={shot} size={window.width()}x{window.height()} '
                  f'plugin={window.config_page.plugin_status_label.text()} '
                  f'backend={window.config_page.backend_status_label.text()}', flush=True)
            os._exit(0)
        except BaseException:
            traceback.print_exc()
            os._exit(1)

    QTimer.singleShot(500, capture)
    return app, window


run_ui.create_app_and_window = create_and_capture
run_ui.main()
