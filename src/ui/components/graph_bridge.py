"""
图谱桥接组件
从原始run_ui.bak移植的GraphBridge实现
负责WebSocket通信和图谱更新
"""
import json
import time
import asyncio
import websockets
from typing import Dict, Any, Optional
from PySide6.QtCore import QObject, Signal, QTimer
from loguru import logger


class GraphBridge(QObject):
    """图谱桥接组件

    负责与API服务器的WebSocket通信
    从原始run_ui.bak完整移植，保持原有逻辑
    """

    # 信号定义
    connection_status_changed = Signal(bool, str)  # 连接状态, 消息
    session_updated = Signal(dict)  # 会话更新
    graph_updated = Signal(dict)  # 图谱更新
    message_received = Signal(dict)  # 收到消息
    error_occurred = Signal(str)  # 错误发生

    def __init__(self, api_base_url: str = "http://127.0.0.1:9543"):
        super().__init__()
        self.api_base_url = api_base_url
        self.websocket_url = ""
        self.session_id = ""
        self.websocket = None
        self.is_connected = False

        # 连接状态检查定时器
        self.connection_timer = QTimer()
        self.connection_timer.timeout.connect(self._check_connection)
        self.connection_timer.start(5000)  # 每5秒检查一次

    def connect_to_session(self, session_id: str):
        """连接到指定会话"""
        self.session_id = session_id
        self.websocket_url = f"ws://127.0.0.1:9543/ws/tavern/{session_id}"

        # 启动WebSocket连接
        asyncio.create_task(self._connect_websocket())

    async def _connect_websocket(self):
        """建立WebSocket连接"""
        try:
            if self.websocket:
                await self.websocket.close()

            logger.info(f"[GraphBridge] 连接到WebSocket: {self.websocket_url}")
            self.websocket = await websockets.connect(self.websocket_url)
            self.is_connected = True
            self.connection_status_changed.emit(True, "WebSocket连接已建立")

            # 启动消息监听
            await self._listen_for_messages()

        except Exception as e:
            logger.error(f"[GraphBridge] WebSocket连接失败: {e}")
            self.is_connected = False
            self.connection_status_changed.emit(False, f"连接失败: {str(e)}")
            self.error_occurred.emit(f"WebSocket连接失败: {str(e)}")

    async def _listen_for_messages(self):
        """监听WebSocket消息"""
        try:
            while self.websocket and not self.websocket.closed:
                try:
                    message = await asyncio.wait_for(self.websocket.recv(), timeout=1.0)
                    data = json.loads(message)
                    self._handle_websocket_message(data)
                except asyncio.TimeoutError:
                    continue
                except websockets.exceptions.ConnectionClosed:
                    logger.info("[GraphBridge] WebSocket连接已关闭")
                    break
                except Exception as e:
                    logger.error(f"[GraphBridge] 处理WebSocket消息失败: {e}")
                    break

        except Exception as e:
            logger.error(f"[GraphBridge] WebSocket监听失败: {e}")
        finally:
            self.is_connected = False
            self.connection_status_changed.emit(False, "WebSocket连接已断开")

    def _handle_websocket_message(self, data: dict):
        """处理WebSocket消息"""
        try:
            message_type = data.get("type")
            logger.debug(f"[GraphBridge] 收到消息类型: {message_type}")

            # 发射通用消息信号
            self.message_received.emit(data)

            # 根据消息类型进行特定处理
            if message_type == "connection_established":
                self.connection_status_changed.emit(True, "连接已确认")

            elif message_type == "graph_updated":
                self.graph_updated.emit(data)
                logger.info(f"[GraphBridge] 图谱更新: 节点+{data.get('nodes_updated', 0)}, 边+{data.get('edges_added', 0)}")

            elif message_type == "session_updated":
                self.session_updated.emit(data)

            elif message_type == "initialization_complete":
                self.session_updated.emit(data)
                logger.info("[GraphBridge] 初始化完成")

            elif message_type == "auto_reinitialization_complete":
                self.session_updated.emit(data)
                logger.info("[GraphBridge] 自动重新初始化完成")

            elif message_type == "error":
                error_msg = data.get("message", "未知错误")
                self.error_occurred.emit(error_msg)

        except Exception as e:
            logger.error(f"[GraphBridge] 处理WebSocket消息失败: {e}")

    async def send_message(self, message: dict):
        """发送WebSocket消息"""
        try:
            if self.websocket and not self.websocket.closed:
                await self.websocket.send(json.dumps(message))
                logger.debug(f"[GraphBridge] 发送消息: {message.get('action')}")
            else:
                logger.warning("[GraphBridge] WebSocket未连接，无法发送消息")
        except Exception as e:
            logger.error(f"[GraphBridge] 发送消息失败: {e}")

    def send_request(self, action: str, payload: dict = None):
        """发送请求（异步）"""
        message = {
            "action": action,
            "request_id": f"{action}_{int(time.time())}",
            "payload": payload or {}
        }
        asyncio.create_task(self.send_message(message))

    def _check_connection(self):
        """检查连接状态"""
        if self.websocket and self.websocket.closed:
            self.is_connected = False
            self.connection_status_changed.emit(False, "连接已断开")

    def disconnect(self):
        """断开连接"""
        if self.websocket:
            asyncio.create_task(self.websocket.close())
        self.is_connected = False
        self.connection_timer.stop()

    def get_connection_status(self) -> tuple[bool, str]:
        """获取连接状态"""
        if self.is_connected:
            return True, f"已连接到会话: {self.session_id[:12]}..."
        else:
            return False, "未连接"