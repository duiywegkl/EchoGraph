"""Offscreen P4 graph page. All HTTP and WebEngine network are stubbed before construction."""

import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'
os.environ['QT_QPA_FONTDIR'] = 'C:/Windows/Fonts'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--no-sandbox --disable-gpu --disable-software-rasterizer'

import json
import sys
import tempfile
import time
import traceback
from pathlib import Path
from types import SimpleNamespace

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestInterceptor

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import run_ui


class BlockNetwork(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if info.requestUrl().scheme() in ('http', 'https', 'ws', 'wss'):
            info.block(True)


def response(value):
    return SimpleNamespace(ok=True, status_code=200, json=lambda: value,
                           raise_for_status=lambda: None)


def main():
    root = Path(tempfile.gettempdir()) / 'echograph-p5-shots'
    root.mkdir(parents=True, exist_ok=True)
    state = {'phase': 'processing', 'retry': False}
    graph = {'session_id': 'chat-a', 'chat_uuid': 'chat-a',
             'graph_data': {'nodes': [
                 {'id': 'a', 'name': '阿青', 'type': 'character', 'description': '旅人', 'attributes': {}},
                 {'id': 'b', 'name': '旧城', 'type': 'location', 'attributes': {}}],
                 'links': [{'edge_id': 'edge-1', 'source': 'a', 'target': 'b',
                            'relation': '到达', 'relationship': '到达'}]},
             'graph_stats': {'nodes': 2, 'edges': 1},
             'manual': {'can_undo': True, 'can_redo': True, 'skipped': 0}}

    def fake_get(url, **_kwargs):
        assert '/timeline/graph/chat-a' in url, url
        value = {**graph, 'status': {'state': state['phase'],
                 'reason': '模拟提取失败' if state['phase'] == 'inconsistent' else None}}
        return response(value)

    def fake_post(url, **_kwargs):
        assert url.endswith('/timeline/retry/chat-a'), url
        state['retry'] = True
        state['phase'] = 'processing'
        return response({})

    run_ui.requests.get = fake_get
    run_ui.requests.post = fake_post
    run_ui.requests.request = lambda *_args, **_kwargs: response({})
    app = QApplication.instance() or QApplication([])
    interceptor = BlockNetwork()
    QWebEngineProfile.defaultProfile().setUrlRequestInterceptor(interceptor)
    original_refresh = run_ui.GraphPage.refresh_graph
    run_ui.GraphPage.refresh_graph = lambda self: None
    page = run_ui.GraphPage(SimpleNamespace())
    run_ui.GraphPage.refresh_graph = original_refresh
    page.layout_storage_root = root
    page.graph_file_path = root / 'graph.html'
    page.resize(1120, 780)
    page.show()
    page.enter_tavern_mode('chat-a')

    def shot(name):
        assert page.refresh_from_api_server('chat-a', force=True)
        until = time.monotonic() + 0.6
        while time.monotonic() < until:
            app.processEvents()
            time.sleep(0.02)
        assert page.undo_btn.isEnabled() and page.redo_btn.isEnabled()
        path = root / name
        assert page.grab().save(str(path))
        print(f'{name}: {page.tavern_timeline_status.text()} | 撤销={page.undo_btn.isEnabled()} 重做={page.redo_btn.isEnabled()} | {path}', flush=True)

    def run():
        try:
            shot('processing.png')
            state['phase'] = 'inconsistent'
            shot('inconsistent.png')
            assert page.tavern_timeline_retry.isVisible()
            page.tavern_timeline_retry.click()
            assert state['retry']
            shot('retry.png')
            os._exit(0)
        except Exception:
            traceback.print_exc()
            os._exit(1)

    QTimer.singleShot(700, run)
    QTimer.singleShot(12000, lambda: os._exit(2))
    app.exec()


if __name__ == '__main__':
    main()
