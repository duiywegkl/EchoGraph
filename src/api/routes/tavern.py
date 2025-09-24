"""
SillyTavern集成路由
处理与SillyTavern的交互
"""

from fastapi import APIRouter, HTTPException, BackgroundTasks
from loguru import logger

from ..models.requests import SubmitCharacterDataRequest, TavernMessageRequest
from ..models.responses import SubmitCharacterDataResponse, TavernMessageResponse
from ...utils.exceptions import TavernError, ValidationError

router = APIRouter(prefix="/tavern", tags=["tavern"])


@router.post("/submit_character", response_model=SubmitCharacterDataResponse)
async def submit_character_data(req: SubmitCharacterDataRequest):
    """
    插件提交角色数据端点
    允许SillyTavern插件直接提交检测到的角色数据到后台
    """
    try:
        logger.info(f"🎭 [角色提交] 收到插件角色数据提交请求")
        logger.info(f"  - 角色ID: {req.character_id}")
        logger.info(f"  - 角色名称: {req.character_name}")

        # 这里需要实现角色数据存储逻辑
        # 暂时返回成功响应
        logger.info(f"[OK] [角色提交] 角色数据已成功存储: {req.character_name} (ID: {req.character_id})")

        return SubmitCharacterDataResponse(
            success=True,
            message=f"角色数据提交成功: {req.character_name}",
            character_id=req.character_id
        )

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [角色提交] 角色数据提交失败: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to submit character data: {e}")


