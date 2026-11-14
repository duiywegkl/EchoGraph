"""Run real UI startup with temp data and fake extraction; never closes Qt normally."""

import os
import sys
import tempfile
import traceback
import faulthandler
from pathlib import Path
from types import SimpleNamespace

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_FONTDIR'] = 'C:/Windows/Fonts'
os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--no-sandbox --disable-gpu --disable-software-rasterizer'
faulthandler.enable()
sys.excepthook = lambda typ, value, tb: (print('UNHANDLED', flush=True), traceback.print_exception(typ, value, tb))

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QMessageBox
import requests
import run_ui

from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEngineUrlRequestInterceptor

class BlockWebNetwork(QWebEngineUrlRequestInterceptor):
    def interceptRequest(self, info):
        if info.requestUrl().scheme() in ('http', 'https', 'ws', 'wss'):
            info.block(True)



ROOT = Path(run_ui.__file__).resolve().parent
DATA = Path(tempfile.mkdtemp(prefix='echograph-p3-data-'))
os.environ['ECHOGRAPH_DATA_ROOT'] = str(DATA)
TEMP_ENV = DATA / '.env'
TEMP_ENV.write_text('UI_THEME=sand\nOPENAI_API_KEY=\n', encoding='utf-8')
SHOTS = Path(tempfile.gettempdir()) / 'echograph-p5-shots'
SHOTS.mkdir(exist_ok=True)


def response(url, **kwargs):
    assert '9543' not in url or url.startswith(('http://127.0.0.1:9543', 'http://localhost:9543'))
    return SimpleNamespace(ok=True, status_code=200, json=lambda: {'connected': True})


requests.get = response
requests.post = response
requests.request = lambda *_args, **_kwargs: response(_args[1] if len(_args) > 1 else _args[0])


class StubNetworkReply(QObject):
    finished = Signal()
    def error(self):
        return QNetworkReply.NoError
    def attribute(self, _attribute):
        return 200
    def readAll(self):
        return b'{"connected": true}'


class StubNetworkManager:
    def __init__(self, parent):
        self.parent = parent
    def get(self, request):
        reply = StubNetworkReply()
        QTimer.singleShot(0, reply.finished.emit)
        return reply


run_ui.QNetworkAccessManager = StubNetworkManager
run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, 'api_server_process', None)
_log_add = run_ui.logger.add
run_ui.logger.add = lambda sink, **kwargs: _log_add(sys.stderr, level='ERROR') if sink is sys.stderr else 0
QMessageBox.warning = lambda *_args: (_ for _ in ()).throw(AssertionError(str(_args)))
QMessageBox.critical = QMessageBox.warning
QMessageBox.information = lambda *_args: QMessageBox.Ok
QMessageBox.question = lambda *_args: QMessageBox.Yes


class FakeExtractor:
    context_size = 0
    model = 'fake'
    fail = False
    calls = 0

    def extract(self, state, segments):
        self.calls += 1
        if self.fail:
            raise RuntimeError('模拟提取失败')
        result = []
        for segment in segments:
            text = ' → '.join(message['content'] for message in segment.messages)
            ident = 'node_' + str(segment.turn)
            if ident in state.nodes:
                result.append({'turn': segment.turn, 'op': 'update_node', 'id': ident,
                               'name': text[:30]})
            else:
                result.append({'turn': segment.turn, 'op': 'add_node', 'id': ident,
                               'name': text[:30], 'type': 'character'})
        return result


fake = FakeExtractor()
original_create = run_ui.create_app_and_window
_queue_timeline = run_ui.IntegratedPlayPage.queue_timeline
run_ui.IntegratedPlayPage.queue_timeline = lambda self: None


