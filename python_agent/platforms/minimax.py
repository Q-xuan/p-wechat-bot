"""
platforms/minimax.py — MiniMax 适配器

配置（从环境变量读取）：
  MINIMAX_API_KEY / MINIMAX_BASE_URL / MINIMAX_MODEL / MINIMAX_SYSTEM_MESSAGE
"""

import os
from typing import Any, Dict, List

from openai import AsyncOpenAI

from .base import BasePlatform


class MiniMaxPlatform(BasePlatform):
    """MiniMax 平台"""

    def __init__(self):
        base_url = os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1")
        model = os.getenv("MINIMAX_MODEL", "MiniMax-M2.5")
        system_message = os.getenv(
            "MINIMAX_SYSTEM_MESSAGE",
            "你是\"黑瑞\"，微信里的毒舌损友。"
        )
        super().__init__(
            api_key=os.getenv("MINIMAX_API_KEY", ""),
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
        """调用 MiniMax API"""
        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto",
        )
