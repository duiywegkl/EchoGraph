"""
API响应数据模型
定义所有API端点的响应格式
"""

from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from datetime import datetime


class BaseResponse(BaseModel):
    """基础响应模型"""
    success: bool = True
    message: str = ""
    timestamp: datetime = Field(default_factory=datetime.now)


class InitializeResponse(BaseResponse):
    """会话初始化响应"""
    session_id: str
    graph_stats: Dict[str, Any] = Field(default_factory=dict)
    processing_time: Optional[float] = None
    nodes_added: Optional[int] = None
    edges_added: Optional[int] = None


class AsyncInitializeResponse(BaseResponse):
    """异步初始化响应"""
    task_id: str
    estimated_time: str


class InitTaskStatusResponse(BaseModel):
    """初始化任务状态响应"""
    task_id: str
    status: str
    progress: float = Field(ge=0.0, le=1.0)
    message: str
    session_id: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str
    updated_at: str


class EnhancePromptResponse(BaseResponse):
    """增强提示词响应"""
    enhanced_context: str
    entities_found: List[str] = Field(default_factory=list)
    context_stats: Dict[str, Any] = Field(default_factory=dict)


class UpdateMemoryResponse(BaseResponse):
    """更新记忆响应"""
    nodes_updated: int = 0
    edges_added: int = 0
    processing_stats: Dict[str, Any] = Field(default_factory=dict)


class ProcessConversationResponse(BaseResponse):
    """滑动窗口对话处理响应"""
    turn_sequence: int
    turn_processed: bool
    target_processed: bool
    window_size: int
    nodes_updated: int = 0
    edges_added: int = 0
    conflicts_resolved: int = 0
    processing_stats: Dict[str, Any] = Field(default_factory=dict)


class SyncConversationResponse(BaseResponse):
    """同步对话响应"""
    conflicts_detected: int
    conflicts_resolved: int
    window_synced: bool


class SessionStatsResponse(BaseModel):
    """会话统计响应"""
    session_id: str
    graph_nodes: int
    graph_edges: int
    hot_memory_size: int
    last_update: Optional[str] = None
    sliding_window_size: Optional[int] = None
    processed_turns: Optional[int] = None
    window_capacity: Optional[int] = None
    processing_delay: Optional[int] = None


class GraphStatusResponse(BaseModel):
    """图谱状态响应"""
    session_id: str
    total_nodes: int
    total_edges: int
    recent_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    timestamp: float


class SubmitCharacterDataResponse(BaseResponse):
    """提交角色数据响应"""
    character_id: str


class TavernMessageResponse(BaseModel):
    """酒馆消息处理响应"""
    enhanced_context: Optional[str] = None
    nodes_updated: int = 0
    edges_added: int = 0
    status: str = "success"
    error: Optional[str] = None


class NodeOperationResponse(BaseResponse):
    """节点操作响应"""
    node_name: str
    node_type: str
    total_nodes: int
    total_edges: int


class EdgeOperationResponse(BaseResponse):
    """关系操作响应"""
    source: str
    target: str
    relationship: str
    total_edges: int


class WebSocketResponse(BaseModel):
    """WebSocket响应"""
    type: str = "response"
    action: str
    request_id: Optional[str] = None
    ok: bool = True
    data: Optional[Dict[str, Any]] = None
    error: Optional[Dict[str, Any]] = None


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = False
    error_code: int
    error_name: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthCheckResponse(BaseModel):
    """健康检查响应"""
    status: str = "healthy"
    version: str
    active_sessions: int
    agent_enabled_sessions: int
    local_processor_sessions: int
    websocket_connections: int
    llm_configured: bool
    storage_path: str
    total_characters: int
    timestamp: datetime = Field(default_factory=datetime.now)


class SystemResetResponse(BaseResponse):
    """系统重置响应"""
    cleared_counts: Dict[str, int] = Field(default_factory=dict)


class CharacterExistsResponse(BaseModel):
    """角色存在检查响应"""
    exists: bool
    session_id: str
    character_name: str
    node_count: Optional[int] = None
    edge_count: Optional[int] = None
    graph_file_exists: Optional[bool] = None
    entities_file_exists: Optional[bool] = None


class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[Dict[str, Any]]
    total_sessions: int


class CharacterListResponse(BaseModel):
    """角色列表响应"""
    characters: List[Dict[str, Any]]
    total_count: int


class ActiveSessionsResponse(BaseModel):
    """活跃会话响应"""
    sessions: List[Dict[str, Any]]
    total_count: int


class CurrentTavernSessionResponse(BaseModel):
    """当前酒馆会话响应"""
    has_session: bool
    session_id: Optional[str] = None
    character_name: Optional[str] = None
    graph_nodes: Optional[int] = None
    graph_edges: Optional[int] = None
    message: str


class ExportResponse(BaseModel):
    """导出响应"""
    session_id: str
    export_timestamp: str
    graph_stats: Dict[str, int]
    graph_data: Dict[str, Any]


class CleanupResponse(BaseResponse):
    """清理响应"""
    cleaned_count: int
    cleaned_sessions: List[Dict[str, Any]] = Field(default_factory=list)