import os
import yaml
from pathlib import Path
from dotenv import dotenv_values
from threading import RLock
from pydantic import BaseModel
from typing import Optional

env_file = Path(__file__).resolve().parents[2] / '.env'
_reload_lock = RLock()
_loaded_env_keys = set()
_env_mtime_ns = None


def _load_file_environment(path=None):
    """For keys present in the repository .env, file values win over inherited environment."""
    global _loaded_env_keys, _env_mtime_ns
    path = Path(path) if path is not None else env_file
    values = dotenv_values(path) if path.is_file() else {}
    for key in _loaded_env_keys - values.keys():
        os.environ.pop(key, None)
    for key, value in values.items():
        os.environ[key] = value if value is not None else ""
    _loaded_env_keys = set(values)
    _env_mtime_ns = path.stat().st_mtime_ns if path.is_file() else None


_load_file_environment()

class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "deepseek-v3.1"
    stream: bool = False # 默认不使用流式输出
    max_tokens: int = 4000
    temperature: float = 0.8
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    request_timeout: int = 180  # 默认超时时间为180秒

class MemoryConfig(BaseModel):
    max_hot_memory: int = 5
    max_context_length: int = 3000

class GameConfig(BaseModel):
    world_name: str = "默认世界"
    character_name: str = "系统"

class SystemConfig(BaseModel):
    name: str = "EchoGraph"
    version: str = "1.0.0"
    debug: bool = True

class LoggingConfig(BaseModel):
    level: str = "INFO"

class Config:
    def __init__(self, config_path=None):
        if config_path is None:
            config_path = env_file.parent / "config.yaml"
        self.config_path = Path(config_path)
        self._load_config()
    
    def _load_config(self):
        if self.config_path.exists():
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
        else:
            config_data = {}
        
        # 从环境变量获取API密钥、基础URL和模型名称
        llm_config = config_data.get('llm', {})
        llm_config['api_key'] = os.getenv('OPENAI_API_KEY')
        
        # 设置默认的外部API服务器地址，不指向本地服务器
        default_base_url = "https://api.deepseek.com/v1"  # 默认使用DeepSeek API
        llm_config['base_url'] = os.getenv('OPENAI_API_BASE_URL', default_base_url)
        
        # 环境变量中的模型名称优先级最高
        if os.getenv('DEFAULT_MODEL'):
            llm_config['model'] = os.getenv('DEFAULT_MODEL')
        if os.getenv('MAX_TOKENS'):
            llm_config['max_tokens'] = int(os.environ['MAX_TOKENS'])
        # 从环境变量读取流式输出配置
        stream_env = os.getenv('LLM_STREAM_OUTPUT', 'false').lower()
        if stream_env in ('true', '1', 't'):
            llm_config['stream'] = True
        
        self.system = SystemConfig(**config_data.get('system', {}))
        self.logging = LoggingConfig(**config_data.get('logging', {}))
        self.llm = LLMConfig(**llm_config)
        self.memory = MemoryConfig(**config_data.get('memory', {}))
        self.game = GameConfig(**config_data.get('game', {}))

# 全局配置实例
config = Config()


def reload_config(path=None):
    """Reload the repository .env and update the existing singleton in place.

    Values explicitly present in .env override inherited process variables and
    are copied into os.environ. Absent keys retain their external values, except
    keys removed from .env since the previous load.
    """
    with _reload_lock:
        _load_file_environment(path)
        fresh = Config(config.config_path)
        for name in ("system", "logging", "llm", "memory", "game"):
            getattr(config, name).__dict__.update(getattr(fresh, name).__dict__)
        return config


def reload_config_if_changed():
    """Stat only; parse and rebuild when the .env timestamp changes."""
    mtime = env_file.stat().st_mtime_ns if env_file.is_file() else None
    if mtime != _env_mtime_ns:
        return reload_config()
    return config
