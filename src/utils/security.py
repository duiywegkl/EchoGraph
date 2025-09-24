"""
安全工具模块
提供API密钥加密、验证和其他安全功能
"""

import os
import secrets
import hashlib
from typing import Optional
from loguru import logger


class SecurityManager:
    """安全管理器，处理API密钥和敏感数据的安全处理"""

    def __init__(self):
        self.app_secret_key = self._get_or_generate_secret_key()

    def _get_or_generate_secret_key(self) -> str:
        """获取或生成应用密钥"""
        secret_key = os.getenv('APP_SECRET_KEY')
        if not secret_key:
            logger.warning("APP_SECRET_KEY not found, generating temporary key")
            # 在生产环境中，这应该从安全的地方获取
            secret_key = secrets.token_urlsafe(32)
        return secret_key

    def hash_api_key(self, api_key: str) -> str:
        """对API密钥进行哈希处理，用于日志记录"""
        if not api_key:
            return "empty"
        # 只保留前4个和后4个字符，中间用***替代
        if len(api_key) <= 8:
            return "***"
        return f"{api_key[:4]}***{api_key[-4:]}"

    def validate_api_key_format(self, api_key: str) -> bool:
        """验证API密钥格式是否合法"""
        if not api_key or not isinstance(api_key, str):
            return False

        # 基本长度检查
        if len(api_key) < 16:
            logger.warning("API key too short")
            return False

        # 检查是否包含明显的占位符
        invalid_patterns = ['your_api_key', 'placeholder', 'example', 'test']
        if any(pattern in api_key.lower() for pattern in invalid_patterns):
            logger.warning("API key appears to be a placeholder")
            return False

        return True

    def secure_headers(self) -> dict:
        """返回安全HTTP头配置"""
        return {
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "X-XSS-Protection": "1; mode=block",
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            "Content-Security-Policy": "default-src 'self'",
            "Referrer-Policy": "strict-origin-when-cross-origin"
        }

    def sanitize_input(self, input_text: str, max_length: int = 10000) -> str:
        """清理和验证输入文本"""
        if not input_text:
            return ""

        # 长度限制
        if len(input_text) > max_length:
            logger.warning(f"Input truncated from {len(input_text)} to {max_length} characters")
            input_text = input_text[:max_length]

        # 移除潜在的恶意字符
        dangerous_chars = ['<script', '</script', 'javascript:', 'data:', 'vbscript:']
        cleaned_text = input_text

        for char in dangerous_chars:
            if char.lower() in cleaned_text.lower():
                logger.warning(f"Potentially dangerous content detected and removed: {char}")
                cleaned_text = cleaned_text.replace(char, "")

        return cleaned_text.strip()

    def generate_session_token(self) -> str:
        """生成安全的会话令牌"""
        return secrets.token_urlsafe(32)


# 全局安全管理器实例
security_manager = SecurityManager()


def get_security_manager() -> SecurityManager:
    """获取安全管理器实例"""
    return security_manager


def validate_cors_origins(origins: str) -> list:
    """验证和解析CORS源配置"""
    if not origins:
        logger.warning("No CORS origins configured, using localhost only")
        return ["http://localhost:3000", "http://127.0.0.1:3000"]

    # 分割并清理源列表
    origin_list = [origin.strip() for origin in origins.split(",") if origin.strip()]

    # 验证每个源的格式
    valid_origins = []
    for origin in origin_list:
        if origin == "*":
            logger.warning("Wildcard CORS origin (*) detected - not recommended for production")
            valid_origins.append(origin)
        elif origin.startswith(("http://", "https://")):
            valid_origins.append(origin)
        else:
            logger.warning(f"Invalid CORS origin format: {origin}")

    if not valid_origins:
        logger.error("No valid CORS origins found, falling back to localhost")
        return ["http://localhost:3000"]

    logger.info(f"Configured CORS origins: {valid_origins}")
    return valid_origins