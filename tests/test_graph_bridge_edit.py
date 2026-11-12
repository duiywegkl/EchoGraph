import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QMessageBox, QPushButton, QWidget

import run_ui


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def test_bridge_opens_editor_in_both_modes(app, monkeypatch):
    calls = []
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    page = SimpleNamespace(
        tavern_mode=False,
        tavern_session_id=None,
        showing_tavern_placeholder=False,
        edit_node_with_python_dialog=lambda *args: calls.append(args),
    )
    bridge = run_ui.GraphBridge(page)
    bridge.editNode("Alice", "character")
    page.tavern_mode = True
    page.tavern_session_id = "session-1"
    bridge.editNode("Alice", "character")
    assert calls == [("Alice", "character"), ("Alice", "character")]
    assert warnings == []


def test_bridge_reports_unavailable_session(app, monkeypatch):
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    page = SimpleNamespace(
        tavern_mode=True,
        tavern_session_id=None,
        showing_tavern_placeholder=True,
        edit_node_with_python_dialog=lambda *args: pytest.fail("dialog opened"),
    )
    run_ui.GraphBridge(page).editNode("Alice", "character")
    assert len(warnings) == 1
    assert "\u9152\u9986" in warnings[0][2]


def test_tavern_dialog_saves_renamed_node_via_api(app, monkeypatch):
    calls = []
    notices = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: notices.append(("warning", args)))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: notices.append(("information", args)))
    monkeypatch.setattr(
        run_ui.requests,
        "request",
        lambda method, url, **kwargs: (
            calls.append((method, url, kwargs))
            or SimpleNamespace(ok=True, json=lambda: {"ok": True})
        ),
    )
    page = QWidget()
    page.tavern_mode = True
    page.tavern_session_id = "session-1"
    page._api_base_url = lambda: "http://stub.invalid"
    page.refresh_from_api_server = lambda session_id, force=False: True
    page.get_all_entities = lambda: [{
        "name": "Alice", "type": "character", "description": "old",
        "attributes": {"role": "hero"}, "created_time": 1,
    }]
    page._tavern_mutation = lambda *args, **kwargs: run_ui.GraphPage._tavern_mutation(page, *args, **kwargs)
    page.save_entities = lambda *args, **kwargs: run_ui.GraphPage.save_entities(page, *args, **kwargs)
    page.refresh_graph = lambda: None

    def accept_dialog(dialog):
        from PySide6.QtWidgets import QLineEdit
        name = next(w for w in dialog.findChildren(QLineEdit) if w.text() == "Alice")
        name.setText("Alicia")
        save = next(w for w in dialog.findChildren(QPushButton) if w.text() == "\u4fdd\u5b58")
        save.click()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", accept_dialog)
    run_ui.GraphPage.edit_node_with_python_dialog(page, "Alice", "character")
    assert len(calls) == 1, notices
    method, url, kwargs = calls[0]
    assert (method, url) == ("PUT", "http://stub.invalid/sessions/session-1/nodes/Alice")
    assert kwargs["json"]["name"] == "Alicia"
    assert kwargs["json"]["type"] == "character"
    assert kwargs["json"]["attributes"] == {"role": "hero"}
    assert notices[0][0] == "information"


def test_tavern_dialog_deletes_node_via_api(app, monkeypatch):
    from PySide6.QtWidgets import QTextEdit
    calls = []
    warnings = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        run_ui.requests, "request",
        lambda method, url, **kwargs: (
            calls.append((method, url))
            or SimpleNamespace(ok=True, json=lambda: {"ok": True})
        ),
    )
    page = QWidget()
    page.tavern_mode = True
    page.tavern_session_id = "session-1"
    page.current_selected_node = "[character] Alice"
    page.detail_text = QTextEdit()
    page._api_base_url = lambda: "http://stub.invalid"
    page.refresh_from_api_server = lambda session_id, force=False: True
    page._tavern_mutation = lambda *args, **kwargs: run_ui.GraphPage._tavern_mutation(page, *args, **kwargs)
    page.get_all_entities = lambda: [{
        "name": "Alice", "type": "character", "description": "old",
        "attributes": {}, "created_time": 1,
    }]

    def accept_dialog(dialog):
        delete = next(w for w in dialog.findChildren(QPushButton) if w.text() == "\u5220\u9664\u8282\u70b9")
        delete.click()
        return QDialog.Accepted

    monkeypatch.setattr(QDialog, "exec", accept_dialog)
    run_ui.GraphPage.edit_node_with_python_dialog(page, "Alice", "character")
    assert calls == [("DELETE", "http://stub.invalid/sessions/session-1/nodes/Alice")]
    assert warnings == []


def test_tavern_api_error_reaches_dialog(app, monkeypatch):
    from PySide6.QtWidgets import QLineEdit
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)
    monkeypatch.setattr(
        run_ui.requests, "request",
        lambda *args, **kwargs: SimpleNamespace(
            ok=False, text="conflict", json=lambda: {"detail": "Node name already exists"}
        ),
    )
    page = QWidget()
    page.tavern_mode = True
    page.tavern_session_id = "session-1"
    page._api_base_url = lambda: "http://stub.invalid"
    page.refresh_from_api_server = lambda *args, **kwargs: True
    page._tavern_mutation = lambda *args, **kwargs: run_ui.GraphPage._tavern_mutation(page, *args, **kwargs)
    page.save_entities = lambda *args, **kwargs: run_ui.GraphPage.save_entities(page, *args, **kwargs)
    page.get_all_entities = lambda: [{"name": "Alice", "type": "character", "attributes": {}}]
    page.refresh_graph = lambda: pytest.fail("refresh after failed save")

    def save_dialog(dialog):
        next(w for w in dialog.findChildren(QLineEdit) if w.text() == "Alice").setText("Alicia")
        next(w for w in dialog.findChildren(QPushButton) if w.text() == "\u4fdd\u5b58").click()
        return QDialog.Rejected

    monkeypatch.setattr(QDialog, "exec", save_dialog)
    run_ui.GraphPage.edit_node_with_python_dialog(page, "Alice", "character")
    assert len(warnings) == 1
    assert "Node name already exists" in warnings[0][2]


def test_unchanged_tavern_graph_skips_page_reload(monkeypatch):
    graph = {"graph_data": {"nodes": [{"id": "Alice", "type": "character"}], "links": []}}
    monkeypatch.setattr(
        run_ui.requests, "get",
        lambda url, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: {"graph_nodes": 1} if url.endswith("/stats") else graph,
        ),
    )
    page = SimpleNamespace(
        tavern_mode=True,
        tavern_session_id="session-1",
        showing_tavern_placeholder=False,
        _tavern_graph_data=graph,
        _api_base_url=lambda: "http://stub.invalid",
    )
    assert run_ui.GraphPage.refresh_from_api_server(page, "session-1", force=True)


def test_unchanged_tavern_placeholder_skips_page_reload(monkeypatch):
    stats = {"graph_nodes": 0, "graph_edges": 0}
    state = {"session_id": "session-1", "initialization_status": "pending"}
    monkeypatch.setattr(
        run_ui.requests, "get",
        lambda url, **kwargs: SimpleNamespace(
            status_code=200,
            json=lambda: stats if url.endswith("/stats") else state,
        ),
    )
    page = SimpleNamespace(
        tavern_mode=True,
        tavern_session_id="session-1",
        showing_tavern_placeholder=True,
        _placeholder_stats={**stats, **state},
        _api_base_url=lambda: "http://stub.invalid",
    )
    assert run_ui.GraphPage.refresh_from_api_server(page, "session-1")
