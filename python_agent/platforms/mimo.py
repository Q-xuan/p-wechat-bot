"""
platforms/mimo.py — Xiaomi MiMo 适配器

配置（从环境变量读取）：
  MIMO_API_KEY / MIMO_BASE_URL / MIMO_MODEL / MIMO_SYSTEM_MESSAGE
  模型：mimo-v2.5-pro（推理模型，必须回传 reasoning_content）
"""

import os
from typing import Any, Dict, List

from openai import AsyncOpenAI

from .base import BasePlatform


def _extract_reasoning(msg: Dict[str, Any]) -> str:
    """提取 reasoning_content（MiMo 推理模型）"""
    return msg.get("reasoning_content") or ""


class MimoPlatform(BasePlatform):
    """MiMo 推理模型平台"""

    def __init__(self):
        base_url = os.getenv("MIMO_BASE_URL", "https://api.xiaomimimo.com/v1")
        model = os.getenv("MIMO_MODEL", "mimo-v2.5-pro")
        system_message = os.getenv(
            "MIMO_SYSTEM_MESSAGE",
            "你是黑瑞，微信里的毒舌损友。风格：毒舌、调侃、幽默，该损就损。"
        )
        super().__init__(
            api_key=os.getenv("MIMO_API_KEY", ""),
            model=model,
            system_message=system_message,
            base_url=base_url,
            reasoning_field="reasoning_content",
        )
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)

    async def get_reply(
        self,
        messages: List[Dict[str, Any]],
        model: str,
        tools: List[Dict],
        **kwargs,
    ) -> Dict[str, Any]:
        """调用 MiMo API"""
        return await self.client.chat.completions.create(
            model=model,
            messages=messages,
            tools=tools if tools else None,
            tool_choice="auto",
            extra_body={} if self.reasoning_field else {},
        )

    @property
    def extract_reasoning(self) -> callable:
        return _extract_reasoning
