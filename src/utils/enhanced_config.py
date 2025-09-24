"""
增强的配置管理模块
支持环境变量验证、配置验证和安全处理
"""

import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel, validator, Field
from typing import Optional, Dict, Any, List
from loguru import logger

from .security import SecurityManager, validate_cors_origins
from .exceptions import ValidationError, ErrorCode


# 强制加载.env文件，覆盖系统环境变量
env_file = Path('.env')
if env_file.exists():
    load_dotenv(env_file, override=True)
else:
    load_dotenv(override=True)


class LLMConfig(BaseModel):
    """LLM配置"""
    provider: str = "openai"
    model: str = "deepseek-v3.1"
    stream: bool = False  # 默认不使用流式输出
    max_tokens: int = Field(default=16000, ge=1, le=32000)
    temperature: float = Field(default=0.8, ge=0.0, le=2.0)
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    request_timeout: int = Field(default=180, ge=10, le=600)  # 10秒到10分钟

    @validator('api_key')
    def validate_api_key(cls, v):
        if v:
            security_manager = SecurityManager()
            if not security_manager.validate_api_key_format(v):
                raise ValueError("Invalid API key format")
        return v

    @validator('base_url')
    def validate_base_url(cls, v):
        if v and not v.startswith(('http://', 'https://')):
            raise ValueError("Base URL must start with http:// or https://")
        return v


class MemoryConfig(BaseModel):
    """记忆系统配置"""
    max_hot_memory: int = Field(default=5, ge=1, le=50)
    max_context_length: int = Field(default=3000, ge=100, le=32000)
    enable_auto_save: bool = True
    save_interval: int = Field(default=300, ge=60, le=3600)  # 1分钟到1小时


class GameConfig(BaseModel):
    """游戏配置"""
    world_name: str = "默认世界"
    character_name: str = "系统"
    enable_sliding_window: bool = True
    sliding_window_size: int = Field(default=4, ge=1, le=20)
    processing_delay: int = Field(default=1, ge=0, le=60)


class SystemConfig(BaseModel):
    """系统配置"""
    name: str = "EchoGraph"
    version: str = "1.0.0"
    debug: bool = Field(default=True)
    environment: str = Field(default="development")  # development, production, testing
    allowed_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    app_secret_key: Optional[str] = None

    @validator('environment')
    def validate_environment(cls, v):
        valid_envs = ['development', 'production', 'testing']
        if v not in valid_envs:
            raise ValueError(f"Environment must be one of: {valid_envs}")
        return v


class LoggingConfig(BaseModel):
    """日志配置"""
    level: str = Field(default="INFO")
    enable_file_logging: bool = True
    log_rotation: str = "5 MB"
    log_retention: str = "7 days"
    enable_console_logging: bool = True

    @validator('level')
    def validate_log_level(cls, v):
        valid_levels = ['TRACE', 'DEBUG', 'INFO', 'SUCCESS', 'WARNING', 'ERROR', 'CRITICAL']
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()


class SecurityConfig(BaseModel):
    """安全配置"""
    enable_rate_limiting: bool = True
    max_requests_per_minute: int = Field(default=60, ge=1, le=1000)
    enable_input_sanitization: bool = True
    max_input_length: int = Field(default=10000, ge=100, le=100000)
    enable_https_only: bool = False  # 开发环境默认关闭
    session_timeout: int = Field(default=3600, ge=300, le=86400)  # 5分钟到24小时


class DatabaseConfig(BaseModel):
    """数据库配置"""
    type: str = "sqlite"  # sqlite, postgresql
    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = "echograph"
    username: Optional[str] = None
    password: Optional[str] = None
    connection_pool_size: int = Field(default=5, ge=1, le=20)

    @validator('type')
    def validate_db_type(cls, v):
        valid_types = ['sqlite', 'postgresql']
        if v not in valid_types:
            raise ValueError(f"Database type must be one of: {valid_types}")
        return v


