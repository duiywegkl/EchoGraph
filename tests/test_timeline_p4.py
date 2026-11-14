"""Tavern HTTP bridge with a fake LLM and an isolated timeline root."""

import json
from types import SimpleNamespace
from threading import Event

from fastapi.testclient import TestClient

from api_server import app
from src.timeline.tavern import TavernTimeline
from src.timeline.segments import segment_messages


class FakeLLM:
    model = 'fake'

    def __init__(self):
        self.calls = []
        self.fail = False

    def chat_with_metadata(self, messages, **_kwargs):
        self.calls.append(messages)
        if self.fail:
            raise RuntimeError('fake failure')
        prompt = messages[-1]['content']
        response = ('{"operations":[]}' if '待处理：' in prompt else
                    '{"main_character":{"name":"阿青","type":"character"},"entities":[],"relationships":[]}')
        return SimpleNamespace(content=response, finish_reason=None)


def msg(role, content, ident=None, included=True):
    ident = ident or content
    return {'msg_id': ident, 'version_id': ident, 'role': role,
            'content': content, 'included': included}


def await_job(service, uuid):
    for _ in range(4):
        job = service.jobs.get(uuid)
        if job:
            job.result(timeout=5)
        if not service.jobs.get(uuid) or service.jobs[uuid].done():
            return


def test_tavern_http_timeline(tmp_path):
    fake = FakeLLM()
    service = TavernTimeline(tmp_path / 'tavern_timeline', lambda: fake)
    app.state.tavern_timeline = service
    api = TestClient(app)
    register = lambda uuid, integrity, file, exists=False: api.post('/timeline/register', json={
        'chat_uuid': uuid, 'integrity': integrity, 'owner': 'avatar.png',
        'file_name': file, 'previous_file_exists': exists}).json()
    assert register('parent', 'i1', 'main')['kind'] == 'new'
    assert register('parent', 'i1', 'main')['kind'] == 'same'
    assert register('parent', 'i1', 'renamed')['kind'] == 'renamed'
    source = {'owner': 'avatar.png', 'card': {'name': '阿青', 'description': '旅人'}, 'books': []}
    assert api.post('/timeline/base', json=source).json()['status'] == 'building'
    service.base_jobs[('avatar.png', next(iter(service.base_jobs))[1])].result(timeout=5)
    assert api.post('/timeline/base', json=source).json()['status'] == 'completed'
    assert len(fake.calls) == 1
    opening = [msg('assistant', '开局 A', 'greeting')]
    def sync(messages, uuid='parent', books=None):
        reply = api.post('/timeline/sync', json={'chat_uuid': uuid, 'messages': messages,
                                                 'books': books or []})
        assert reply.status_code == 200, reply.text
        await_job(service, uuid)
        assert api.get(f'/timeline/status/{uuid}').json()['state'] == 'consistent'
    sync(opening)
    count = len(fake.calls)
    sync([msg('assistant', '开局 B', 'greeting')])
    assert len(fake.calls) > count
    count = len(fake.calls)
    sync(opening)
    assert len(fake.calls) == count
    reply = opening + [msg('user', '问题'), msg('assistant', '回答')]
    sync(reply)
    count = len(fake.calls)
    sync(reply + [msg('user', '剪掉')])
    assert len(fake.calls) == count  # unfinished trailing user segment
    sync(reply)
    assert len(fake.calls) == count
    sync([opening[0], msg('user', '改过的问题', '问题'), reply[-1]])
    assert len(fake.calls) > count
    count = len(fake.calls)
    sync([opening[0], msg('user', '改过的问题', '问题', False), reply[-1]])
    assert len(fake.calls) > count
    child = register('parent', 'i2', 'branch', True)
    assert child['kind'] == 'derived'
    child_uuid = child['chat_uuid']
    assert child_uuid != 'parent'
    parent_head = service.store.get_chat('parent')['head_key']
    sync(reply, child_uuid)
    child_head = service.store.get_chat(child_uuid)['head_key']
    sync([msg('assistant', '新开局')])
    assert service.store.get_chat(child_uuid)['head_key'] == child_head
    assert service.store.get_chat('parent')['head_key'] != parent_head
    copy = register('parent', 'i1', 'copy', True)
    assert copy['kind'] == 'derived'
    assert api.get('/timeline/identity/parent').json()['previous_file_name'] == 'renamed'
    graph = api.get(f'/timeline/graph/{child_uuid}').json()
    assert graph['graph_data']['nodes']
    assert api.get(f'/timeline/prompt/{child_uuid}').status_code == 200
    payload = {'op': 'add_node', 'payload': {'id': 'manual', 'name': '手动', 'type': 'character'}}
    assert api.post(f'/timeline/manual/{child_uuid}', json=payload).status_code == 200
    assert '手动' in api.get(f'/timeline/prompt/{child_uuid}').json()['content']
    assert api.post(f'/timeline/undo/{child_uuid}').json()['manual']['can_redo']
    assert api.post(f'/timeline/redo/{child_uuid}').json()['manual']['can_undo']
    assert api.get('/timeline/current').json()['chat_uuid'] == copy['chat_uuid']
    del app.state.tavern_timeline


