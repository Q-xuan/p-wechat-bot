"""
platforms/deepseek.py — DeepSeek 适配器

配置（从环境变量读取）：
  DEEPSEEK_API_KEY / DEEPSEEK_URL / DEEPSEEK_MODEL / DEEPSEEK_SYSTEM_MESSAGE
"""

import os
from typing import Any, Dict, List

from openai import AsyncOpenAI

from .base import BasePlatform


class DeepSeekPlatform(BasePlatform):
    """DeepSeek 平台"""

    def __init__(self):
        base_url = os.getenv("DEEPSEEK_URL", "https://api.deepseek.com/v1")
        model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
        system_message = os.getenv(
            "DEEPSEEK_SYSTEM_MESSAGE",
            "你是黑瑞，微信里的毒舌损友。风格：毒舌、调侃、幽默，该损就损。"
        )
        super().__init__(
            api_key=os.getenv("DEEPSEEK_API_KEY", ""),
            model=model,
            system_message=system_message,
            base_url=base_url,
        )
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def get_reply(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: List[Dict],
        **kwargs,
    ) -> Dict[str, Any]:
        """调用 DeepSeek API"""
        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto",
        )