class EnhancedConfig:
    """增强的配置管理器"""

    def __init__(self, config_path: str = "config.yaml", environment: str = None):
        self.config_path = Path(config_path)
        self.environment = environment or os.getenv('ENVIRONMENT', 'development')
        self.security_manager = SecurityManager()
        self._load_config()
        self._validate_configuration()

    def _load_config(self):
        """加载配置文件和环境变量"""
        # 1. 加载基础配置文件
        config_data = self._load_config_file()

        # 2. 根据环境加载对应的配置文件
        env_config = self._load_environment_config()
        if env_config:
            config_data = self._merge_configs(config_data, env_config)

        # 3. 应用环境变量覆盖
        config_data = self._apply_environment_overrides(config_data)

        # 4. 初始化各配置模块
        self._initialize_config_modules(config_data)

    def _load_config_file(self) -> Dict[str, Any]:
        """加载基础配置文件"""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    config_data = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {self.config_path}")
                return config_data
            except Exception as e:
                logger.error(f"Failed to load config file {self.config_path}: {e}")
                return {}
        else:
            logger.info(f"Config file {self.config_path} not found, using defaults")
            return {}

    def _load_environment_config(self) -> Optional[Dict[str, Any]]:
        """加载环境特定的配置文件"""
        env_config_path = Path(f"config/{self.environment}.yaml")
        if env_config_path.exists():
            try:
                with open(env_config_path, 'r', encoding='utf-8') as f:
                    env_config = yaml.safe_load(f) or {}
                logger.info(f"Loaded environment config from {env_config_path}")
                return env_config
            except Exception as e:
                logger.error(f"Failed to load environment config {env_config_path}: {e}")
        return None

    def _merge_configs(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """递归合并配置字典"""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._merge_configs(result[key], value)
            else:
                result[key] = value
        return result

    def _apply_environment_overrides(self, config_data: Dict[str, Any]) -> Dict[str, Any]:
        """应用环境变量覆盖"""
        # LLM配置环境变量覆盖
        llm_config = config_data.get('llm', {})
        llm_config['api_key'] = os.getenv('OPENAI_API_KEY', llm_config.get('api_key'))

        # 设置默认的外部API服务器地址
        default_base_url = "https://api.deepseek.com/v1"
        llm_config['base_url'] = os.getenv('OPENAI_API_BASE_URL',
                                         llm_config.get('base_url', default_base_url))

        # 模型名称覆盖
        if os.getenv('DEFAULT_MODEL'):
            llm_config['model'] = os.getenv('DEFAULT_MODEL')

        # 流式输出配置
        stream_env = os.getenv('LLM_STREAM_OUTPUT', 'false').lower()
        if stream_env in ('true', '1', 't'):
            llm_config['stream'] = True

        config_data['llm'] = llm_config

        # 系统配置环境变量覆盖
        system_config = config_data.get('system', {})
        system_config['debug'] = os.getenv('DEBUG', str(system_config.get('debug', True))).lower() == 'true'
        system_config['environment'] = self.environment
        system_config['allowed_origins'] = os.getenv('ALLOWED_ORIGINS',
                                                    system_config.get('allowed_origins', ''))
        system_config['app_secret_key'] = os.getenv('APP_SECRET_KEY',
                                                   system_config.get('app_secret_key'))
        config_data['system'] = system_config

        # 日志配置环境变量覆盖
        logging_config = config_data.get('logging', {})
        logging_config['level'] = os.getenv('LOG_LEVEL', logging_config.get('level', 'INFO'))
        config_data['logging'] = logging_config

        return config_data

    def _initialize_config_modules(self, config_data: Dict[str, Any]):
        """初始化各配置模块"""
        try:
            self.system = SystemConfig(**config_data.get('system', {}))
            self.logging = LoggingConfig(**config_data.get('logging', {}))
            self.llm = LLMConfig(**config_data.get('llm', {}))
            self.memory = MemoryConfig(**config_data.get('memory', {}))
            self.game = GameConfig(**config_data.get('game', {}))
            self.security = SecurityConfig(**config_data.get('security', {}))
            self.database = DatabaseConfig(**config_data.get('database', {}))
        except Exception as e:
            logger.error(f"Configuration validation failed: {e}")
            raise ValidationError(f"Invalid configuration: {e}", error_code=ErrorCode.VALIDATION_ERROR)

    def _validate_configuration(self):
        """验证配置的完整性和合理性"""
        errors = []

        # 验证LLM配置
        if not self.llm.api_key:
            errors.append("LLM API key is required")

        if not self.llm.base_url:
            errors.append("LLM base URL is required")

        # 在生产环境中进行额外验证
        if self.system.environment == 'production':
            if self.system.debug:
                errors.append("Debug mode should be disabled in production")

            if '*' in self.system.allowed_origins:
                errors.append("Wildcard CORS origins not allowed in production")

            if not self.security.enable_https_only:
                logger.warning("HTTPS enforcement disabled in production environment")

        if errors:
            error_msg = "; ".join(errors)
            logger.error(f"Configuration validation failed: {error_msg}")
            raise ValidationError(error_msg, error_code=ErrorCode.VALIDATION_ERROR)

        logger.info("Configuration validation passed")

    def get_cors_origins(self) -> List[str]:
        """获取验证后的CORS源列表"""
        return validate_cors_origins(self.system.allowed_origins)

    def is_development(self) -> bool:
        """检查是否为开发环境"""
        return self.system.environment == 'development'

    def is_production(self) -> bool:
        """检查是否为生产环境"""
        return self.system.environment == 'production'

    def get_masked_api_key(self) -> str:
        """获取掩码后的API密钥用于日志"""
        return self.security_manager.hash_api_key(self.llm.api_key)

    def reload(self):
        """重新加载配置"""
        logger.info("Reloading configuration...")
        self._load_config()
        self._validate_configuration()
        logger.info("Configuration reloaded successfully")


# 全局配置实例
config = EnhancedConfig()


def get_config() -> EnhancedConfig:
    """获取全局配置实例"""
    return config


def reload_config():
    """重新加载全局配置"""
    global config
    config.reload()