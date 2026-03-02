"""
ConfigPage - 系统配置页面（布局和分组严格对齐 run_ui.bak）
"""
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QGroupBox, QFormLayout, QLineEdit,
    QCheckBox, QSpinBox, QDoubleSpinBox, QPushButton, QLabel, QMessageBox, QComboBox,
    QApplication
)
from loguru import logger

try:
    from dotenv import dotenv_values, set_key
except Exception:
    dotenv_values = lambda *_args, **_kwargs: {}  # type: ignore
    def set_key(*_a, **_k):  # type: ignore
        logger.warning("dotenv not available; skipping save")


class ConfigPage(QWidget):
    """系统配置页面（只做模块化包装，不改变原布局/交互）"""

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setObjectName("configPage")
        # .env 放在项目根目录（与原版一致）
        self.env_path = Path(".env").resolve()
        self._init_ui()
        self.load_config()

    def load_config_styles(self):
        """从 assets/css/graph.css 提取 QSS_CONFIG 片段并应用到配置页"""
        try:
            repo_root = Path(__file__).resolve().parents[3]
            css_path = repo_root / "assets" / "css" / "graph.css"
            if css_path.exists():
                content = css_path.read_text(encoding="utf-8")
                start_marker = "/* QSS_CONFIG_START */"
                end_marker = "/* QSS_CONFIG_END */"
                start = content.find(start_marker)
                end = content.find(end_marker)
                if start != -1 and end != -1 and end > start:
                    qss = content[start + len(start_marker): end].strip()
                    self.setStyleSheet(qss)
                else:
                    logger.warning("未找到配置页面QSS片段，使用内置最小样式")
                    self.setStyleSheet(
                        "#configPage QSpinBox::up-button, #configPage QDoubleSpinBox::up-button, "
                        "#configPage QSpinBox::down-button, #configPage QDoubleSpinBox::down-button { "
                        "width:0px; height:0px; border:none; background:transparent; } "
                        "#configPage QLabel { background-color: transparent; }"
                    )
            else:
                logger.warning(f"CSS文件不存在: {css_path}")
        except Exception as e:
            logger.error(f"加载CSS样式失败: {e}")

    def _init_ui(self):
        # 加载配置页的深色QSS样式（与原版一致）
        self.load_config_styles()
        scroll_area = QScrollArea(); scroll_area.setWidgetResizable(True)
        main_widget = QWidget(); main_layout = QVBoxLayout(main_widget)

        # ========== LLM 模型配置 ==========
        llm_group = QGroupBox("LLM模型配置")
        llm_form = QFormLayout(llm_group)
        self.api_base_url_input = QLineEdit()
        self.api_key_input = QLineEdit(); self.api_key_input.setEchoMode(QLineEdit.Password)
        self.model_input = QLineEdit()
        self.stream_checkbox = QCheckBox("启用流式输出")
        self.embedding_review_checkbox = QCheckBox("启用Embedding向量复核（付费）")
        self.embedding_review_checkbox.setToolTip("仅勾选后才会调用Embedding接口进行语义复核，可能产生额外费用。")
        self.max_tokens_input = QSpinBox(); self.max_tokens_input.setRange(100, 32000); self.max_tokens_input.setSuffix(" tokens")
        self.temperature_input = QDoubleSpinBox(); self.temperature_input.setRange(0.0, 2.0); self.temperature_input.setSingleStep(0.1); self.temperature_input.setDecimals(1)
        self.request_timeout_input = QSpinBox(); self.request_timeout_input.setRange(30, 600); self.request_timeout_input.setSuffix(" 秒")
        llm_form.addRow("API 基址:", self.api_base_url_input)
        llm_form.addRow("API Key:", self.api_key_input)
        llm_form.addRow("默认模型:", self.model_input)
        llm_form.addRow("最大Token:", self.max_tokens_input)
        llm_form.addRow("温度(Temperature):", self.temperature_input)
        llm_form.addRow("请求超时:", self.request_timeout_input)
        llm_form.addRow("", self.stream_checkbox)
        llm_form.addRow("", self.embedding_review_checkbox)

        # ========== 滑动窗口配置 ==========
        window_group = QGroupBox("滑动窗口配置")
        window_form = QFormLayout(window_group)
        self.window_size_input = QSpinBox(); self.window_size_input.setRange(2, 20); self.window_size_input.setSuffix(" 轮")
        self.processing_delay_input = QSpinBox(); self.processing_delay_input.setRange(0, 10); self.processing_delay_input.setSuffix(" 秒")
        self.enable_enhanced_agent_checkbox = QCheckBox("启用增强代理")
        self.enable_conflict_resolution_checkbox = QCheckBox("启用冲突协调")
        window_form.addRow("窗口大小:", self.window_size_input)
        window_form.addRow("处理延迟:", self.processing_delay_input)
        window_form.addRow("", self.enable_enhanced_agent_checkbox)
        window_form.addRow("", self.enable_conflict_resolution_checkbox)

        # ========== 服务器配置 ==========
        server_group = QGroupBox("服务器配置")
        server_form = QFormLayout(server_group)
        self.api_server_port_input = QLineEdit(); self.api_server_port_input.setValidator(QIntValidator(1024, 65535, self))
        self.api_timeout_input = QSpinBox(); self.api_timeout_input.setRange(5, 60); self.api_timeout_input.setSuffix(" 秒")
        self.health_check_timeout_input = QSpinBox(); self.health_check_timeout_input.setRange(3, 30); self.health_check_timeout_input.setSuffix(" 秒")
        server_form.addRow("API 服务端口:", self.api_server_port_input)
        server_form.addRow("API 调用超时:", self.api_timeout_input)
        server_form.addRow("健康检查超时:", self.health_check_timeout_input)

        # ========== SillyTavern 连接配置 ==========
        tavern_group = QGroupBox("SillyTavern 连接配置")
        tavern_form = QFormLayout(tavern_group)
        self.tavern_host_input = QLineEdit()
        self.tavern_port_input = QLineEdit(); self.tavern_port_input.setValidator(QIntValidator(1024, 65535, self))
        self.tavern_timeout_input = QSpinBox(); self.tavern_timeout_input.setRange(3, 30); self.tavern_timeout_input.setSuffix(" 秒")
        self.test_tavern_btn = QPushButton("测试连接")
        self.tavern_status_label = QLabel("未测试")
        tavern_form.addRow("主机:", self.tavern_host_input)
        tavern_form.addRow("端口:", self.tavern_port_input)
        tavern_form.addRow("超时:", self.tavern_timeout_input)
        tavern_form.addRow("状态:", self.tavern_status_label)
        tavern_form.addRow("", self.test_tavern_btn)

        # ========== 界面配置 ==========
        ui_group = QGroupBox("界面配置")
        ui_form = QFormLayout(ui_group)
        self.max_messages_input = QSpinBox(); self.max_messages_input.setRange(100, 5000); self.max_messages_input.setSuffix(" 条")
        self.animation_interval_input = QSpinBox(); self.animation_interval_input.setRange(100, 2000); self.animation_interval_input.setSuffix(" ms")
        self.poll_interval_input = QSpinBox(); self.poll_interval_input.setRange(1, 10); self.poll_interval_input.setSuffix(" 秒")
        ui_form.addRow("消息上限:", self.max_messages_input)
        ui_form.addRow("动画间隔:", self.animation_interval_input)
        ui_form.addRow("轮询间隔:", self.poll_interval_input)

        # ========== 系统配置 ==========
        system_group = QGroupBox("系统配置")
        system_form = QFormLayout(system_group)
        self.log_level_combo = QComboBox(); self.log_level_combo.addItems(["TRACE","DEBUG","INFO","WARNING","ERROR"])
        system_form.addRow("日志等级:", self.log_level_combo)

        # 保存按钮
        self.save_button = QPushButton("保存配置")

        # 组装
        main_layout.addWidget(llm_group)
        main_layout.addWidget(window_group)
        main_layout.addWidget(server_group)
        main_layout.addWidget(tavern_group)
        main_layout.addWidget(ui_group)
        main_layout.addWidget(system_group)
        main_layout.addWidget(self.save_button)
        main_layout.addStretch()

        scroll_area.setWidget(main_widget)
        root = QVBoxLayout(self)
        root.addWidget(scroll_area)

        # 连接信号
        self.save_button.clicked.connect(self.save_config)
        self.test_tavern_btn.clicked.connect(self.test_tavern_connection)

    # ---------------- 读写 .env ----------------
    def load_config(self):
        try:
            if not self.env_path.exists():
                self.env_path.touch()
            config = dotenv_values(self.env_path)
        except Exception:
            config = {}

        # LLM
        self.api_base_url_input.setText(config.get("OPENAI_API_BASE_URL", ""))
        self.api_key_input.setText(config.get("OPENAI_API_KEY", ""))
        self.model_input.setText(config.get("DEFAULT_MODEL", ""))
        self.max_tokens_input.setValue(int(config.get("MAX_TOKENS", "4000")))
        self.temperature_input.setValue(float(config.get("TEMPERATURE", "0.8")))
        self.request_timeout_input.setValue(int(config.get("REQUEST_TIMEOUT", "180")))
        self.stream_checkbox.setChecked(config.get("LLM_STREAM_OUTPUT", "false").lower() in ("true","1","t","yes"))
        self.embedding_review_checkbox.setChecked(config.get("ENABLE_EMBEDDING_REVIEW", "false").lower() in ("true","1","t","yes"))

        # 滑动窗口
        self.window_size_input.setValue(int(config.get("SLIDING_WINDOW_SIZE", "4")))
        self.processing_delay_input.setValue(int(config.get("PROCESSING_DELAY", "1")))
        self.enable_enhanced_agent_checkbox.setChecked(config.get("ENHANCED_AGENT", "true").lower() in ("true","1","t","yes"))
        self.enable_conflict_resolution_checkbox.setChecked(config.get("CONFLICT_RESOLUTION", "true").lower() in ("true","1","t","yes"))

        # 服务器
        self.api_server_port_input.setText(config.get("API_SERVER_PORT", "9543"))
        self.api_timeout_input.setValue(int(config.get("API_TIMEOUT", "15")))
        self.health_check_timeout_input.setValue(int(config.get("HEALTH_CHECK_TIMEOUT", "10")))

        # Tavern
        self.tavern_host_input.setText(config.get("SILLYTAVERN_HOST", "localhost"))
        self.tavern_port_input.setText(config.get("SILLYTAVERN_PORT", "8000"))
        self.tavern_timeout_input.setValue(int(config.get("SILLYTAVERN_TIMEOUT", "10")))

        # UI
        self.max_messages_input.setValue(int(config.get("MAX_MESSAGES", "1000")))
        self.animation_interval_input.setValue(int(config.get("ANIMATION_INTERVAL", "500")))
        self.poll_interval_input.setValue(int(config.get("POLL_INTERVAL", "3")))

        # 系统
        level = config.get("LOG_LEVEL", "INFO").upper()
        idx = max(0, self.log_level_combo.findText(level))
        self.log_level_combo.setCurrentIndex(idx)

    def save_config(self):
        try:
            set_key(self.env_path, "OPENAI_API_BASE_URL", self.api_base_url_input.text())
            set_key(self.env_path, "OPENAI_API_KEY", self.api_key_input.text())
            set_key(self.env_path, "DEFAULT_MODEL", self.model_input.text())
            set_key(self.env_path, "LLM_STREAM_OUTPUT", str(self.stream_checkbox.isChecked()).lower())
            set_key(self.env_path, "ENABLE_EMBEDDING_REVIEW", str(self.embedding_review_checkbox.isChecked()).lower())
            set_key(self.env_path, "MAX_TOKENS", str(self.max_tokens_input.value()))
            set_key(self.env_path, "TEMPERATURE", str(self.temperature_input.value()))
            set_key(self.env_path, "REQUEST_TIMEOUT", str(self.request_timeout_input.value()))
            set_key(self.env_path, "SLIDING_WINDOW_SIZE", str(self.window_size_input.value()))
            set_key(self.env_path, "PROCESSING_DELAY", str(self.processing_delay_input.value()))
            set_key(self.env_path, "ENHANCED_AGENT", str(self.enable_enhanced_agent_checkbox.isChecked()).lower())
            set_key(self.env_path, "CONFLICT_RESOLUTION", str(self.enable_conflict_resolution_checkbox.isChecked()).lower())
            set_key(self.env_path, "API_SERVER_PORT", self.api_server_port_input.text())
            set_key(self.env_path, "API_TIMEOUT", str(self.api_timeout_input.value()))
            set_key(self.env_path, "HEALTH_CHECK_TIMEOUT", str(self.health_check_timeout_input.value()))
            set_key(self.env_path, "SILLYTAVERN_HOST", self.tavern_host_input.text())
            set_key(self.env_path, "SILLYTAVERN_PORT", self.tavern_port_input.text())
            set_key(self.env_path, "SILLYTAVERN_TIMEOUT", str(self.tavern_timeout_input.value()))
            set_key(self.env_path, "MAX_MESSAGES", str(self.max_messages_input.value()))
            set_key(self.env_path, "ANIMATION_INTERVAL", str(self.animation_interval_input.value()))
            set_key(self.env_path, "POLL_INTERVAL", str(self.poll_interval_input.value()))
            set_key(self.env_path, "LOG_LEVEL", self.log_level_combo.currentText())
            QMessageBox.information(self, "成功", "配置已保存。")
        except Exception as e:
            QMessageBox.critical(self, "失败", f"保存失败: {e}")

    def test_tavern_connection(self):
        """测试酒馆连接"""
        try:
            host = self.tavern_host_input.text().strip() or "localhost"
            port = self.tavern_port_input.text().strip() or "8000"

            self.tavern_status_label.setText("测试中...")
            self.tavern_status_label.setStyleSheet("color: #f39c12;")
            self.test_tavern_btn.setEnabled(False)
            QApplication.processEvents()

            # 创建临时连接器进行测试
            from src.tavern.tavern_connector import SillyTavernConnector, TavernConfig

            timeout = self.tavern_timeout_input.value()
            config = TavernConfig(host=host, port=int(port), timeout=timeout)
            connector = SillyTavernConnector(config)

            result = connector.test_connection()

            if result["status"] == "connected":
                self.tavern_status_label.setText("✅ 连接成功")
                self.tavern_status_label.setStyleSheet("color: #27ae60;")

                version = result.get("version", {})
                QMessageBox.information(
                    self,
                    "连接成功",
                    f"成功连接到SillyTavern！\n\n"
                    f"地址: {result['url']}\n"
                    f"版本: {version.get('version', '未知')}"
                )
            else:
                self.tavern_status_label.setText("❌ 连接失败")
                self.tavern_status_label.setStyleSheet("color: #e74c3c;")

                QMessageBox.warning(
                    self,
                    "连接失败",
                    f"无法连接到SillyTavern:\n\n{result['error']}\n\n"
                    f"请确保SillyTavern正在运行并检查地址和端口是否正确。"
                )

            connector.disconnect()

        except ValueError as e:
            self.tavern_status_label.setText("❌ 配置错误")
            self.tavern_status_label.setStyleSheet("color: #e74c3c;")
            QMessageBox.warning(self, "配置错误", f"端口必须是数字：{e}")

        except Exception as e:
            self.tavern_status_label.setText("❌ 测试异常")
            self.tavern_status_label.setStyleSheet("color: #e74c3c;")
            QMessageBox.critical(self, "测试异常", f"测试连接时发生异常：{e}")

        finally:
            self.test_tavern_btn.setEnabled(True)