def test_tavern_failure_retry_and_chat_book(tmp_path):
    fake = FakeLLM()
    service = TavernTimeline(tmp_path, lambda: fake)
    app.state.tavern_timeline = service
    api = TestClient(app)
    api.post('/timeline/register', json={'chat_uuid': 'c', 'integrity': 'i',
        'owner': 'o', 'file_name': 'c', 'previous_file_exists': False})
    base = api.post('/timeline/base', json={'owner': 'o', 'card': {'name': '阿青'}, 'books': []}).json()
    service.base_jobs[('o', base['base_hash'])].result(timeout=5)
    fake.fail = True
    api.post('/timeline/sync', json={'chat_uuid': 'c', 'messages': [msg('assistant', '开局')]})
    await_job(service, 'c')
    assert api.get('/timeline/status/c').json()['state'] == 'inconsistent'
    fake.fail = False
    api.post('/timeline/retry/c')
    await_job(service, 'c')
    assert api.get('/timeline/status/c').json()['state'] == 'consistent'
    count = len(fake.calls)
    book = {'source': 'chat', 'name': '聊天书', 'entries': [
        {'uid': 1, 'key': ['旅人'], 'content': '一座城', 'disable': False}]}
    api.post('/timeline/sync', json={'chat_uuid': 'c', 'messages': [msg('assistant', '开局')], 'books': [book]})
    await_job(service, 'c')
    assert len(fake.calls) > count
    del app.state.tavern_timeline


def test_tavern_branch_reuses_prefix_and_parent_edit_isolated(tmp_path):
    fake = FakeLLM()
    service = TavernTimeline(tmp_path, lambda: fake)
    app.state.tavern_timeline = service
    api = TestClient(app)
    def register(uuid, integrity, file):
        return api.post('/timeline/register', json={'chat_uuid': uuid, 'integrity': integrity,
            'owner': 'o', 'file_name': file, 'previous_file_exists': True}).json()['chat_uuid']
    register('parent', 'i1', 'parent')
    base = api.post('/timeline/base', json={'owner': 'o', 'card': {'name': '阿青'}, 'books': []}).json()
    service.base_jobs[('o', base['base_hash'])].result(timeout=5)
    prefix = [msg('assistant', '开局'), msg('user', '问一'), msg('assistant', '答一')]
    api.post('/timeline/sync', json={'chat_uuid': 'parent', 'messages': prefix})
    await_job(service, 'parent')
    child = register('parent', 'i2', 'branch')
    before = len(fake.calls)
    extended = prefix + [msg('user', '问二'), msg('assistant', '答二')]
    api.post('/timeline/sync', json={'chat_uuid': child, 'messages': extended})
    await_job(service, child)
    assert len(fake.calls) == before + 1
    child_head = service.store.get_chat(child)['head_key']
    api.post('/timeline/sync', json={'chat_uuid': 'parent', 'messages': [msg('assistant', '改过的开局')]})
    await_job(service, 'parent')
    assert service.store.get_chat(child)['head_key'] == child_head
    api.post('/timeline/manual/parent', json={'op': 'add_node', 'payload':
        {'id': 'parent-only', 'name': '父图', 'type': 'character'}})
    assert '父图' in api.get('/timeline/prompt/parent').json()['content']
    assert '父图' not in api.get(f'/timeline/prompt/{child}').json()['content']
    del app.state.tavern_timeline


def test_tavern_new_sync_supersedes_running_worker(tmp_path):
    fake = FakeLLM()
    service = TavernTimeline(tmp_path, lambda: fake)
    app.state.tavern_timeline = service
    api = TestClient(app)
    api.post('/timeline/register', json={'chat_uuid': 'c', 'integrity': 'i',
        'owner': 'o', 'file_name': 'c', 'previous_file_exists': False})
    base = api.post('/timeline/base', json={'owner': 'o', 'card': {'name': '阿青'}, 'books': []}).json()
    service.base_jobs[('o', base['base_hash'])].result(timeout=5)
    started, release = Event(), Event()
    class BlockingExtractor:
        context_size = 0
        def extract(self, _state, _segments):
            started.set()
            assert release.wait(5)
            return []
    service.engine.extractor = BlockingExtractor()
    first = [msg('assistant', '开局 A')]
    second = [msg('assistant', '开局 B')]
    api.post('/timeline/sync', json={'chat_uuid': 'c', 'messages': first})
    assert started.wait(5)
    api.post('/timeline/sync', json={'chat_uuid': 'c', 'messages': second})
    release.set()
    await_job(service, 'c')
    chat = service.store.get_chat('c')
    assert chat['head_key'] == segment_messages(second, chat['base_hash'])[-1].key
    assert api.get('/timeline/status/c').json()['state'] == 'consistent'
    del app.state.tavern_timeline
