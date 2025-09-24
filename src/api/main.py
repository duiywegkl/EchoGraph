"""
EchoGraph API主入口
重构后的模块化FastAPI应用
"""

import asyncio
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from .middleware.security import setup_cors_middleware, setup_security_middleware, setup_logging_middleware
from .routes import sessions, memory, graph, tavern, system
from .websocket.manager import get_connection_manager
from .websocket.handlers import get_websocket_handler
from .services.session_service import get_session_service
from .services.memory_service import get_memory_service
from ..utils.enhanced_config import get_config
from ..utils.exceptions import EchoGraphException


# 全局变量
app_state = {
    "startup_time": None,
    "tavern_mode_active": False
}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    app_state["startup_time"] = time.time()
    logger.info("[START] EchoGraph API服务器启动中...")

    # 初始化服务
    await _initialize_services()

    logger.info("[OK] EchoGraph API服务器启动完成")

    yield

    # 关闭时执行
    logger.info("🔄 EchoGraph API服务器关闭中...")
    await _cleanup_services()
    logger.info("[OK] EchoGraph API服务器已关闭")


async def _initialize_services():
    """初始化服务"""
    try:
        # 获取配置
        config = get_config()

        # 初始化服务间的依赖关系
        session_service = get_session_service()
        memory_service = get_memory_service()

        # 设置服务间的引用关系
        memory_service.set_sessions(session_service.sessions)
        memory_service.set_sliding_window_managers(session_service.sliding_window_managers)
        memory_service.set_conflict_resolvers(session_service.conflict_resolvers)

        # 设置Tavern模式状态
        app_state["tavern_mode_active"] = True

        logger.info("[CHART] 服务初始化完成")
        logger.info(f"  - 环境: {config.system.environment}")
        logger.info(f"  - LLM配置: {config.get_masked_api_key()}")
        logger.info(f"  - Tavern模式: {app_state['tavern_mode_active']}")

    except Exception as e:
        logger.error(f"❌ 服务初始化失败: {e}")
        raise


async def _cleanup_services():
    """清理服务"""
    try:
        # 关闭所有WebSocket连接
        manager = get_connection_manager()
        await manager.close_all_connections("Server shutdown")

        # 清理定时任务
        # 这里可以添加其他清理逻辑

        logger.info("🧹 服务清理完成")
    except Exception as e:
        logger.error(f"❌ 服务清理失败: {e}")


def create_app() -> FastAPI:
    """创建FastAPI应用"""
    config = get_config()

    app = FastAPI(
        title="EchoGraph API",
        description="A backend service for SillyTavern to provide dynamic knowledge graph and RAG capabilities.",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/docs" if config.is_development() else None,
        redoc_url="/redoc" if config.is_development() else None
    )

    # 设置中间件
    _setup_middleware(app, config)

    # 注册路由
    _register_routes(app)

    # 注册WebSocket端点
    _register_websocket_routes(app)

    # 全局异常处理器
    _setup_exception_handlers(app)

    return app


def _setup_middleware(app: FastAPI, config):
    """设置中间件"""
    # 日志中间件（最先执行）
    setup_logging_middleware(app)

    # 安全中间件
    setup_security_middleware(
        app,
        enable_rate_limiting=config.security.enable_rate_limiting,
        max_requests_per_minute=config.security.max_requests_per_minute
    )

    # CORS中间件
    cors_origins = config.get_cors_origins()
    setup_cors_middleware(app, cors_origins)

    logger.info("[SECURITY] 中间件配置完成")


def _register_routes(app: FastAPI):
    """注册API路由"""
    # 会话管理路由
    app.include_router(sessions.router)

    # 记忆和图谱路由
    app.include_router(memory.router)
    app.include_router(graph.router)

    # SillyTavern集成路由
    app.include_router(tavern.router)

    # 系统管理路由
    app.include_router(system.router)

    logger.info("📍 API路由注册完成")


