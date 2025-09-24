"""
自定义异常类
统一错误处理和错误码定义
"""

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(Enum):
    """错误码枚举"""
    # 通用错误 (1000-1999)
    UNKNOWN_ERROR = 1000
    INVALID_INPUT = 1001
    VALIDATION_ERROR = 1002
    PERMISSION_DENIED = 1003
    RATE_LIMIT_EXCEEDED = 1004

    # 认证和授权错误 (2000-2999)
    UNAUTHORIZED = 2000
    INVALID_API_KEY = 2001
    TOKEN_EXPIRED = 2002
    INSUFFICIENT_PERMISSIONS = 2003

    # 会话相关错误 (3000-3999)
    SESSION_NOT_FOUND = 3000
    SESSION_EXPIRED = 3001
    SESSION_CREATION_FAILED = 3002
    INVALID_SESSION_STATE = 3003
    SESSION_OPERATION_FAILED = 3004

    # LLM相关错误 (4000-4999)
    LLM_UNAVAILABLE = 4000
    LLM_REQUEST_FAILED = 4001
    LLM_TIMEOUT = 4002
    LLM_QUOTA_EXCEEDED = 4003
    INVALID_LLM_RESPONSE = 4004

    # 图谱相关错误 (5000-5999)
    GRAPH_OPERATION_FAILED = 5000
    NODE_NOT_FOUND = 5001
    EDGE_NOT_FOUND = 5002
    GRAPH_VALIDATION_ERROR = 5003
    GRAPH_SAVE_FAILED = 5004

    # 存储相关错误 (6000-6999)
    STORAGE_ERROR = 6000
    FILE_NOT_FOUND = 6001
    FILE_PERMISSION_ERROR = 6002
    DISK_SPACE_ERROR = 6003

    # WebSocket相关错误 (7000-7999)
    WEBSOCKET_CONNECTION_FAILED = 7000
    WEBSOCKET_MESSAGE_ERROR = 7001
    WEBSOCKET_TIMEOUT = 7002

    # SillyTavern集成错误 (8000-8999)
    TAVERN_CONNECTION_ERROR = 8000
    TAVERN_DATA_ERROR = 8001
    TAVERN_SYNC_ERROR = 8002


class EchoGraphException(Exception):
    """EchoGraph基础异常类"""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        details: Optional[Dict[str, Any]] = None,
        cause: Optional[Exception] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        self.cause = cause
        super().__init__(self.message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典格式"""
        result = {
            "error_code": self.error_code.value,
            "error_name": self.error_code.name,
            "message": self.message,
            "details": self.details
        }
        if self.cause:
            result["cause"] = str(self.cause)
        return result

    def __str__(self) -> str:
        return f"[{self.error_code.name}] {self.message}"


class ValidationError(EchoGraphException):
    """输入验证错误"""

    def __init__(self, message: str, field: str = None, **kwargs):
        details = kwargs.get('details', {})
        if field:
            details['field'] = field
        super().__init__(
            message,
            ErrorCode.VALIDATION_ERROR,
            details,
            kwargs.get('cause')
        )


class SessionError(EchoGraphException):
    """会话相关错误"""

    def __init__(self, message: str, session_id: str = None, **kwargs):
        details = kwargs.get('details', {})
        if session_id:
            details['session_id'] = session_id
        super().__init__(
            message,
            kwargs.get('error_code', ErrorCode.SESSION_NOT_FOUND),
            details,
            kwargs.get('cause')
        )


class LLMError(EchoGraphException):
    """LLM相关错误"""

    def __init__(self, message: str, model: str = None, **kwargs):
        details = kwargs.get('details', {})
        if model:
            details['model'] = model
        super().__init__(
            message,
            kwargs.get('error_code', ErrorCode.LLM_REQUEST_FAILED),
            details,
            kwargs.get('cause')
        )


class GraphError(EchoGraphException):
    """图谱操作错误"""

    def __init__(self, message: str, node_id: str = None, **kwargs):
        details = kwargs.get('details', {})
        if node_id:
            details['node_id'] = node_id
        super().__init__(
            message,
            kwargs.get('error_code', ErrorCode.GRAPH_OPERATION_FAILED),
            details,
            kwargs.get('cause')
        )


class StorageError(EchoGraphException):
    """存储相关错误"""

    def __init__(self, message: str, file_path: str = None, **kwargs):
        details = kwargs.get('details', {})
        if file_path:
            details['file_path'] = file_path
        super().__init__(
            message,
            kwargs.get('error_code', ErrorCode.STORAGE_ERROR),
            details,
            kwargs.get('cause')
        )


class WebSocketError(EchoGraphException):
    """WebSocket相关错误"""

    def __init__(self, message: str, connection_id: str = None, **kwargs):
        details = kwargs.get('details', {})
        if connection_id:
            details['connection_id'] = connection_id
        super().__init__(
            message,
            kwargs.get('error_code', ErrorCode.WEBSOCKET_CONNECTION_FAILED),
            details,
            kwargs.get('cause')
        )


class TavernError(EchoGraphException):
    """SillyTavern集成错误"""

    def __init__(self, message: str, character_id: str = None, **kwargs):
        details = kwargs.get('details', {})
        if character_id:
            details['character_id'] = character_id
        super().__init__(
            message,
            kwargs.get('error_code', ErrorCode.TAVERN_CONNECTION_ERROR),
            details,
            kwargs.get('cause')
        )


# 错误消息模板
ERROR_MESSAGES = {
    ErrorCode.SESSION_NOT_FOUND: "会话 {session_id} 不存在",
    ErrorCode.LLM_UNAVAILABLE: "LLM服务当前不可用",
    ErrorCode.GRAPH_OPERATION_FAILED: "图谱操作失败: {operation}",
    ErrorCode.INVALID_API_KEY: "API密钥无效或格式错误",
    ErrorCode.VALIDATION_ERROR: "输入验证失败: {field}",
    ErrorCode.STORAGE_ERROR: "存储操作失败: {file_path}",
    ErrorCode.WEBSOCKET_CONNECTION_FAILED: "WebSocket连接失败",
    ErrorCode.TAVERN_CONNECTION_ERROR: "SillyTavern连接错误"
}


def get_error_message(error_code: ErrorCode, **kwargs) -> str:
    """获取格式化的错误消息"""
    template = ERROR_MESSAGES.get(error_code, "未知错误")
    try:
        return template.format(**kwargs)
    except KeyError:
        return template