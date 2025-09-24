"""
API请求数据模型
定义所有API端点的请求参数
"""

from pydantic import BaseModel, Field, validator
from typing import List, Dict, Any, Optional
from datetime import datetime


class InitializeRequest(BaseModel):
    """会话初始化请求"""
    session_id: Optional[str] = None
    character_card: Dict[str, Any]
    world_info: str
    session_config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_test: bool = False
    enable_agent: bool = True

    @validator('character_card')
    def validate_character_card(cls, v):
        if not v:
            raise ValueError("Character card cannot be empty")
        if not isinstance(v, dict):
            raise ValueError("Character card must be a dictionary")
        return v

    @validator('world_info')
    def validate_world_info(cls, v):
        if v and len(v) > 100000:  # 100KB限制
            raise ValueError("World info too large (max 100KB)")
        return v


class AsyncInitializeRequest(BaseModel):
    """异步会话初始化请求"""
    session_id: Optional[str] = None
    character_card: Dict[str, Any]
    world_info: str
    session_config: Optional[Dict[str, Any]] = Field(default_factory=dict)
    is_test: bool = False
    enable_agent: bool = False  # 异步模式默认禁用Agent避免超时


class EnhancePromptRequest(BaseModel):
    """增强提示词请求"""
    session_id: str
    user_input: str = Field(..., min_length=1, max_length=10000)
    recent_history: Optional[List[Dict[str, str]]] = None
    max_context_length: Optional[int] = Field(default=4000, ge=100, le=32000)

    @validator('user_input')
    def validate_user_input(cls, v):
        if not v.strip():
            raise ValueError("User input cannot be empty")
        return v.strip()


class UpdateMemoryRequest(BaseModel):
    """更新记忆请求"""
    session_id: str
    llm_response: str = Field(..., max_length=50000)
    user_input: str = Field(..., max_length=10000)
    timestamp: Optional[str] = None
    chat_id: Optional[int] = None

    @validator('timestamp')
    def validate_timestamp(cls, v):
        if v:
            try:
                datetime.fromisoformat(v.replace('Z', '+00:00'))
            except ValueError:
                raise ValueError("Invalid timestamp format")
        return v


class ProcessConversationRequest(BaseModel):
    """滑动窗口对话处理请求"""
    session_id: str
    user_input: str = Field(..., max_length=10000)
    llm_response: str = Field(..., max_length=50000)
    timestamp: Optional[str] = None
    chat_id: Optional[int] = None
    tavern_message_id: Optional[str] = None


class SyncConversationRequest(BaseModel):
    """同步对话请求"""
    session_id: str
    tavern_history: List[Dict[str, Any]]

    @validator('tavern_history')
    def validate_tavern_history(cls, v):
        if len(v) > 1000:  # 最多1000条历史记录
            raise ValueError("Too many history entries (max 1000)")
        return v


class ResetSessionRequest(BaseModel):
    """重置会话请求"""
    session_id: str
    keep_character_data: bool = True


class SubmitCharacterDataRequest(BaseModel):
    """提交角色数据请求"""
    character_id: str = Field(..., min_length=1, max_length=100)
    character_name: str = Field(..., min_length=1, max_length=200)
    character_data: Dict[str, Any]
    timestamp: Optional[float] = None

    @validator('character_id')
    def validate_character_id(cls, v):
        # 移除潜在的危险字符
        import re
        if not re.match(r'^[a-zA-Z0-9_\-\.]+$', v):
            raise ValueError("Invalid character ID format")
        return v


class TavernMessageRequest(BaseModel):
    """酒馆消息处理请求"""
    message: str = Field(..., min_length=1, max_length=10000)
    session_id: Optional[str] = "tavern_session"
    mode: Optional[str] = "tavern_integration"
    timestamp: Optional[float] = None


class NodeUpdateRequest(BaseModel):
    """节点更新请求"""
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(..., min_length=1, max_length=50)
    description: Optional[str] = Field(default="", max_length=2000)
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator('type')
    def validate_node_type(cls, v):
        valid_types = ['character', 'location', 'item', 'skill', 'organization', 'event', 'concept']
        if v not in valid_types:
            raise ValueError(f"Node type must be one of: {valid_types}")
        return v


class EdgeCreateRequest(BaseModel):
    """创建关系请求"""
    source: str = Field(..., min_length=1, max_length=200)
    target: str = Field(..., min_length=1, max_length=200)
    relationship: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(default="", max_length=1000)
    attributes: Optional[Dict[str, Any]] = Field(default_factory=dict)


class WebSocketRequest(BaseModel):
    """WebSocket请求基类"""
    action: str = Field(..., min_length=1, max_length=50)
    request_id: Optional[str] = None
    payload: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator('action')
    def validate_action(cls, v):
        valid_actions = [
            'initialize', 'enhance_prompt', 'process_conversation',
            'sync_conversation', 'tavern.submit_character',
            'tavern.request_character_data', 'tavern.current_session',
            'sessions.stats', 'health', 'system.full_reset'
        ]
        if v not in valid_actions:
            raise ValueError(f"Invalid action: {v}")
        return v


class SystemControlRequest(BaseModel):
    """系统控制请求"""
    action: str = Field(..., min_length=1, max_length=50)
    parameters: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator('action')
    def validate_action(cls, v):
        valid_actions = ['full_reset', 'quick_reset', 'reload_config', 'health_check']
        if v not in valid_actions:
            raise ValueError(f"Invalid system action: {v}")
        return v