def create_and_schedule(*args, **kwargs):
    print('creating window', flush=True)
    app, window = original_create(env_path=TEMP_ENV, *args, **kwargs)
    global _web_blocker
    _web_blocker = BlockWebNetwork()
    QWebEngineProfile.defaultProfile().setUrlRequestInterceptor(_web_blocker)
    print('window created', flush=True)
    print('visible', window.isVisible(), flush=True)
    app.aboutToQuit.connect(lambda: print('about to quit', flush=True))
    window.resize(1500, 950)
    page = window.play_page
    run_ui.IntegratedPlayPage.queue_timeline = _queue_timeline
    page.timeline_engine.extractor = fake

    def shot(name, tab='graph'):
        print('shot begin', name, flush=True)
        window.tabs.setCurrentWidget(window.graph_page if tab == 'graph' else page)
        app.processEvents()
        path = SHOTS / (name + '.png')
        assert window.grab().save(str(path))
        print(name, path, 'status=', page.timeline_status.text(),
              'nodes=', window.memory.knowledge_graph.graph.number_of_nodes(),
              'edges=', window.memory.knowledge_graph.graph.number_of_edges(), flush=True)

    def guarded(callback):
        try:
            callback()
        except BaseException:
            traceback.print_exc()
            os._exit(1)

    def step_a():
        print('step_a', flush=True)
        window.tabs.setCurrentWidget(window.graph_page)
        QTimer.singleShot(700, lambda: guarded(step_a_capture))

    def step_a_capture():
        shot('a-default-zero')
        conv_id = page.conversation_manager.create_conversation('三版本对话')
        page.conversation_manager.add_message({'role': 'user', 'content': '旅程开始'})
        page.conversation_manager.add_message({'role': 'assistant', 'content': '版本一'})
        page.conversation_manager.add_swipe(1, '版本二')
        page.conversation_manager.add_swipe(1, '版本三')
        page.conversation_manager.switch_swipe(1, 1)
        page.load_conversation(conv_id)
        QTimer.singleShot(1300, lambda: guarded(step_b))

    def step_b():
        assert '2/3' in page.chat_display.message_widgets[1]['widget'].findChildren(run_ui.QLabel)[1].text() or any(
            label.text() == '2/3' for label in page.chat_display.message_widgets[1]['widget'].findChildren(run_ui.QLabel))
        window.tabs.setCurrentWidget(page)
        QTimer.singleShot(450, lambda: guarded(step_b_capture))

    def step_b_capture():
        shot('b-three-swipes', 'chat')
        window.tabs.setCurrentWidget(window.graph_page)
        QTimer.singleShot(650, lambda: guarded(step_b_graph))

    def step_b_graph():
        shot('b-swipe-graph')
        page.conversation_manager.edit_message(0, '旅程改写')
        page.load_conversation(page.conversation_manager.current_conversation_id)
        QTimer.singleShot(1300, lambda: guarded(step_c))

    def step_c():
        shot('c-edited-earlier')
        fake.fail = True
        page.conversation_manager.edit_message(0, '失败的编辑')
        page.load_conversation(page.conversation_manager.current_conversation_id)
        QTimer.singleShot(1300, lambda: guarded(step_d))

    def step_d():
        assert '图谱与聊天不一致' in page.timeline_status.text()
        shot('d-inconsistent-retry', 'chat')
        fake.fail = False
        page.retry_timeline()
        QTimer.singleShot(1300, lambda: guarded(step_e))

    def step_e():
        graph = window.graph_page
        layer, head = graph._manual_context()
        layer.apply('add_node', {'id': 'manual_a', 'name': '手动甲', 'type': 'character'}, head)
        layer.apply('add_node', {'id': 'manual_b', 'name': '手动乙', 'type': 'character'}, head)
        graph.reload_manual_graph()
        assert graph.undo_btn.isEnabled()
        window.tabs.setCurrentWidget(graph)
        QTimer.singleShot(500, lambda: guarded(step_e_capture))

    def step_e_capture():
        graph = window.graph_page
        layer, head = graph._manual_context()
        shot('e-manual-undo-redo')
        layer.apply('add_edge', {'id': 'relation_a', 'source': 'manual_a', 'target': 'manual_b',
                                 'relation': '朋友'}, head)
        layer.apply('add_edge', {'id': 'relation_b', 'source': 'manual_a', 'target': 'manual_b',
                                 'relation': '同伴'}, head)
        graph.reload_manual_graph()
        QTimer.singleShot(1300, lambda: guarded(step_f))

    def step_f():
        assert window.memory.knowledge_graph.graph.number_of_edges('manual_a', 'manual_b') == 2
        import json
        links = json.loads(window.graph_page.html_generator.last_graph_data[1])
        pair = [link for link in links if link['source'] == 'manual_a' and link['target'] == 'manual_b']
        assert {link['id'] for link in pair} == {'relation_a', 'relation_b'}
        shot('f-two-relations')
        page.conversation_manager.branch_from(1)
        QTimer.singleShot(1300, lambda: guarded(step_g))

    def step_g():
        assert any('分支' in conv['name'] for conv in page.conversation_manager.conversations.values())
        shot('g-branch-list', 'chat')
        print('fake extraction calls=', fake.calls, 'temp data=', DATA, flush=True)
        os._exit(0)

    QTimer.singleShot(0, lambda: print('event loop started', flush=True))
    QTimer.singleShot(3300, lambda: guarded(step_a))
    QTimer.singleShot(35000, lambda: os._exit(2))
    return app, window


run_ui.create_app_and_window = create_and_schedule
try:
    print('starting main', DATA, flush=True)
    run_ui.main()
except BaseException:
    traceback.print_exc()
    os._exit(1)
