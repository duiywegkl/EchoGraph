"""
WebSocket连接管理器
处理SillyTavern插件的WebSocket连接
"""

import asyncio
from typing import Dict, Any, Optional, Set
from fastapi import WebSocket, WebSocketDisconnect
from loguru import logger

from ...utils.exceptions import WebSocketError, ErrorCode


class ConnectionManager:
    """WebSocket连接管理器"""

    def __init__(self):
        # Map session_id -> WebSocket (current active socket for that session)
        self.active_connections: Dict[str, WebSocket] = {}
        self._connection_lock = asyncio.Lock()

    async def connect(self, session_id: str, websocket: WebSocket):
        """建立WebSocket连接"""
        async with self._connection_lock:
            await websocket.accept()

            # 如果已有相同会话的连接，关闭旧连接
            old_ws = self.active_connections.get(session_id)
            if old_ws is not None and old_ws is not websocket:
                try:
                    await old_ws.close(code=1012, reason="Replaced by new connection")
                    logger.info(f"🔌 [WS] Closed old connection for session {session_id}")
                except Exception as e:
                    logger.warning(f"[WARN] [WS] Failed to close old connection: {e}")

            self.active_connections[session_id] = websocket
            logger.info(f"🔌 [WS] Plugin connected for session {session_id}. "
                       f"Total connections: {len(self.active_connections)}")

    def disconnect(self, session_id: str, websocket: Optional[WebSocket] = None):
        """断开WebSocket连接"""
        try:
            if session_id in self.active_connections:
                # 只有当传入的websocket与存储的相同时才删除（避免删除新连接）
                if websocket is None or self.active_connections.get(session_id) is websocket:
                    del self.active_connections[session_id]
                    logger.info(f"🔌 [WS] Plugin disconnected for session {session_id}. "
                               f"Total connections: {len(self.active_connections)}")

                    # 清理orphaned session的逻辑在这里可以调用其他服务
                    # 为了避免循环依赖，这里只记录日志
                    if session_id.startswith('tavern_'):
                        logger.info(f"🧹 [Cleanup] Session {session_id} disconnected, "
                                   f"may need cleanup if no engine exists")

        except Exception as e:
            logger.error(f"❌ [WS] Error during disconnect: {e}")

    async def send_message(self, session_id: str, message: Dict[str, Any]):
        """发送消息到指定会话"""
        if session_id in self.active_connections:
            websocket = self.active_connections[session_id]
            try:
                await websocket.send_json(message)
                logger.debug(f"📤 [WS] Sent message to session {session_id}: {message.get('type')}")
            except Exception as e:
                logger.error(f"❌ [WS] Failed to send message to session {session_id}: {e}")
                # 发送失败时断开连接
                self.disconnect(session_id, websocket)
                raise WebSocketError(
                    f"Failed to send message: {e}",
                    connection_id=session_id,
                    error_code=ErrorCode.WEBSOCKET_MESSAGE_ERROR
                )
        else:
            logger.warning(f"[WARN] [WS] No active connection for session {session_id}")
            raise WebSocketError(
                f"No active connection for session {session_id}",
                connection_id=session_id,
                error_code=ErrorCode.WEBSOCKET_CONNECTION_FAILED
            )

    async def broadcast_message(self, message: Dict[str, Any], exclude_sessions: Set[str] = None):
        """广播消息到所有连接"""
        exclude_sessions = exclude_sessions or set()
        disconnected_sessions = []

        for session_id, websocket in self.active_connections.items():
            if session_id in exclude_sessions:
                continue

            try:
                await websocket.send_json(message)
                logger.debug(f"📤 [WS] Broadcasted message to session {session_id}")
            except Exception as e:
                logger.error(f"❌ [WS] Failed to broadcast to session {session_id}: {e}")
                disconnected_sessions.append(session_id)

        # 清理失败的连接
        for session_id in disconnected_sessions:
            self.disconnect(session_id)

    def get_connection_count(self) -> int:
        """获取当前连接数"""
        return len(self.active_connections)

    def get_connected_sessions(self) -> list:
        """获取所有已连接的会话ID"""
        return list(self.active_connections.keys())

    def is_connected(self, session_id: str) -> bool:
        """检查指定会话是否已连接"""
        return session_id in self.active_connections

    async def close_all_connections(self, reason: str = "Server shutdown"):
        """关闭所有连接"""
        logger.info(f"🔌 [WS] Closing all connections: {reason}")

        async with self._connection_lock:
            for session_id, websocket in list(self.active_connections.items()):
                try:
                    await websocket.close(code=1001, reason=reason)
                    logger.debug(f"🔌 [WS] Closed connection for session {session_id}")
                except Exception as e:
                    logger.warning(f"[WARN] [WS] Failed to close connection {session_id}: {e}")

            self.active_connections.clear()
            logger.info("🔌 [WS] All connections closed")

    async def cleanup_stale_connections(self, timeout_seconds: int = 300):
        """清理过期连接"""
        current_time = asyncio.get_event_loop().time()
        stale_sessions = []

        for session_id, websocket in self.active_connections.items():
            try:
                # 发送ping消息检查连接状态
                await websocket.send_json({"type": "ping", "timestamp": current_time})
            except Exception:
                stale_sessions.append(session_id)

        # 清理过期连接
        for session_id in stale_sessions:
            logger.info(f"🧹 [WS] Removing stale connection: {session_id}")
            self.disconnect(session_id)


# 全局连接管理器实例
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """获取WebSocket连接管理器实例"""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager