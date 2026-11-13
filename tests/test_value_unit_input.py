"""Base-unit conversion and config-save protection for the live Qt page."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from dotenv import dotenv_values
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMessageBox

from src.ui.value_unit_input import UnitSpec, ValueUnitInput


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def test_unit_switch_both_ways(app):
    field = ValueUnitInput([UnitSpec("秒", 1), UnitSpec("分钟", 60)], 30, 600)
    field.setValue(180)
    emitted = []
    field.valueChanged.connect(emitted.append)
    field.unit_combo.setCurrentIndex(1)
    assert field.number_edit.text() == "3"
    assert field.value() == 180
    field.unit_combo.setCurrentIndex(0)
    assert field.number_edit.text() == "180"
    assert field.value() == 180
    assert emitted == []  # A display-unit change does not change the quantity.


def test_set_value_round_trip_and_integer_rounding(app):
    field = ValueUnitInput([UnitSpec("毫秒", 1), UnitSpec("秒", 1000)], 100, 2000)
    field.setValue(1251)
    assert field.unit_combo.currentIndex() == 0
    field.unit_combo.setCurrentIndex(1)
    assert field.number_edit.text() == "1.251"
    assert field.value() == 1251
    field.unit_combo.setCurrentIndex(0)
    assert field.value() == 1251
    field.unit_combo.setCurrentIndex(1)
    field.number_edit.setText("1.2506")
    assert field.value() == 1251
    field.setValue(500)
    assert field.unit_combo.currentIndex() == 0
    assert field.value() == 500


def test_range_is_checked_in_base_units_and_invalid_text(app):
    field = ValueUnitInput([UnitSpec("秒", 1), UnitSpec("分钟", 60)], 30, 600)
    field.setValue(180)
    field.unit_combo.setCurrentIndex(1)
    field.number_edit.setText("11")
    assert not field.isValid()
    assert "0.5–10 分钟" in field.errorText()
    assert field.number_edit.property("invalid") is True
    assert field.number_edit.toolTip() == field.errorText()
    with pytest.raises(ValueError):
        field.value()
    field.number_edit.setText("abc")
    assert not field.isValid()
    assert "有效数字" in field.errorText()
    field.number_edit.setText("3")
    assert field.isValid() and field.value() == 180


def test_unitless_mode(app):
    field = ValueUnitInput([], 0, 2, decimals=1)
    field.setValue(0.8)
    assert field.unit_combo is None
    assert field.value() == 0.8
    field.number_edit.setText("2.1")
    assert not field.isValid()
    field.number_edit.setText("0.86")
    assert field.value() == 0.9


CONFIG_VALUES = {
    "MAX_TOKENS": "32000", "TEMPERATURE": "0.8", "REQUEST_TIMEOUT": "181",
    "SLIDING_WINDOW_SIZE": "20", "PROCESSING_DELAY": "0", "API_TIMEOUT": "59",
    "HEALTH_CHECK_TIMEOUT": "29",
    "MAX_MESSAGES": "5000", "ANIMATION_INTERVAL": "1251", "POLL_INTERVAL": "7",
}
FIELD_NAMES = {
    "MAX_TOKENS": "max_tokens_input", "TEMPERATURE": "temperature_input",
    "REQUEST_TIMEOUT": "request_timeout_input", "SLIDING_WINDOW_SIZE": "window_size_input",
    "PROCESSING_DELAY": "processing_delay_input", "API_TIMEOUT": "api_timeout_input",
    "HEALTH_CHECK_TIMEOUT": "health_check_timeout_input",
    "MAX_MESSAGES": "max_messages_input", "ANIMATION_INTERVAL": "animation_interval_input",
    "POLL_INTERVAL": "poll_interval_input",
}


@pytest.fixture
def config_page(app, tmp_path, monkeypatch):
    import run_ui
    from src.ui import theme
    path = tmp_path / ".env"
    path.write_text("UI_THEME=sand\n" + "".join(f"{k}={v}\n" for k, v in CONFIG_VALUES.items()), encoding="utf-8")
    theme.set_theme("sand")
    monkeypatch.setenv("UI_THEME", "sand")
    monkeypatch.setattr(run_ui.BackendReloadWorker, "start", lambda self: None)
    monkeypatch.setattr("src.utils.config.reload_config", lambda *_args: None)
    messages = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: messages.append(_args[-1]))
    monkeypatch.setattr(QMessageBox, "critical", lambda *_args: pytest.fail(str(_args[-1])))
    page = run_ui.ConfigPage(env_path=path)
    return page, path, messages


def test_old_sillytavern_keys_are_ignored(config_page):
    page, path, _ = config_page
    with path.open('a', encoding='utf-8') as env:
        env.write('SILLYTAVERN_HOST=old.example\nSILLYTAVERN_PORT=8123\nSILLYTAVERN_TIMEOUT=17\n')
    page.load_config()
    assert not hasattr(page, 'tavern_host_input')
    assert not hasattr(page, 'tavern_port_input')
    assert not hasattr(page, 'tavern_timeout_input')


class StubReply(QObject):
    finished = Signal()

    def __init__(self, status_code, data):
        super().__init__()
        self.status_code = status_code
        self.data = data

    def error(self):
        return QNetworkReply.NoError

    def attribute(self, attribute):
        assert attribute == QNetworkRequest.HttpStatusCodeAttribute
        return self.status_code

    def readAll(self):
        return self.data


class StubNetworkManager:
    def __init__(self, status_code=200, data=b'{"connected": true}'):
        self.status_code = status_code
        self.data = data
        self.urls = []
        self.replies = []

    def get(self, request):
        self.urls.append(request.url().toString())
        reply = StubReply(self.status_code, self.data)
        self.replies.append(reply)
        return reply


@pytest.mark.parametrize('status_code,data,expected', [
    (200, b'{"connected": true}', ("已连接", "运行中")),
    (200, b'{"connected": false}', ("未连接", "运行中")),
    (503, b'', ("未连接", "未运行")),
])
def test_status_display_from_stubbed_http(config_page, monkeypatch, status_code, data, expected):
    import run_ui
    page, _, _ = config_page
    manager = StubNetworkManager(status_code, data)
    page.connection_status_manager = manager
    monkeypatch.setattr(run_ui.requests, 'get', lambda *_args, **_kwargs: pytest.fail('blocking requests.get'))
    page.show()
    assert len(manager.replies) == 1
    manager.replies[0].finished.emit()
    assert (page.plugin_status_label.text(), page.backend_status_label.text()) == expected


def test_connection_status_polls_only_when_visible_and_uses_started_port(config_page, monkeypatch):
    import run_ui
    page, _, _ = config_page
    page.api_server_port = 9876
    page.api_server_port_input.setText('12345')
    manager = StubNetworkManager()
    page.connection_status_manager = manager
    monkeypatch.setattr(run_ui.requests, 'get', lambda *_args, **_kwargs: pytest.fail('blocking requests.get'))
    page.refresh_connection_status()
    page.connection_status_timer.timeout.emit()
    assert manager.urls == []
    assert not page.connection_status_timer.isActive()

    page.show()
    assert manager.urls == ['http://127.0.0.1:9876/system/plugin_status']
    assert page.connection_status_timer.isActive()
    page.refresh_connection_status()
    manager.replies[1].finished.emit()
    assert page.plugin_status_label.text() == '已连接'
    manager.replies[0].status_code = 503
    manager.replies[0].finished.emit()
    assert page.plugin_status_label.text() == '已连接'

    page.hide()
    page.refresh_connection_status()
    page.connection_status_timer.timeout.emit()
    assert len(manager.urls) == 2
    assert not page.connection_status_timer.isActive()


def test_save_refuses_invalid_without_writing(config_page):
    page, path, messages = config_page
    before = path.read_bytes()
    page.request_timeout_input.number_edit.setText("999")
    page.save_config()
    assert path.read_bytes() == before
    assert messages and "请求超时" in messages[-1] and "允许范围" in messages[-1]


def test_load_save_round_trip_for_every_numeric_field(config_page):
    page, path, messages = config_page
    for key, name in FIELD_NAMES.items():
        assert getattr(page, name).value() == float(CONFIG_VALUES[key])
        field = getattr(page, name)
        if field.unit_combo is not None and field.unit_combo.count() > 1:
            field.unit_combo.setCurrentIndex(1)
            assert field.value() == float(CONFIG_VALUES[key])
    page.save_config()
    assert not messages
    after = dotenv_values(path)
    assert {key: after[key] for key in CONFIG_VALUES} == CONFIG_VALUES