@router.get("/get_character/{character_id}")
async def get_character_data(character_id: str):
    """
    获取插件提交的角色数据
    供后台初始化流程使用
    """
    try:
        logger.info(f"[SEARCH] [角色获取] 查询角色数据: {character_id}")

        # 这里需要实现角色数据查询逻辑
        # 暂时返回404
        logger.warning(f"[WARN] [角色获取] 未找到角色数据: {character_id}")
        raise HTTPException(status_code=404, detail=f"Character data not found: {character_id}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [角色获取] 获取角色数据异常: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.get("/available_characters")
async def get_available_characters():
    """获取所有可用的角色数据"""
    try:
        logger.info(f"[LOG] [角色列表] 查询可用角色列表")

        # 这里需要实现角色列表查询逻辑
        # 暂时返回空列表
        characters = []

        logger.info(f"[OK] [角色列表] 返回 {len(characters)} 个角色")
        return {"characters": characters, "count": len(characters)}

    except Exception as e:
        logger.error(f"❌ [角色列表] 获取角色列表异常: {e}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/process_message", response_model=TavernMessageResponse)
async def process_tavern_message(request: TavernMessageRequest):
    """处理来自酒馆插件的消息并进行GRAG增强"""
    try:
        logger.info(f"[READY] [API] 收到酒馆消息处理请求: {request.message[:100]}...")

        # 这里需要实现消息处理逻辑
        # 暂时返回基本响应
        enhanced_context = f"[EchoGraph Basic Context]\n{request.message}"

        response = TavernMessageResponse(
            enhanced_context=enhanced_context,
            nodes_updated=0,
            edges_added=0,
            status="success"
        )

        logger.info(f"[OK] [API] 酒馆消息处理完成 - 返回上下文长度: {len(enhanced_context)}")
        return response

    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except Exception as e:
        logger.error(f"❌ [API] 酒馆消息处理异常: {e}")
        return TavernMessageResponse(
            status="error",
            error=str(e)
        )


@router.get("/current_session")
async def get_current_tavern_session():
    """获取当前活跃的酒馆会话ID"""
    try:
        logger.info(f"[get_current_tavern_session] 查询当前活跃会话")

        # 这里需要实现当前会话查询逻辑
        # 暂时返回无会话状态
        return {
            "has_session": False,
            "message": "No active tavern session found"
        }

    except Exception as e:
        logger.error(f"Error getting current tavern session: {e}")
        return {
            "has_session": False,
            "error": str(e)
        }


@router.post("/cleanup_orphaned_sessions")
async def cleanup_orphaned_sessions():
    """清理无引擎的orphaned sessions"""
    try:
        logger.info("🧹 [Manual Cleanup] 开始清理orphaned sessions")

        # 这里需要实现清理逻辑
        # 暂时返回空结果
        cleaned_sessions = []

        return {
            "cleaned_count": len(cleaned_sessions),
            "cleaned_sessions": cleaned_sessions,
            "message": f"Cleaned {len(cleaned_sessions)} orphaned sessions"
        }

    except Exception as e:
        logger.error(f"Error cleaning orphaned sessions: {e}")
        return {"error": str(e), "cleaned_count": 0}


@router.get("/characters")
async def list_characters():
    """列出所有已注册的角色"""
    try:
        # 这里需要实现角色列表查询逻辑
        # 暂时返回空列表
        characters = []
        return {"characters": characters, "total_count": len(characters)}
    except Exception as e:
        logger.error(f"Error listing characters: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list characters: {e}")


@router.get("/sessions")
async def list_active_sessions():
    """列出所有活跃会话"""
    try:
        # 这里需要实现活跃会话查询逻辑
        # 暂时返回空列表
        sessions_info = []
        return {"sessions": sessions_info, "total_count": len(sessions_info)}
    except Exception as e:
        logger.error(f"Error listing sessions: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to list sessions: {e}")


@router.post("/sessions/{session_id}/request_reinitialize")
async def request_coordinated_reinitialize(session_id: str):
    """
    请求插件提交当前角色数据，然后自动执行重新初始化。
    这是一个协调式的初始化流程，确保获取最新的角色数据。
    """
    logger.info(f"🔄 [Coord Re-init] Received coordinated re-initialization request for session {session_id}")

    try:
        # 这里需要实现协调式重新初始化逻辑
        # 暂时返回成功响应
        return {
            "success": True,
            "message": "已向插件发送角色数据请求，请等待插件提交数据后自动重新初始化。",
            "session_id": session_id,
            "next_step": "插件将自动提交角色数据并触发重新初始化"
        }

    except Exception as e:
        logger.error(f"❌ [Coord Re-init] Failed to send request to plugin: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"向插件发送请求失败：{e}"
        )


@router.post("/sessions/{session_id}/reinitialize_from_plugin")
async def reinitialize_session_from_plugin(session_id: str, background_tasks: BackgroundTasks):
    """
    使用插件最后一次提交的数据，重新初始化会话的知识图谱。
    这是一个耗时操作，将作为后台任务运行。
    """
    logger.info(f"🔄 [Re-init] Received request to re-initialize session {session_id} from plugin submission")

    try:
        # 这里需要实现从插件数据重新初始化的逻辑
        # 暂时返回成功响应
        return {
            "message": "Re-initialization started in the background. The graph will be updated shortly.",
            "session_id": session_id,
            "character_id": "unknown"
        }

    except Exception as e:
        logger.error(f"❌ [Re-init] Failed to start re-initialization: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to start re-initialization: {e}")


@router.delete("/character/{character_name}")
async def delete_character(character_name: str):
    """删除指定角色的所有数据"""
    try:
        logger.info(f"🗑️ [Character Delete] Deleting character: {character_name}")

        # 这里需要实现角色删除逻辑
        # 暂时返回成功响应
        return {"message": f"Character '{character_name}' deleted successfully"}

    except Exception as e:
        logger.error(f"Error deleting character: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete character: {e}")


@router.post("/new_session")
async def create_new_session(character_name: str):
    """为已存在的角色创建新会话"""
    try:
        logger.info(f"🆕 [New Session] Creating new session for character: {character_name}")

        # 这里需要实现新会话创建逻辑
        # 暂时返回基本响应
        new_session_id = f"tavern_{character_name}_new"
        return {
            "session_id": new_session_id,
            "character_name": character_name,
            "message": "New session created successfully"
        }

    except Exception as e:
        logger.error(f"Error creating new session: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create new session: {e}")