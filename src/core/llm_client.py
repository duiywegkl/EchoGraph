from typing import List, Dict, Any, Optional, Iterator
import openai
from loguru import logger
from src.utils.config import config

class LLMClient:
    def __init__(self):
        self.client = openai.OpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url
        )
        self.model = config.llm.model
        self.max_tokens = config.llm.max_tokens
        self.temperature = config.llm.temperature
    
    def chat(self, messages: List[Dict[str, str]], **kwargs) -> str:
        """单次LLM调用 - 严格JSON模式"""
        try:
            response = self.client.chat.completions.create(
                model=kwargs.get('model', self.model),
                messages=messages,
                max_tokens=kwargs.get('max_tokens', self.max_tokens),
                temperature=kwargs.get('temperature', self.temperature),
                timeout=config.llm.request_timeout,
                response_format={"type": "json_object"} # 启用JSON模式
            )
            content = response.choices[0].message.content
            logger.info(f"LLM调用成功，返回{len(content)}字符")
            return content
        except Exception as e:
            logger.error(f"LLM调用失败: {e}")
            return "抱歉，系统暂时无法响应。"

    def generate_response(self, prompt: str, max_tokens: int = None, temperature: float = None, system_message: str = None) -> str:
        """
        兼容GRAG Agent调用的统一接口
        将单个prompt转换为消息格式进行调用
        """
        messages = []
        
        if system_message:
            messages.append({"role": "system", "content": system_message})
            
        messages.append({"role": "user", "content": prompt})
        
        return self.chat(
            messages=messages,
            max_tokens=max_tokens or self.max_tokens,
            temperature=temperature or self.temperature
        )
