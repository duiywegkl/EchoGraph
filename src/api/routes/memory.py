"""
记忆管理路由
处理记忆相关的操作
"""

from fastapi import APIRouter, HTTPException, Depends
from loguru import logger

from ..models.requests import EnhancePromptRequest, UpdateMemoryRequest, ProcessConversationRequest, SyncConversationRequest
from ..models.responses import EnhancePromptResponse, UpdateMemoryResponse, ProcessConversationResponse, SyncConversationResponse
from ..services.memory_service import MemoryService, get_memory_service
from ...utils.exceptions import SessionError, ValidationError

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/enhance_prompt", response_model=EnhancePromptResponse)
async def enhance_prompt(
    req: EnhancePromptRequest,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """
    根据用户输入，从知识图谱中检索上下文以增强Prompt。
    支持最大上下文长度限制和详细的实体分析。
    """
    try:
        result = await memory_service.enhance_prompt(req)
        return result
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error during prompt enhancement: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to enhance prompt: {e}")


@router.post("/update", response_model=UpdateMemoryResponse)
async def update_memory(
    req: UpdateMemoryRequest,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """
    分析LLM的回复，提取新信息更新知识图谱，并记录对话历史。
    支持时间戳和聊天ID跟踪。
    """
    try:
        result = await memory_service.update_memory(req)
        return result
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error during memory update: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update memory: {e}")


@router.post("/process_conversation", response_model=ProcessConversationResponse)
async def process_conversation(
    req: ProcessConversationRequest,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """
    使用滑动窗口系统处理新的对话轮次
    支持延迟处理和冲突解决
    """
    try:
        result = await memory_service.process_conversation(req)
        return result
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error during sliding window conversation processing: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to process conversation: {e}")


@router.post("/sync_conversation", response_model=SyncConversationResponse)
async def sync_conversation(
    req: SyncConversationRequest,
    memory_service: MemoryService = Depends(get_memory_service)
):
    """
    同步SillyTavern对话历史，解决冲突
    """
    try:
        result = await memory_service.sync_conversation(req)
        return result
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=e.to_dict())
    except SessionError as e:
        raise HTTPException(status_code=404, detail=e.to_dict())
    except Exception as e:
        logger.error(f"Error during conversation sync: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to sync conversation: {e}")