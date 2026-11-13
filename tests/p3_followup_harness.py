"""Capture P3 follow-up UI with isolated storage, fake extraction, and stubbed network."""

import os
import sys
import tempfile
import traceback
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_FONTDIR'] = 'C:/Windows/Fonts'
os.environ['QTWEBENGINE_DISABLE_SANDBOX'] = '1'
os.environ['QTWEBENGINE_CHROMIUM_FLAGS'] = '--no-sandbox --disable-gpu --disable-software-rasterizer'

DATA = Path(tempfile.mkdtemp(prefix='echograph-p3-v2-data-'))
os.environ['ECHOGRAPH_DATA_ROOT'] = str(DATA)
TEMP_ENV = DATA / '.env'
TEMP_ENV.write_text('UI_THEME=sand\nOPENAI_API_KEY=\n', encoding='utf-8')
SHOTS = Path(tempfile.gettempdir()) / 'echograph-p3-shots-v2'
SHOTS.mkdir(exist_ok=True)

# Install both stubs before constructing the app or making the first UI call.
import requests

def response(*args, **kwargs):
    return SimpleNamespace(ok=True, status_code=200, text='{}',
                           json=lambda: {'connected': True, 'active': False})

requests.get = response
requests.post = response
requests.request = response
requests.Session.request = response

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QMessageBox
import run_ui

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

    def get(self, _request):
        reply = StubNetworkReply()
        QTimer.singleShot(0, reply.finished.emit)
        return reply

run_ui.QNetworkAccessManager = StubNetworkManager
run_ui.EchoGraphMainWindow.start_api_server = lambda self: setattr(self, 'api_server_process', None)
run_ui.logger.remove()
run_ui.logger.add(sys.stderr, level='ERROR')
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
            ident = 'node_' + str(segment.turn)
            name = ' / '.join(message['content'] for message in segment.messages)[:30]
            if ident in state.nodes:
                result.append({'turn': segment.turn, 'op': 'update_node', 'id': ident, 'name': name})
            else:
                result.append({'turn': segment.turn, 'op': 'add_node', 'id': ident,
                               'name': name, 'type': 'character'})
        return result

fake = FakeExtractor()
original_queue = run_ui.IntegratedPlayPage.queue_timeline
run_ui.IntegratedPlayPage.queue_timeline = lambda self: None
app, window = run_ui.create_app_and_window(env_path=TEMP_ENV, process_theme='sand')
window.resize(1500, 950)
page = window.play_page
graph = window.graph_page
page.timeline_engine.extractor = fake
run_ui.IntegratedPlayPage.queue_timeline = original_queue

def shot(name, tab='graph'):
    window.tabs.setCurrentWidget(graph if tab == 'graph' else page)
    app.processEvents()
    path = SHOTS / (name + '.png')
    assert window.grab().save(str(path))
    print(name, path, 'status=', page.timeline_status.text(),
          'nodes=', window.memory.knowledge_graph.graph.number_of_nodes(),
          'edges=', window.memory.knowledge_graph.graph.number_of_edges(), flush=True)

def later(milliseconds, callback):
    def guarded():
        try:
            callback()
        except BaseException:
            traceback.print_exc()
            os._exit(1)
    QTimer.singleShot(milliseconds, guarded)

def start():
    global conv_id
    conv_id = page.conversation_manager.create_conversation('三版本对话')
    page.conversation_manager.add_message({'role': 'user', 'content': '旅程开始'})
    page.conversation_manager.add_message({'role': 'assistant', 'content': '版本一'})
    page.conversation_manager.add_swipe(1, '版本二')
    page.conversation_manager.add_swipe(1, '版本三')
    page.conversation_manager.switch_swipe(1, 1)
    page.load_conversation(conv_id)
    later(1300, capture_b)

def capture_b():
    assert any(label.text() == '2/3' for label in
               page.chat_display.message_widgets[1]['widget'].findChildren(run_ui.QLabel))
    shot('b-three-swipes', 'chat')
    run_ui.WindowManager.apply_theme(app, 'ink')
    shot('ink-b-three-swipes', 'chat')
    run_ui.WindowManager.apply_theme(app, 'sand')
    make_long_chat()

def make_long_chat():
    page.queue_timeline = lambda: None
    long_id = page.conversation_manager.create_conversation('多轮对话')
    for i in range(6):
        page.conversation_manager.add_message({'role': 'user', 'content': f'用户第 {i + 1} 轮：讨论图谱'})
        page.conversation_manager.add_message({'role': 'assistant', 'content': f'助手第 {i + 1} 轮：记录变化'})
        if i in (0, 2, 4):
            index = 2 * i + 1
            page.conversation_manager.add_swipe(index, f'助手第 {i + 1} 轮：另一种回答')
            page.conversation_manager.switch_swipe(index, 1)
    page.load_conversation(long_id)
    window.resize(1500, 2050)
    later(200, capture_long)

def capture_long():
    assert len(page.chat_display.message_widgets) == 12
    shot('long-chat-mixed-swipes', 'chat')
    window.resize(1500, 950)
    del page.queue_timeline
    page.conversation_manager.switch_conversation(conv_id)
    later(1300, start_failure)

def start_failure():
    fake.fail = True
    page.conversation_manager.edit_message(0, '失败的编辑')
    page.load_conversation(conv_id)
    shot('processing-status', 'chat')
    later(1300, capture_d)

def capture_d():
    assert '图谱与聊天不一致' in page.timeline_status.text()
    assert page.timeline_status_row.isVisible() and page.timeline_retry.isVisible()
    shot('d-inconsistent-retry', 'chat')
    fake.fail = False
    page.retry_timeline()
    later(1300, capture_e)

def capture_e():
    assert not page.timeline_status_row.isVisible()
    layer, head = graph._manual_context()
    layer.apply('add_node', {'id': 'manual_a', 'name': '手动甲', 'type': 'character'}, head)
    layer.apply('add_node', {'id': 'manual_b', 'name': '手动乙', 'type': 'character'}, head)
    window.tabs.setCurrentWidget(graph)
    graph.reload_manual_graph()
    assert graph.undo_btn.isEnabled() and not graph.redo_btn.isEnabled()
    later(2500, capture_e_ready)

def capture_e_ready():
    shot('e-manual-undo-redo')
    run_ui.WindowManager.apply_theme(app, 'ink')
    graph.refresh_graph()
    later(1800, capture_ink_e)

def capture_ink_e():
    shot('ink-e-manual-undo-redo')
    run_ui.WindowManager.apply_theme(app, 'sand')
    layer, head = graph._manual_context()
    layer.apply('add_edge', {'id': 'relation_a', 'source': 'manual_a', 'target': 'manual_b',
                             'relation': '朋友'}, head)
    layer.apply('add_edge', {'id': 'relation_b', 'source': 'manual_a', 'target': 'manual_b',
                             'relation': '同伴'}, head)
    graph.reload_manual_graph()
    later(1800, capture_f)

def capture_f():
    assert window.memory.knowledge_graph.graph.number_of_edges('manual_a', 'manual_b') == 2
    shot('f-two-relations')
    print('fake extraction calls=', fake.calls, 'temp data=', DATA, flush=True)
    os._exit(0)

later(3500, start)
later(45000, lambda: os._exit(2))
app.exec()
