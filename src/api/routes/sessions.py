"""
会话管理路由
处理会话的创建、初始化、管理等操作
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from fastapi.concurrency import run_in_threadpool
from typing import Dict, Any, Optional
from loguru import logger

from ..models.requests import (
    InitializeRequest, AsyncInitializeRequest, ResetSessionRequest
)
from ..models.responses import (
    InitializeResponse, AsyncInitializeResponse, InitTaskStatusResponse,
    SessionStatsResponse
)
from ..services.session_service import SessionService, get_session_service
from ..services.memory_service import MemoryService, get_memory_service
from ...utils.exceptions import SessionError, ValidationError, ErrorCode
from ...utils.security import get_security_manager

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("/initialize", response_model=InitializeResponse)
async def initialize_session(
    req: InitializeRequest,
    session_service: SessionService = Depends(get_session_service),
    memory_service: MemoryService = Depends(get_memory_service)
):
    """
    初始化一个新的对话会话，解析角色卡和世界书来创建知识图谱。
    支持酒馆角色卡分类存储和测试模式。
    """
    try:
        logger.info(f"[START] 开始初始化会话，请求数据: session_id={req.session_id}, is_test={req.is_test}")

        # 输入验证
        security_manager = get_security_manager()
        if req.character_card:
            # 验证角色卡数据
            for key, value in req.character_card.items():
                if isinstance(value, str):
                    req.character_card[key] = security_manager.sanitize_input(value)

        if req.world_info:
            req.world_info = security_manager.sanitize_input(req.world_info)

        # 创建会话
        result = await session_service.initialize_session(req)

        logger.info(f"[SUCCESS] 会话 {result.session_id} 初始化完成")
        return result

    except ValidationError as e:
        logger.error(f"❌ 会话初始化验证失败: {e}")
        raise HTTPException(status_code=400, detail=e.to_dict())
    except SessionError as e:
        logger.error(f"❌ 会话初始化失败: {e}")
        raise HTTPException(status_code=500, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ 会话初始化异常: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to initialize session: {e}")


@router.post("/initialize_async", response_model=AsyncInitializeResponse)
async def initialize_session_async(
    req: AsyncInitializeRequest,
    background_tasks: BackgroundTasks,
    session_service: SessionService = Depends(get_session_service)
):
    """
    异步初始化会话，避免长时间阻塞请求
    返回任务ID，客户端可以通过轮询来获取进度
    """
    try:
        result = await session_service.initialize_session_async(req, background_tasks)
        logger.info(f"[START] 创建异步初始化任务: {result.task_id}")
        return result
    except Exception as e:
        logger.error(f"❌ 创建异步初始化任务失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create async initialization task: {e}")


@router.get("/initialize_status/{task_id}", response_model=InitTaskStatusResponse)
async def get_initialization_status(
    task_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """获取异步初始化任务的状态"""
    try:
        result = await session_service.get_initialization_status(task_id)
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ 获取任务状态失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get task status: {e}")


@router.get("/{session_id}/stats", response_model=SessionStatsResponse)
async def get_session_stats(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """获取会话统计信息，包括滑动窗口状态"""
    try:
        result = await session_service.get_session_stats(session_id)
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error getting session stats: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get session stats: {e}")


@router.get("/{session_id}/graph_status")
async def get_graph_status(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """获取知识图谱的最新状态，用于前端轮询更新"""
    try:
        result = await session_service.get_graph_status(session_id)
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error getting graph status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get graph status: {e}")


@router.post("/{session_id}/clear")
async def clear_session_graph(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """清空指定会话的知识图谱"""
    try:
        result = await session_service.clear_session_graph(session_id)
        logger.info(f"会话 {session_id} 的知识图谱已清空")
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"清空会话 {session_id} 图谱失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear graph: {str(e)}")


@router.post("/{session_id}/save")
async def save_session_data(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """手动保存会话数据（知识图谱和记忆）"""
    try:
        result = await session_service.save_session_data(session_id)
        logger.info(f"💾 手动保存会话 {session_id} 完成")
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error saving session data: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save session data: {e}")


@router.post("/{session_id}/reset")
async def reset_session(
    session_id: str,
    req: ResetSessionRequest,
    session_service: SessionService = Depends(get_session_service)
):
    """重置会话数据"""
    try:
        result = await session_service.reset_session(session_id, req)
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error resetting session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reset session: {e}")


@router.post("/{session_id}/reinitialize")
async def reinitialize_session(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """重新初始化酒馆会话的角色知识图谱"""
    try:
        result = await session_service.reinitialize_session(session_id)
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error reinitializing session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to reinitialize session: {e}")


@router.get("")
async def list_sessions(
    session_service: SessionService = Depends(get_session_service)
):
    """列出所有活跃会话"""
    try:
        result = await session_service.list_sessions()
        return result
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}")


@router.get("/{session_id}/export")
async def export_session_graph(
    session_id: str,
    session_service: SessionService = Depends(get_session_service)
):
    """导出会话的知识图谱为JSON格式"""
    try:
        result = await session_service.export_session_graph(session_id)
        return result
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error exporting session graph: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to export graph: {e}")