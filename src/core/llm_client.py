from typing import List, Dict, Any, Optional, Iterator
from dataclasses import dataclass
import openai
from loguru import logger
from src.utils.config import config

@dataclass(frozen=True)
class ChatResult:
    content: str
    finish_reason: str | None


class LLMClient:
    def __init__(self):
        self.client = openai.OpenAI(
            api_key=config.llm.api_key,
            base_url=config.llm.base_url
        )
        self.model = config.llm.model
        self.temperature = config.llm.temperature

    def chat(self, messages: List[Dict[str, str]], json_mode: bool = False, **kwargs) -> str:
        return self.chat_with_metadata(messages, json_mode=json_mode, **kwargs).content

    def chat_with_metadata(self, messages: List[Dict[str, str]], json_mode: bool = False, **kwargs) -> ChatResult:
        """单次LLM调用，支持按需开启JSON模式。"""
        try:
            value = kwargs.get('max_tokens')
            token_display = value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else '未设置'
            # 记录调用参数和关键信息（不记录API密钥）
            try:
                sys_msgs = [m for m in messages if m.get('role') == 'system']
                usr_msgs = [m for m in messages if m.get('role') == 'user']
                logger.info(f"🤖 [LLM] 调用开始 | model={kwargs.get('model', self.model)} | max_tokens={token_display} | temp={kwargs.get('temperature', self.temperature)}")
                if sys_msgs:
                    logger.debug(f"[LLM] System message preview (first 300 chars):\n---\n{sys_msgs[-1].get('content','')[:300]}\n---")
                if usr_msgs:
                    logger.debug(f"[LLM] User prompt preview (first 500 chars):\n---\n{usr_msgs[-1].get('content','')[:500]}\n---")
                logger.debug(f"[LLM] Full messages: {messages}")
            except Exception:
                pass

            request_kwargs = {
                "model": kwargs.get('model', self.model),
                "messages": messages,
                "temperature": kwargs.get('temperature', self.temperature),
                "timeout": config.llm.request_timeout,
            }
            max_tokens = kwargs.get('max_tokens')
            if isinstance(max_tokens, int) and not isinstance(max_tokens, bool) and max_tokens > 0:
                request_kwargs["max_tokens"] = max_tokens
            if json_mode:
                request_kwargs["response_format"] = {"type": "json_object"}

            response = self.client.chat.completions.create(**request_kwargs)
            content = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason
            logger.info(f"🤖 [LLM] 调用成功 | 返回长度={len(content)} | finish_reason={finish_reason}")
            logger.debug(f"[LLM] Raw response preview (first 800 chars):\n---\n{content[:800]}\n---")
            logger.debug(f"[LLM] Full raw response object: {response}")
            return ChatResult(content, finish_reason)
        except Exception as e:
            logger.error(f"❌ [LLM] 调用失败: {e}")
            raise

    def generate_response(
        self,
        prompt: str,
        max_tokens: int = None,
        temperature: float = None,
        system_message: str = None,
        json_mode: bool = False,
    ) -> str:
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
            max_tokens=max_tokens,
            temperature=temperature if temperature is not None else self.temperature,
            json_mode=json_mode,
        )
