"""
安全中间件
提供CORS、安全头、输入验证等安全功能
"""

import time
from typing import Callable
from fastapi import Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from loguru import logger

from ..utils.security import get_security_manager
from ..utils.exceptions import EchoGraphException, ErrorCode


class SecurityMiddleware(BaseHTTPMiddleware):
    """安全中间件"""

    def __init__(self, app, enable_rate_limiting: bool = True, max_requests_per_minute: int = 60):
        super().__init__(app)
        self.security_manager = get_security_manager()
        self.enable_rate_limiting = enable_rate_limiting
        self.max_requests_per_minute = max_requests_per_minute
        self.rate_limit_storage = {}  # 简单的内存存储，生产环境应使用Redis

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        try:
            # 1. 速率限制检查
            if self.enable_rate_limiting:
                await self._check_rate_limit(request)

            # 2. 输入验证
            await self._validate_request(request)

            # 3. 处理请求
            response = await call_next(request)

            # 4. 添加安全头
            self._add_security_headers(response)

            # 5. 记录访问日志
            process_time = time.time() - start_time
            self._log_request(request, response, process_time)

            return response

        except EchoGraphException as e:
            logger.error(f"Security middleware error: {e}")
            raise HTTPException(status_code=400, detail=e.to_dict())
        except Exception as e:
            logger.error(f"Unexpected error in security middleware: {e}")
            raise HTTPException(status_code=500, detail="Internal server error")

    async def _check_rate_limit(self, request: Request):
        """检查速率限制"""
        client_ip = request.client.host
        current_time = time.time()
        minute_key = f"{client_ip}:{int(current_time // 60)}"

        # 清理过期的记录
        expired_keys = [key for key in self.rate_limit_storage.keys()
                       if int(key.split(':')[1]) < int(current_time // 60) - 1]
        for key in expired_keys:
            del self.rate_limit_storage[key]

        # 检查当前分钟的请求数
        current_requests = self.rate_limit_storage.get(minute_key, 0)
        if current_requests >= self.max_requests_per_minute:
            logger.warning(f"Rate limit exceeded for IP {client_ip}")
            raise EchoGraphException(
                "请求过于频繁，请稍后再试",
                ErrorCode.RATE_LIMIT_EXCEEDED,
                {"client_ip": client_ip, "limit": self.max_requests_per_minute}
            )

        # 增加请求计数
        self.rate_limit_storage[minute_key] = current_requests + 1

    async def _validate_request(self, request: Request):
        """验证请求"""
        # 检查请求大小
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > 10_000_000:  # 10MB限制
            raise EchoGraphException(
                "请求体过大",
                ErrorCode.VALIDATION_ERROR,
                {"max_size": "10MB", "received_size": content_length}
            )

        # 检查User-Agent
        user_agent = request.headers.get('user-agent', '')
        if not user_agent or len(user_agent) > 512:
            logger.warning(f"Suspicious user agent: {user_agent[:100]}")

        # 检查可疑的查询参数
        for param, value in request.query_params.items():
            if len(str(value)) > 1000:
                raise EchoGraphException(
                    f"查询参数 {param} 值过长",
                    ErrorCode.VALIDATION_ERROR,
                    {"parameter": param, "max_length": 1000}
                )

    def _add_security_headers(self, response: Response):
        """添加安全HTTP头"""
        security_headers = self.security_manager.secure_headers()
        for header, value in security_headers.items():
            response.headers[header] = value

        # 添加自定义头
        response.headers["X-API-Version"] = "1.0.0"
        response.headers["X-Server"] = "EchoGraph"

    def _log_request(self, request: Request, response: Response, process_time: float):
        """记录请求日志"""
        client_ip = request.client.host
        method = request.method
        url = str(request.url)
        status_code = response.status_code
        user_agent = request.headers.get('user-agent', 'Unknown')

        logger.info(
            f"{client_ip} - \"{method} {url}\" {status_code} - "
            f"{process_time:.3f}s - \"{user_agent[:100]}\""
        )

        # 记录慢请求
        if process_time > 2.0:
            logger.warning(f"Slow request detected: {method} {url} took {process_time:.3f}s")


def setup_cors_middleware(app, allowed_origins: list):
    """设置CORS中间件"""
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-API-Version", "X-Server"]
    )
    logger.info(f"CORS middleware configured with origins: {allowed_origins}")


def setup_security_middleware(app, enable_rate_limiting: bool = True, max_requests_per_minute: int = 60):
    """设置安全中间件"""
    app.add_middleware(
        SecurityMiddleware,
        enable_rate_limiting=enable_rate_limiting,
        max_requests_per_minute=max_requests_per_minute
    )
    logger.info(f"Security middleware configured (rate limiting: {enable_rate_limiting})")


class LoggingMiddleware(BaseHTTPMiddleware):
    """请求日志中间件"""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()

        # 记录请求开始
        request_id = self._generate_request_id()
        logger.debug(f"[{request_id}] Request started: {request.method} {request.url}")

        try:
            response = await call_next(request)
            process_time = time.time() - start_time

            # 记录请求完成
            logger.debug(
                f"[{request_id}] Request completed: {response.status_code} "
                f"in {process_time:.3f}s"
            )

            # 添加请求ID到响应头
            response.headers["X-Request-ID"] = request_id

            return response

        except Exception as e:
            process_time = time.time() - start_time
            logger.error(
                f"[{request_id}] Request failed: {str(e)} "
                f"after {process_time:.3f}s"
            )
            raise

    def _generate_request_id(self) -> str:
        """生成请求ID"""
        import uuid
        return str(uuid.uuid4())[:8]


def setup_logging_middleware(app):
    """设置日志中间件"""
    app.add_middleware(LoggingMiddleware)
    logger.info("Logging middleware configured")