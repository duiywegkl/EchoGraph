from pathlib import Path
from typing import Optional

import requests
from loguru import logger
from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QRadioButton, QButtonGroup, QComboBox, QPushButton, QTextEdit, QStyle,
    QMessageBox, QInputDialog, QApplication
)

from src.ui.widgets.chat_components import ChatDisplayWidget
from src.ui.managers.conversation_manager import ConversationManager


class IntegratedPlayPage(QWidget):
    """
    与 run_ui.bak 行为对齐的对话集成页：
    - 按“名称”切换会话（currentTextChanged → switch_conversation）
    - 本地/酒馆模式切换（/system/tavern_mode, /system/quick_reset）
    - 深色聊天样式 + Ctrl+Enter 发送
    - 会话持久化：data/local_conversations
    """

    message_sent = Signal(str)

    def __init__(self, engine=None, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.engine = engine  # GameEngine实例，与原版逻辑一致
        self.api_base_url = "http://127.0.0.1:9543"
        self.is_test_mode = True
        self.is_connected_to_api = False
        self.switching_modes = False

        # 酒馆状态
        self.current_session_id: str = ""
        self._tavern_session_poll_timer: Optional[QTimer] = None

        # 初始化酒馆管理器（与原版逻辑一致）
        try:
            from src.tavern.tavern_connector import TavernModeManager
            self.tavern_manager = TavernModeManager(self.engine) if self.engine else None
        except Exception as e:
            logger.warning(f"初始化酒馆管理器失败: {e}")
            self.tavern_manager = None

        # 会话存储路径（对齐 bak）
        repo_root = Path(__file__).resolve().parents[3]
        base_path = repo_root / "data" / "local_conversations"
        base_path.mkdir(parents=True, exist_ok=True)
        self.conv_manager = ConversationManager(base_path)

        self._init_ui()
        self._connect_signals()

        # 初次加载对话
        self.conv_manager.load_conversations()

        # 初始为本地测试模式（与原版逻辑一致）
        self.update_status_display("本地测试模式已选择")
        self.is_connected_to_api = True
        self.local_mode_radio.setEnabled(False)
        self.tavern_mode_radio.setEnabled(True)

        # 加载现有对话（与原版逻辑一致）
        self.load_existing_conversations()

    # ---------------- UI -----------------
    def _init_ui(self):
        self.setStyleSheet("IntegratedPlayPage { background-color: #2f3136; }")
        layout = QVBoxLayout(self)

        layout.addWidget(self._create_toolbar())
        layout.addWidget(self._create_conversation_management())

        self.chat_display = ChatDisplayWidget()
        layout.addWidget(self.chat_display)

        layout.addWidget(self._create_input_area())

    def _create_toolbar(self) -> QWidget:
        w = QWidget()
        row = QHBoxLayout(w)
        row.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("测试模式")
        g = QVBoxLayout(group)
        self.mode_button_group = QButtonGroup()
        self.local_mode_radio = QRadioButton("本地测试模式")
        self.tavern_mode_radio = QRadioButton("酒馆模式")
        self.local_mode_radio.setChecked(True)
        self.is_test_mode = True
        self.mode_button_group.addButton(self.local_mode_radio, 0)
        self.mode_button_group.addButton(self.tavern_mode_radio, 1)
        g.addWidget(self.local_mode_radio)
        g.addWidget(self.tavern_mode_radio)

        self.status_label = QLabel("本地测试模式已选择")
        self.status_label.setStyleSheet(
            "QLabel { padding: 5px 10px; border-radius: 3px; background-color: #27ae60; color: white; font-weight: bold; }"
        )

        row.addWidget(group)
        row.addStretch()
        row.addWidget(self.status_label)
        return w

    def _create_conversation_management(self) -> QWidget:
        group = QGroupBox("对话管理")
        row = QHBoxLayout(group)

        self.conversation_combo = QComboBox()
        self.conversation_combo.setMinimumWidth(220)

        self.new_conv_btn = QPushButton("新建对话")
        self.new_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        self.rename_conv_btn = QPushButton("重命名")
        self.rename_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        self.delete_conv_btn = QPushButton("删除对话")
        self.delete_conv_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))

        row.addWidget(QLabel("当前对话："))
        row.addWidget(self.conversation_combo)
        row.addWidget(self.new_conv_btn)
        row.addWidget(self.rename_conv_btn)
        row.addWidget(self.delete_conv_btn)
        row.addStretch()
        return group

    def _create_input_area(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)

        self.input_text = QTextEdit()
        self.input_text.setMaximumHeight(100)
        self.input_text.setPlaceholderText("输入你的消息...")

        buttons = QHBoxLayout()
        self.regenerate_btn = QPushButton("重新生成")
        self.regenerate_btn.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.delete_mode_btn = QPushButton("删除模式")
        self.delete_mode_btn.setCheckable(True)
        self.delete_mode_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self.clear_btn = QPushButton("清空对话")
        self.clear_btn.setIcon(self.style().standardIcon(QStyle.SP_DialogResetButton))
        self.send_btn = QPushButton("发送")
        self.send_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))

        buttons.addWidget(self.regenerate_btn)
        buttons.addWidget(self.delete_mode_btn)
        buttons.addStretch()
        buttons.addWidget(self.clear_btn)
        buttons.addWidget(self.send_btn)

        v.addWidget(self.input_text)
        v.addLayout(buttons)
        return w

    # -------------- 信号与交互 ----------------
    def _connect_signals(self):
        self.mode_button_group.idClicked.connect(self.on_mode_change)
        self.new_conv_btn.clicked.connect(self._on_new_conversation)
        self.delete_conv_btn.clicked.connect(self._on_delete_conversation)
        self.rename_conv_btn.clicked.connect(self._on_rename_conversation)
        # 原版：按名称切换
        self.conversation_combo.currentTextChanged.connect(self.switch_conversation)

        self.send_btn.clicked.connect(self.send_message)
        self.clear_btn.clicked.connect(self.clear_conversation)
        self.regenerate_btn.clicked.connect(self._on_regenerate_last)
        self.delete_mode_btn.toggled.connect(self._on_toggle_delete_mode)

        # Ctrl+Enter 发送
        self.input_text.installEventFilter(self)

        self.conv_manager.conversation_list_updated.connect(self.update_conversation_combo)
        self.conv_manager.conversation_changed.connect(self.load_conversation)

    def eventFilter(self, obj, event):  # noqa: N802
        if obj == self.input_text and event.type() == event.Type.KeyPress:
            if event.key() == Qt.Key_Return and event.modifiers() == Qt.ControlModifier:
                self.send_message()
                return True
        return super().eventFilter(obj, event)

    # -------------- 模式切换（对齐原版语义） --------------
    def on_mode_change(self, mode_id: int):
        if self.switching_modes:
            return
        self.switching_modes = True
        try:
            self.is_test_mode = (mode_id == 0)
            if self.is_test_mode:
                self._switch_to_local_mode()
            else:
                self._switch_to_tavern_mode()
        finally:
            self.switching_modes = False

    def _switch_to_local_mode(self):
        self._stop_tavern_session_polling()
        self._set_api_mode(False)
        # 请求后端快速清理（与 bak 一致）
        try:
            requests.get(f"{self.api_base_url}/system/quick_reset", timeout=5)
        except Exception:
            pass

        self.local_mode_radio.setEnabled(False)
        self.tavern_mode_radio.setEnabled(True)
        self.enable_chat_interface(True)
        self.update_status_display("✅ 本地测试模式已启用")

        # 通知图谱页退出酒馆模式
        try:
            mw = self.window()
            if mw and hasattr(mw, 'graph_page'):
                mw.graph_page.exit_tavern_mode()
        except Exception:
            pass

    def _switch_to_tavern_mode(self):
        self._set_api_mode(True)
        self.local_mode_radio.setEnabled(True)
        self.tavern_mode_radio.setEnabled(False)
        self.enable_chat_interface(False)
        self.update_status_display("✅ 酒馆模式已启用（等待SillyTavern角色提交）")
        self._start_tavern_session_polling()

    def _set_api_mode(self, tavern_active: bool):
        try:
            requests.post(f"{self.api_base_url}/system/tavern_mode", json={"active": tavern_active}, timeout=5)
        except Exception:
            pass

    # -------------- 酒馆会话轮询（语义对齐） --------------
    def _start_tavern_session_polling(self):
        self._stop_tavern_session_polling()
        self._tavern_session_poll_timer = QTimer(self)
        self._tavern_session_poll_timer.setInterval(3000)

        def tick():
            try:
                r = requests.get(f"{self.api_base_url}/tavern/current_session", timeout=8)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("has_session") and data.get("session_id"):
                        sid = data["session_id"]
                        char_name = data.get('character_name', 'Unknown')
                        graph_nodes = data.get('graph_nodes', 0)

                        # 检查会话ID变化
                        session_changed = getattr(self, 'current_session_id', None) != sid

                        # 检查图谱节点数量变化（用于检测重新初始化）
                        last_nodes = getattr(self, '_last_graph_nodes', -1)
                        nodes_changed = last_nodes != graph_nodes

                        # 检查角色名称变化
                        last_char = getattr(self, '_last_character_name', '')
                        char_changed = last_char != char_name

                        if session_changed or nodes_changed or char_changed:
                            logger.info(f"🔄 检测到变化: session_changed={session_changed}, "
                                      f"nodes_changed={nodes_changed} ({last_nodes}->{graph_nodes}), "
                                      f"char_changed={char_changed} ({last_char}->{char_name})")

                            self.current_session_id = sid
                            self._last_graph_nodes = graph_nodes
                            self._last_character_name = char_name

                            self.update_status_display(f"🍺 已连接到角色: {char_name} (节点: {graph_nodes})")
                            try:
                                mw = self.window()
                                if mw and hasattr(mw, 'graph_page'):
                                    mw.graph_page.enter_tavern_mode(sid)
                            except Exception:
                                pass
            except Exception:
                pass

        self._tavern_session_poll_timer.timeout.connect(tick)
        self._tavern_session_poll_timer.start()

    def _stop_tavern_session_polling(self):
        t = getattr(self, '_tavern_session_poll_timer', None)
        if t:
            t.stop()
            t.deleteLater()
            self._tavern_session_poll_timer = None

    # -------------- 聊天/会话操作 --------------
    def enable_chat_interface(self, enabled: bool):
        self.input_text.setEnabled(enabled)
        self.input_text.setPlaceholderText(
            "酒馆模式下，请在SillyTavern中进行对话" if not enabled else "输入你的消息..."
        )
        for btn in [
            self.send_btn, self.clear_btn, self.new_conv_btn, self.delete_conv_btn,
            self.rename_conv_btn, self.regenerate_btn, self.delete_mode_btn
        ]:
            btn.setEnabled(enabled)

    def update_status_display(self, text: str):
        self.status_label.setText(text)

    def send_message(self):
        text = self.input_text.toPlainText().strip()
        if not text:
            return
        self.chat_display.add_message(text, is_user=True)
        if self.conv_manager and self.conv_manager.get_current_conversation():
            self.conv_manager.add_message({"role": "user", "content": text})
        self.message_sent.emit(text)
        self.input_text.clear()

    def clear_conversation(self):
        if QMessageBox.question(
            self, "确认清空", "确定要清空当前对话吗？这也将清空知识图谱。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        self.chat_display.clear_messages()
        if self.conv_manager:
            self.conv_manager.clear_current_conversation()
        try:
            mw = self.window()
            if mw and hasattr(mw, 'memory') and mw.memory:
                mw.memory.clear_all()
            if mw and hasattr(mw, 'graph_page'):
                mw.graph_page.refresh_graph()
        except Exception:
            pass

    def add_system_message(self, message: str):
        self.chat_display.add_message(message, is_user=False, color="#4f545c")

    def add_assistant_message(self, message: str):
        self.chat_display.add_message(message, is_user=False)

    def cleanup(self):
        self._stop_tavern_session_polling()
        if self.conv_manager:
            self.conv_manager.deleteLater()
            self.conv_manager = None

    # --- 会话 CRUD ---
    def _on_new_conversation(self):
        name, ok = QInputDialog.getText(
            self, "新建对话", "请输入对话名称：",
            text=f"新对话 {len(self.conv_manager.conversations) + 1}"
        )
        if not ok:
            return
        try:
            self.conv_manager.create_conversation(name.strip() or None)
        except Exception as e:
            logger.error(f"新建对话失败: {e}")

    def _on_delete_conversation(self):
        name = self.conversation_combo.currentText()
        if not name:
            return
        conv_id = None
        for cid, conv in (self.conv_manager.conversations or {}).items():
            if conv.get('name') == name:
                conv_id = cid
                break
        if not conv_id:
            return
        if QMessageBox.question(
            self, "删除对话", f"确定要删除对话：{name}？",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        ) != QMessageBox.Yes:
            return
        if self.conv_manager.delete_conversation(conv_id):
            try:
                mw = self.window()
                if mw and hasattr(mw, 'memory') and mw.memory:
                    mw.memory.clear_all()
                if mw and hasattr(mw, 'graph_page'):
                    mw.graph_page.refresh_graph()
            except Exception:
                pass

    def _on_rename_conversation(self):
        old_name = self.conversation_combo.currentText()
        if not old_name:
            return
        conv_id = None
        for cid, conv in (self.conv_manager.conversations or {}).items():
            if conv.get('name') == old_name:
                conv_id = cid
                break
        if not conv_id:
            return
        new_name, ok = QInputDialog.getText(self, "重命名对话", "新的对话名称：", text=old_name)
        if not ok or not new_name.strip():
            return
        self.conv_manager.rename_conversation(conv_id, new_name.strip())

    # --- 列表/加载（与原版命名一致） ---
    def update_conversation_combo(self, conversations: list):
        try:
            try:
                self.conversation_combo.currentTextChanged.disconnect()
            except Exception:
                pass
            self.conversation_combo.clear()
            for conv in conversations:
                self.conversation_combo.addItem(conv.get('name', '未命名'))
            current_id = getattr(self.conv_manager, 'current_conversation_id', None)
            if current_id:
                for i, conv in enumerate(conversations):
                    if conv.get('id') == current_id:
                        self.conversation_combo.setCurrentIndex(i)
                        break
        finally:
            self.conversation_combo.currentTextChanged.connect(self.switch_conversation)

    def switch_conversation(self, name: str):
        if not self.conv_manager or not name:
            return
        target_id = None
        for cid, conv in (self.conv_manager.conversations or {}).items():
            if conv.get('name') == name:
                target_id = cid
                break
        if target_id:
            self.conv_manager.switch_conversation(target_id)

    def load_conversation(self, conv_id: str):
        try:
            self.chat_display.clear_messages()
            conv = self.conv_manager.get_current_conversation()
            if not conv:
                return
            for msg in conv.get('messages', []):
                role = msg.get('role') or msg.get('sender') or ''
                content = msg.get('content') or msg.get('message') or ''
                if not content:
                    continue
                if role == 'system':
                    self.add_system_message(content)
                elif role == 'user':
                    self.chat_display.add_message(content, is_user=True)
                else:
                    self.chat_display.add_message(content, is_user=False)
        except Exception as e:
            logger.warning(f"加载对话失败: {e}")

    # -------- 与 bak 同名包装（保持外部接口） --------
    def create_new_conversation(self):
        return self._on_new_conversation()

    def delete_current_conversation(self):
        return self._on_delete_conversation()

    def rename_current_conversation(self):
        return self._on_rename_conversation()

    def regenerate_last_response(self):
        return self._on_regenerate_last()

    def toggle_delete_mode(self, enabled: bool):
        return self._on_toggle_delete_mode(enabled)

    def load_existing_conversations(self):
        """加载现有对话到下拉框（与原版逻辑一致）"""
        try:
            logger.debug("📥 [UI] 开始加载现有对话...")

            # 触发对话管理器加载对话
            self.conv_manager.load_conversations()

            # 获取排序后的对话列表
            conversations = list(self.conv_manager.conversations.values())
            logger.debug(f"📋 [UI] 找到 {len(conversations)} 个对话")

            if conversations:
                # 按最后修改时间排序
                sorted_conversations = sorted(
                    conversations,
                    key=lambda x: x.get('last_modified', 0),
                    reverse=True
                )

                for i, conv in enumerate(sorted_conversations):
                    logger.debug(f"📄 [UI] 对话{i+1}: {conv['name']} (ID: {conv['id']})")

                self.update_conversation_combo(sorted_conversations)

                # 如果有对话，自动选择第一个并加载其内容
                if sorted_conversations:
                    first_conv = sorted_conversations[0]
                    logger.debug(f"🎯 [UI] 自动选择第一个对话: {first_conv['name']}")

                    self.conv_manager.current_conversation_id = first_conv['id']
                    self.load_conversation(first_conv['id'])
                    logger.debug(f"✅ [UI] 自动加载对话: {first_conv['name']}")
            else:
                logger.debug("📭 [UI] 没有找到现有对话")
        except Exception as e:
            logger.error(f"❌ [UI] 加载现有对话失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")

    # 其它
    def _on_regenerate_last(self):
        removed = getattr(self.chat_display, "remove_last_ai_message", lambda: False)()
        try:
            conv = self.conv_manager.get_current_conversation() if self.conv_manager else None
            if conv and conv.get('messages'):
                for i in range(len(conv['messages']) - 1, -1, -1):
                    msg = conv['messages'][i]
                    role = (msg.get('role') or msg.get('sender') or '').lower()
                    if role in ('assistant', 'ai'):
                        conv['messages'].pop(i)
                        if hasattr(self.conv_manager, '_save_conversation'):
                            self.conv_manager._save_conversation(conv)  # noqa: SLF001
                        break
        except Exception as e:
            logger.warning(f"同步删除最后AI消息失败: {e}")
        if removed:
            logger.info("[UI] 重新生成：已删除最后一条AI消息")

    def _on_toggle_delete_mode(self, enabled: bool):
        if hasattr(self.chat_display, "set_delete_mode"):
            self.chat_display.set_delete_mode(enabled)

    # ========== 酒馆模式功能 ==========

    def enter_tavern_mode(self):
        """进入酒馆模式的完整流程 - 使用多线程避免UI卡顿"""
        logger.info("🍺 ========== 开始进入酒馆模式流程（多线程模式）==========")

        try:
            # 立即更新UI状态，告知用户开始初始化
            self.update_status_display("🍺 正在初始化酒馆模式...")
            from PySide6.QtWidgets import QApplication
            QApplication.processEvents()

            # 禁用相关UI控件，防止重复操作
            if hasattr(self, 'switch_to_tavern_btn'):
                self.switch_to_tavern_btn.setEnabled(False)
                self.switch_to_tavern_btn.setText("正在初始化...")

            logger.info("📋 步骤1: 准备多线程初始化...")

            # 获取主窗口和相关组件
            from src.ui.windows.main_window import MainWindow
            main_window = None
            for widget in QApplication.topLevelWidgets():
                if isinstance(widget, MainWindow):
                    main_window = widget
                    break
            if not main_window:
                logger.error("❌ 无法获取主窗口实例")
                self.update_status_display("❌ 初始化失败：无法获取主窗口")
                return

            logger.info("📋 步骤2: 获取酒馆连接配置...")
            repo_root = Path(__file__).resolve().parents[3]
            env_path = repo_root / '.env'
            from dotenv import dotenv_values
            config_data = dotenv_values(env_path) if env_path.exists() else {}
            host = config_data.get("SILLYTAVERN_HOST", "localhost")
            port = int(config_data.get("SILLYTAVERN_PORT", "8000"))

            logger.info(f"🔧 酒馆连接配置:")
            logger.info(f"  - 主机: {host}")
            logger.info(f"  - 端口: {port}")

            import os
            tavern_timeout = int(os.getenv("SILLYTAVERN_TIMEOUT", "10"))

            logger.info("📋 步骤3: 启动后台初始化线程...")

            # 创建工作线程
            from src.ui.workers.tavern_init_worker import TavernInitWorker
            self.tavern_init_worker = TavernInitWorker(self.api_base_url)

            # 连接信号槽
            self.tavern_init_worker.connection_status_changed.connect(self.on_tavern_init_progress)
            self.tavern_init_worker.initialization_completed.connect(self.on_tavern_init_completed)
            self.tavern_init_worker.error_occurred.connect(self.on_tavern_init_error)
            self.tavern_init_worker.finished.connect(self.on_tavern_init_finished)

            # 启动线程
            self.tavern_init_worker.start()

            logger.info("✅ 酒馆模式初始化线程已启动")

        except Exception as e:
            logger.error(f"❌ 进入酒馆模式失败: {e}")
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            self.update_status_display(f"❌ 初始化失败: {str(e)}")

            # 恢复UI状态
            if hasattr(self, 'switch_to_tavern_btn'):
                self.switch_to_tavern_btn.setEnabled(True)
                self.switch_to_tavern_btn.setText("切换到酒馆模式")

    def on_tavern_init_progress(self, is_connected: bool, message: str):
        """酒馆初始化进度更新"""
        logger.info(f"🔄 酒馆初始化进度: {message}")
        self.update_status_display(message)

    def on_tavern_init_completed(self, result: dict):
        """酒馆初始化完成"""
        try:
            logger.info("🎉 酒馆模式初始化完成！")
            logger.info(f"结果: {result}")

            character = result.get("character", "未知角色")
            session_id = result.get("session_id", "")
            nodes_created = result.get("nodes_created", 0)
            reused_existing = result.get("reused_existing", False)

            if reused_existing:
                self.update_status_display(f"✅ 已连接到现有会话: {character} (节点: {nodes_created})")
            else:
                self.update_status_display(f"✅ 酒馆模式已激活: {character} (新建节点: {nodes_created})")

            # 更新当前会话ID
            self.current_session_id = session_id

            # 切换到酒馆模式
            self.is_test_mode = False
            self.is_connected_to_api = True

            # 更新UI状态
            if hasattr(self, 'local_mode_radio'):
                self.local_mode_radio.setEnabled(True)
            if hasattr(self, 'tavern_mode_radio'):
                self.tavern_mode_radio.setChecked(True)
                self.tavern_mode_radio.setEnabled(False)

            # 恢复按钮状态
            if hasattr(self, 'switch_to_tavern_btn'):
                self.switch_to_tavern_btn.setEnabled(True)
                self.switch_to_tavern_btn.setText("切换到酒馆模式")

            # 通知图谱页面进入酒馆模式
            try:
                from src.ui.windows.main_window import MainWindow
                for widget in QApplication.topLevelWidgets():
                    if isinstance(widget, MainWindow):
                        if hasattr(widget, 'graph_page'):
                            widget.graph_page.enter_tavern_mode(session_id)
                        break
            except Exception as e:
                logger.warning(f"通知图谱页面进入酒馆模式失败: {e}")

            logger.info("🍺 酒馆模式切换完成")

        except Exception as e:
            logger.error(f"处理酒馆初始化完成事件失败: {e}")
            self.update_status_display(f"❌ 处理完成事件失败: {str(e)}")

    def on_tavern_init_error(self, error_message: str):
        """酒馆初始化错误"""
        logger.error(f"❌ 酒馆初始化失败: {error_message}")
        self.update_status_display(f"❌ 初始化失败: {error_message}")

        # 恢复UI状态
        if hasattr(self, 'switch_to_tavern_btn'):
            self.switch_to_tavern_btn.setEnabled(True)
            self.switch_to_tavern_btn.setText("切换到酒馆模式")

        # 显示错误对话框
        QMessageBox.critical(self, "酒馆模式初始化失败", f"无法初始化酒馆模式：\n\n{error_message}")

    def on_tavern_init_finished(self):
        """酒馆初始化线程结束"""
        logger.info("🧵 酒馆初始化线程已结束")
        if hasattr(self, 'tavern_init_worker'):
            self.tavern_init_worker = None

    def exit_tavern_mode(self):
        """退出酒馆模式，切换回本地模式"""
        try:
            logger.info("🏠 退出酒馆模式，切换回本地模式")

            # 更新状态
            self.is_test_mode = True
            self.is_connected_to_api = True
            self.current_session_id = ""

            # 更新UI状态
            if hasattr(self, 'local_mode_radio'):
                self.local_mode_radio.setChecked(True)
                self.local_mode_radio.setEnabled(False)
            if hasattr(self, 'tavern_mode_radio'):
                self.tavern_mode_radio.setEnabled(True)

            # 通知图谱页面退出酒馆模式
            try:
                from src.ui.windows.main_window import MainWindow
                for widget in QApplication.topLevelWidgets():
                    if isinstance(widget, MainWindow):
                        if hasattr(widget, 'graph_page'):
                            widget.graph_page.exit_tavern_mode()
                        break
            except Exception as e:
                logger.warning(f"通知图谱页面退出酒馆模式失败: {e}")

            self.update_status_display("✅ 已切换回本地测试模式")
            logger.info("🏠 本地模式切换完成")

        except Exception as e:
            logger.error(f"退出酒馆模式失败: {e}")
            self.update_status_display(f"❌ 切换失败: {str(e)}")

    def cleanup(self):
        """清理资源"""
        try:
            # 停止定时器
            if self._tavern_session_poll_timer:
                self._tavern_session_poll_timer.stop()
                self._tavern_session_poll_timer = None

            # 停止酒馆初始化工作线程
            if hasattr(self, 'tavern_init_worker') and self.tavern_init_worker:
                self.tavern_init_worker.stop()
                self.tavern_init_worker = None

            logger.info("[UI] IntegratedPlayPage 资源清理完成")
        except Exception as e:
            logger.error(f"[UI] 清理资源失败: {e}")

