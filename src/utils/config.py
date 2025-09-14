import os
import yaml
from pathlib import Path
from dotenv import load_dotenv
from pydantic import BaseModel
from typing import Optional

# 强制加载.env文件，覆盖系统环境变量
env_file = Path('.env')
if env_file.exists():
    load_dotenv(env_file, override=True)
else:
    load_dotenv(override=True)

class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "deepseek-v3.1"
    stream: bool = False # 默认不使用流式输出
    max_tokens: int = 16000
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
    name: str = "ChronoForge"
    version: str = "0.1.0"
    debug: bool = True

class Config:
    def __init__(self, config_path: str = "config.yaml"):
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
        # 从环境变量读取流式输出配置
        stream_env = os.getenv('LLM_STREAM_OUTPUT', 'false').lower()
        if stream_env in ('true', '1', 't'):
            llm_config['stream'] = True
        
        self.system = SystemConfig(**config_data.get('system', {}))
        self.llm = LLMConfig(**llm_config)
        self.memory = MemoryConfig(**config_data.get('memory', {}))
        self.game = GameConfig(**config_data.get('game', {}))

# 全局配置实例
config = Config()