def _register_websocket_routes(app: FastAPI):
    """注册WebSocket路由"""

    @app.websocket("/ws/tavern/{session_id}")
    async def websocket_endpoint(websocket: WebSocket, session_id: str):
        """WebSocket端点，供SillyTavern插件连接"""
        logger.info(f"🔌 [WS] New WebSocket connection attempt for session: {session_id}")

        # 检查Tavern模式
        if not app_state["tavern_mode_active"]:
            logger.warning(f"🔌 [WS] Rejecting connection for {session_id}: Tavern mode disabled")
            await websocket.accept()
            await websocket.close(code=1008, reason="Tavern mode disabled")
            return

        manager = get_connection_manager()
        handler = get_websocket_handler()

        logger.info(f"🔌 [WS] Accepting WebSocket connection for session: {session_id}")
        await manager.connect(session_id, websocket)

        try:
            # 发送连接确认消息
            await websocket.send_json({
                "type": "connection_established",
                "message": f"Successfully connected to EchoGraph for session {session_id}.",
                "session_id": session_id
            })

            # 主循环：接收请求并路由处理
            logger.info(f"🔌 [WS] Starting message loop for session: {session_id}")

            # 添加超时检测
            timeout_task = None

            async def check_activity_timeout():
                await asyncio.sleep(10)  # 10秒超时
                logger.warning(f"[WARN] [WS] No requests received within 10s for session: {session_id}")

            timeout_task = asyncio.create_task(check_activity_timeout())

            while True:
                msg = await websocket.receive_json()

                # 取消超时检测
                if timeout_task and not timeout_task.done():
                    timeout_task.cancel()

                # 处理消息
                req_id = msg.get("request_id")
                action = msg.get("action")

                logger.info(f"📥 [WS] Received request | session={session_id} | "
                           f"action={action} | request_id={req_id}")

                # 路由到处理器
                result = await handler.handle_request(session_id, msg)

                # 发送响应
                await websocket.send_json({
                    "type": "response",
                    "action": action,
                    "request_id": req_id,
                    **result
                })

                logger.debug(f"📤 [WS] Response sent for action '{action}' to session {session_id}")

                # 重置超时检测
                timeout_task = asyncio.create_task(check_activity_timeout())

        except WebSocketDisconnect:
            logger.info(f"🔌 [WS] WebSocket disconnected normally for session: {session_id}")
            manager.disconnect(session_id, websocket)
        except Exception as e:
            logger.error(f"❌ [WS] Error in WebSocket connection for session {session_id}: {e}")
            manager.disconnect(session_id, websocket)

    logger.info("🔌 WebSocket路由注册完成")


def _setup_exception_handlers(app: FastAPI):
    """设置全局异常处理器"""

    @app.exception_handler(EchoGraphException)
    async def echograph_exception_handler(request, exc: EchoGraphException):
        """EchoGraph自定义异常处理器"""
        logger.error(f"EchoGraph Exception: {exc}")
        return HTTPException(
            status_code=400,
            detail=exc.to_dict()
        )

    @app.exception_handler(ValueError)
    async def value_error_handler(request, exc: ValueError):
        """值错误处理器"""
        logger.error(f"Value Error: {exc}")
        return HTTPException(
            status_code=400,
            detail={"error": "Invalid input value", "message": str(exc)}
        )

    @app.exception_handler(Exception)
    async def general_exception_handler(request, exc: Exception):
        """通用异常处理器"""
        logger.exception(f"Unhandled exception: {exc}")
        return HTTPException(
            status_code=500,
            detail={"error": "Internal server error", "message": "An unexpected error occurred"}
        )

    logger.info("[WARN] 异常处理器注册完成")


# 健康检查端点
@app.get("/health")
async def health_check():
    """健康检查端点"""
    if not app_state["tavern_mode_active"]:
        raise HTTPException(status_code=403, detail="Tavern mode disabled")

    config = get_config()
    session_service = get_session_service()
    manager = get_connection_manager()

    # 计算运行时间
    uptime = time.time() - app_state["startup_time"] if app_state["startup_time"] else 0

    health_data = {
        "status": "healthy",
        "version": "2.0.0",
        "uptime": uptime,
        "environment": config.system.environment,
        "active_sessions": len(session_service.sessions),
        "websocket_connections": manager.get_connection_count(),
        "llm_configured": bool(config.llm.api_key and config.llm.base_url),
        "tavern_mode_active": app_state["tavern_mode_active"]
    }

    logger.info("🏥 [Health Check] System healthy")
    return health_data


@app.get("/system/liveness")
async def liveness():
    """存活检查端点（不受Tavern模式限制）"""
    return {"ok": True, "version": "2.0.0", "timestamp": time.time()}


# 系统模式控制端点
@app.get("/system/tavern_mode")
async def get_tavern_mode_state():
    """获取Tavern模式状态"""
    return {"active": app_state["tavern_mode_active"]}


@app.post("/system/tavern_mode")
async def set_tavern_mode_state(payload: dict):
    """设置Tavern模式状态"""
    try:
        active = payload.get("active", False)
        if isinstance(active, str):
            active = active.lower() in ("1", "true", "yes", "on")

        app_state["tavern_mode_active"] = bool(active)
        logger.info(f"🛠️ [Mode] Set TAVERN_MODE_ACTIVE = {app_state['tavern_mode_active']}")

        return {"success": True, "active": app_state["tavern_mode_active"]}
    except Exception as e:
        logger.error(f"[Mode] Failed to set tavern mode: {e}")
        raise HTTPException(status_code=400, detail=str(e))


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    import argparse

    parser = argparse.ArgumentParser(description="EchoGraph API Server")
    parser.add_argument("--port", type=int, default=9543, help="Port to run the API server on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to run the API server on")
    args = parser.parse_args()

    logger.info(f"Starting EchoGraph API server on {args.host}:{args.port}...")
    uvicorn.run(app, host=args.host, port=args.port)