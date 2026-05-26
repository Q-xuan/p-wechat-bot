"""
platforms/base.py — 平台适配器基类

所有平台（Mimo/MiniMax/DeepSeek）都遵循同一接口：
- get_reply(prompt, options) -> str
- build_tools() -> List[Dict]
- get_system_prompt_base() -> str
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Callable, Optional


class BasePlatform(ABC):
    """平台适配器抽象基类"""

    def __init__(
        self,
        api_key: str,
        model: str,
        system_message: str = "",
        base_url: Optional[str] = None,
        compress_fn: Optional[Callable] = None,
        reasoning_field: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.system_message = system_message
        self.base_url = base_url
        self.compress_fn = compress_fn
        self.reasoning_field = reasoning_field  # 推理模型的 reasoning 字段名

    @abstractmethod
    async def get_reply(
        self,
        prompt: str,
        options: Dict[str, Any],
    ) -> str:
        """执行一次对话（ReAct 循环调用）"""
        pass

    def build_system_prompt(self, room_name: str = "", asker_name: str = "") -> str:
        """构建带上下文的 system prompt"""
        extra = ""
        if room_name:
            extra += f"\n当前所在群：「{room_name}」（查该群消息时 room 参数填\"{room_name}\"）"
        if asker_name:
            extra += f"\n提问者：{asker_name}"
        extra += """

🛠️ 工具使用规则（重要）：
【queryWechat】—— 只有当你需要查"谁说了什么"、"群里在聊什么"、"某话题的讨论"时才用。
不需要查聊天记录时（如闲聊、回答常识、写作等）直接回复，不要调用工具。

【触发词判断】—— 以下场景必须用 queryWechat：
  - "群里/群里谁..."、"@某人说了什么"、"查一下..."、"统计..."
  - "有人提到..."、"说说关于..."、"大家觉得..."、"昨天/上周群里..."
  - "发言记录"、"聊天记录"、"多少人说过"

【mode 参数】：统计→stats，搜索→search，分析→detail，找图片→images（默认 search）
【重要】：queryWechat 结果已自动压缩，无需再调用任何优化工具。
【禁止】：不要在回复末尾加上"已查询微信消息"等说明。

【回答规范】：当你用 queryWechat 查完聊天记录后，必须基于查到的内容**直接回答用户的问题**，而不仅仅是汇报查到了什么。
"""
        return self.system_message + extra
