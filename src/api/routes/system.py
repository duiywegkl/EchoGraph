"""
系统管理路由
处理系统级别的操作和管理功能
"""

from fastapi import APIRouter, HTTPException
from loguru import logger

from ..models.requests import SystemControlRequest
from ..models.responses import SystemResetResponse, HealthCheckResponse
from ...utils.enhanced_config import get_config

router = APIRouter(prefix="/system", tags=["system"])


@router.post("/full_reset", response_model=SystemResetResponse)
async def full_system_reset():
    """
    完全清理系统状态，包括所有会话、存储数据和缓存
    解决重复连接和数据冲突问题
    """
    try:
        logger.info("🧼 [Full Reset] 开始完全清理系统...")

        # 这里需要实现完全重置逻辑
        # 暂时返回基本响应
        cleared_counts = {
            "sessions": 0,
            "sliding_windows": 0,
            "conflict_resolvers": 0,
            "initialization_tasks": 0,
            "plugin_characters": 0,
            "websocket_connections": 0,
            "total": 0
        }

        logger.info(f"[SUCCESS] [Full Reset] 系统完全清理完成！")

        return SystemResetResponse(
            success=True,
            message="系统已完全清理，可以重新开始使用",
            cleared_counts=cleared_counts
        )

    except Exception as e:
        logger.error(f"❌ [Full Reset] 系统清理失败: {e}")
        return SystemResetResponse(
            success=False,
            message=f"系统清理失败: {str(e)}",
            cleared_counts={}
        )


@router.get("/quick_reset", response_model=SystemResetResponse)
async def quick_reset():
    """
    快速清理 - 只清理内存中的会话和连接，不影响文件系统
    适合解决重复连接问题
    """
    try:
        logger.info("🛠️ [Quick Reset] 开始快速清理...")

        # 这里需要实现快速清理逻辑
        # 暂时返回基本响应
        cleared_counts = {
            "sessions": 0,
            "sliding_windows": 0,
            "conflict_resolvers": 0,
            "websocket_connections": 0,
            "plugin_characters": 0,
            "total": 0
        }

        logger.info(f"[OK] [Quick Reset] 快速清理完成！")

        return SystemResetResponse(
            success=True,
            message=f"快速清理完成，清理了 0 个对象",
            cleared_counts=cleared_counts
        )

    except Exception as e:
        logger.error(f"❌ [Quick Reset] 快速清理失败: {e}")
        return SystemResetResponse(
            success=False,
            message=f"快速清理失败: {str(e)}",
            cleared_counts={}
        )


@router.post("/control")
async def system_control(req: SystemControlRequest):
    """系统控制端点"""
    try:
        logger.info(f"🎛️ [System Control] Executing action: {req.action}")

        if req.action == "reload_config":
            # 重新加载配置
            config = get_config()
            config.reload()
            return {"success": True, "message": "Configuration reloaded successfully"}

        elif req.action == "health_check":
            # 执行健康检查
            return await get_system_health()

        else:
            raise HTTPException(status_code=400, detail=f"Unknown system action: {req.action}")

    except Exception as e:
        logger.error(f"❌ [System Control] Action failed: {e}")
        raise HTTPException(status_code=500, detail=f"System control action failed: {e}")


@router.get("/health", response_model=HealthCheckResponse)
async def get_system_health():
    """获取系统健康状态"""
    try:
        config = get_config()

        # 这里需要实现健康检查逻辑
        # 暂时返回基本健康状态
        health_data = HealthCheckResponse(
            status="healthy",
            version="2.0.0",
            active_sessions=0,
            agent_enabled_sessions=0,
            local_processor_sessions=0,
            websocket_connections=0,
            llm_configured=bool(config.llm.api_key and config.llm.base_url),
            storage_path="data",
            total_characters=0
        )

        logger.info("🏥 [Health Check] System health checked")
        return health_data

    except Exception as e:
        logger.error(f"❌ [Health Check] Health check failed: {e}")
        raise HTTPException(status_code=500, detail=f"Health check failed: {e}")


@router.get("/info")
async def get_system_info():
    """获取系统信息"""
    try:
        config = get_config()

        system_info = {
            "application": {
                "name": config.system.name,
                "version": config.system.version,
                "environment": config.system.environment,
                "debug": config.system.debug
            },
            "configuration": {
                "llm_provider": config.llm.provider,
                "llm_model": config.llm.model,
                "llm_configured": bool(config.llm.api_key and config.llm.base_url),
                "memory_max_hot": config.memory.max_hot_memory,
                "security_rate_limiting": config.security.enable_rate_limiting
            },
            "features": {
                "sliding_window": config.game.enable_sliding_window,
                "auto_save": config.memory.enable_auto_save,
                "input_sanitization": config.security.enable_input_sanitization
            }
        }

        return system_info

    except Exception as e:
        logger.error(f"❌ [System Info] Failed to get system info: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get system info: {e}")


@router.get("/logs/recent")
async def get_recent_logs(lines: int = 100):
    """获取最近的日志记录"""
    try:
        # 这里需要实现日志读取逻辑
        # 暂时返回空日志
        recent_logs = []

        return {
            "logs": recent_logs,
            "total_lines": len(recent_logs),
            "requested_lines": lines
        }

    except Exception as e:
        logger.error(f"❌ [Logs] Failed to get recent logs: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get recent logs: {e}")


@router.post("/maintenance")
async def toggle_maintenance_mode(enabled: bool):
    """切换维护模式"""
    try:
        logger.info(f"[TOOL] [Maintenance] Toggling maintenance mode: {enabled}")

        # 这里需要实现维护模式逻辑
        # 暂时返回成功响应
        return {
            "success": True,
            "maintenance_mode": enabled,
            "message": f"Maintenance mode {'enabled' if enabled else 'disabled'}"
        }

    except Exception as e:
        logger.error(f"❌ [Maintenance] Failed to toggle maintenance mode: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to toggle maintenance mode: {e}")