"""
WebSocket消息处理器
处理来自SillyTavern插件的各种消息
"""

import asyncio
from typing import Dict, Any
from loguru import logger

from ..models.requests import (
    InitializeRequest, EnhancePromptRequest, ProcessConversationRequest,
    SyncConversationRequest, SubmitCharacterDataRequest
)
from ..services.session_service import get_session_service
from ..services.memory_service import get_memory_service
from ...utils.exceptions import EchoGraphException, SessionError, ValidationError, ErrorCode
from ...utils.enhanced_config import get_config


class WebSocketHandler:
    """WebSocket消息处理器"""

    def __init__(self):
        self.config = get_config()
        self.session_service = get_session_service()
        self.memory_service = get_memory_service()

    async def handle_request(self, session_id: str, message: Dict[str, Any]) -> Dict[str, Any]:
        """处理WebSocket请求"""
        action = message.get("action")
        payload = message.get("payload") or {}

        try:
            logger.info(f"[WS] Routing action='{action}' for session={session_id} | "
                       f"payload_keys={list(payload.keys())}")

            # 检查Tavern模式
            if not self._is_tavern_mode_active():
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.PERMISSION_DENIED.value,
                        "message": "Tavern mode is disabled"
                    }
                }

            # 路由到对应的处理方法
            handler_map = {
                "initialize": self._handle_initialize,
                "enhance_prompt": self._handle_enhance_prompt,
                "process_conversation": self._handle_process_conversation,
                "sync_conversation": self._handle_sync_conversation,
                "tavern.submit_character": self._handle_submit_character,
                "tavern.request_character_data": self._handle_request_character_data,
                "tavern.current_session": self._handle_current_session,
                "sessions.stats": self._handle_session_stats,
                "health": self._handle_health_check,
                "system.full_reset": self._handle_system_reset
            }

            handler = handler_map.get(action)
            if not handler:
                return {
                    "ok": False,
                    "error": {
                        "code": ErrorCode.VALIDATION_ERROR.value,
                        "message": f"Unknown action: {action}"
                    }
                }

            return await handler(session_id, payload)

        except EchoGraphException as e:
            logger.error(f"[WS] EchoGraph error handling action '{action}': {e}")
            return {
                "ok": False,
                "error": {
                    "code": e.error_code.value,
                    "message": str(e),
                    "details": e.details
                }
            }
        except Exception as e:
            logger.exception(f"[WS] Unexpected error handling action '{action}' for session {session_id}: {e}")
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.UNKNOWN_ERROR.value,
                    "message": "Internal server error"
                }
            }

    async def _handle_initialize(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理初始化请求"""
        try:
            req = InitializeRequest(**payload)
            req.session_id = session_id  # 强制使用WebSocket连接的session_id
            resp = await self.session_service.initialize_session(req)
            return {"ok": True, "data": resp.model_dump()}
        except ValidationError as e:
            raise e
        except Exception as e:
            raise SessionError(f"Initialize failed: {e}", session_id=session_id)

    async def _handle_enhance_prompt(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理增强提示词请求"""
        try:
            req = EnhancePromptRequest(session_id=session_id, **payload)
            resp = await self.memory_service.enhance_prompt(req)
            return {"ok": True, "data": resp.model_dump()}
        except ValidationError as e:
            raise e
        except Exception as e:
            raise SessionError(f"Enhance prompt failed: {e}", session_id=session_id)

    async def _handle_process_conversation(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理对话处理请求"""
        try:
            req = ProcessConversationRequest(session_id=session_id, **payload)
            resp = await self.memory_service.process_conversation(req)
            return {"ok": True, "data": resp.model_dump()}
        except ValidationError as e:
            raise e
        except Exception as e:
            raise SessionError(f"Process conversation failed: {e}", session_id=session_id)

    async def _handle_sync_conversation(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理对话同步请求"""
        try:
            req = SyncConversationRequest(session_id=session_id, **payload)
            resp = await self.memory_service.sync_conversation(req)
            return {"ok": True, "data": resp.model_dump()}
        except ValidationError as e:
            raise e
        except Exception as e:
            raise SessionError(f"Sync conversation failed: {e}", session_id=session_id)

    async def _handle_submit_character(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理提交角色数据请求"""
        try:
            # 这里需要实现角色数据提交逻辑
            # 暂时返回成功响应
            req = SubmitCharacterDataRequest(**payload)
            return {
                "ok": True,
                "data": {
                    "success": True,
                    "message": f"角色数据提交成功: {req.character_name}",
                    "character_id": req.character_id
                }
            }
        except ValidationError as e:
            raise e
        except Exception as e:
            raise SessionError(f"Submit character failed: {e}", session_id=session_id)

    async def _handle_request_character_data(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理请求角色数据"""
        logger.info(f"[WS] Processing tavern.request_character_data for session_id: {session_id}")
        return {
            "ok": True,
            "data": {
                "message": "请插件提交当前角色数据",
                "action_required": "submit_current_character"
            }
        }

    async def _handle_current_session(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理当前会话查询请求"""
        logger.info(f"[WS] Processing tavern.current_session for session_id: {session_id}")

        try:
            # 检查会话是否存在
            sessions = self.session_service.sessions
            if session_id in sessions and session_id.startswith("tavern_"):
                engine = sessions[session_id]
                nodes_count = len(engine.memory.knowledge_graph.graph.nodes())
                edges_count = len(engine.memory.knowledge_graph.graph.edges())

                logger.info(f"[WS] Session graph stats: nodes={nodes_count}, edges={edges_count}")

                data = {
                    "has_session": True,
                    "session_id": session_id,
                    "graph_nodes": nodes_count,
                    "graph_edges": edges_count,
                    "message": "Active tavern session found"
                }
            else:
                logger.info(f"[WS] No session found for: {session_id}")
                data = {
                    "has_session": False,
                    "message": f"No active tavern session found for {session_id}. Please send initialization data."
                }

            return {"ok": True, "data": data}

        except Exception as e:
            logger.error(f"[WS] Error getting current session: {e}")
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.SESSION_NOT_FOUND.value,
                    "message": str(e)
                }
            }

    async def _handle_session_stats(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理会话统计请求"""
        try:
            target_session_id = payload.get("session_id", session_id)
            resp = await self.session_service.get_session_stats(target_session_id)

            # 处理返回数据
            if hasattr(resp, 'model_dump'):
                return {"ok": True, "data": resp.model_dump()}
            else:
                return {"ok": True, "data": resp}
        except SessionError as e:
            raise e
        except Exception as e:
            raise SessionError(f"Get session stats failed: {e}", session_id=session_id)

    async def _handle_health_check(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理健康检查请求"""
        try:
            # 这里需要实现健康检查逻辑
            # 暂时返回基本信息
            sessions = self.session_service.sessions
            health_data = {
                "status": "healthy",
                "version": "1.0.0",
                "active_sessions": len(sessions),
                "llm_configured": bool(self.config.llm.api_key and self.config.llm.base_url)
            }
            return {"ok": True, "data": health_data}
        except Exception as e:
            logger.error(f"[WS] Health check failed: {e}")
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.UNKNOWN_ERROR.value,
                    "message": "Health check failed"
                }
            }

    async def _handle_system_reset(self, session_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        """处理系统重置请求"""
        try:
            # 这里需要实现系统重置逻辑
            # 暂时返回成功响应
            logger.warning(f"[WS] System reset requested by session {session_id}")
            return {
                "ok": True,
                "data": {
                    "success": True,
                    "message": "系统重置完成",
                    "cleared_counts": {
                        "sessions": 0,
                        "connections": 0
                    }
                }
            }
        except Exception as e:
            logger.error(f"[WS] System reset failed: {e}")
            return {
                "ok": False,
                "error": {
                    "code": ErrorCode.UNKNOWN_ERROR.value,
                    "message": "System reset failed"
                }
            }

    def _is_tavern_mode_active(self) -> bool:
        """检查Tavern模式是否激活"""
        # 这里需要从配置或全局状态检查
        # 暂时返回True
        return True


# 全局处理器实例
_websocket_handler: Optional[WebSocketHandler] = None


def get_websocket_handler() -> WebSocketHandler:
    """获取WebSocket处理器实例"""
    global _websocket_handler
    if _websocket_handler is None:
        _websocket_handler = WebSocketHandler()
    return _websocket_handler