"""
agent/core.py — Python Agent 核心（ReAct 循环）

对标 Node.js agent-core/index.js 的 createAgent()

功能：
- ReAct 循环（最多 3 轮工具调用）
- withRetry 指数退避重试
- Session 持久化
- 工具注册表 + 执行器
- markdown 清理
"""

import logging
import re
import asyncio
from typing import Any, Dict, List, Optional

from .compression import smart_compress
from .session import load_session, save_session, extract_dialog_turns
from ..tools.registry import TOOLS, execute_tool

log = logging.getLogger(__name__)

# ============================================================
# Markdown 处理
# ============================================================

def clean_reply(raw: str) -> str:
    """清理 AI 回复中的各种格式，输出纯文本"""
    if not raw:
        return ""
    text = re.sub(r"<think>[\s\S]*?<\/think>", "", raw)
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"`{1,3}(.+?)`{1,3}", r"\1", text, flags=re.DOTALL)
    text = re.sub(r"^---+$", "", text, flags=re.MULTILINE)
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    return text.strip()

# ============================================================
# 带指数退避的重试
# ============================================================

async def with_retry(fn, *args, max_retries: int = 3, base_delay: float = 1.0, **kwargs):
    """
    带指数退避的重试封装

    Args:
        fn: 要执行的异步函数
        max_retries: 最大重试次数（默认 3）
        base_delay: 基础延迟秒数（默认 1.0）
    """
    last_error = None
    retryable_errors = [429, 500, 502, 503, 504]

    for attempt in range(max_retries):
        try:
            return await fn(*args, **kwargs)
        except Exception as err:
            last_error = err
            is_retryable = (
                getattr(err, "status", None) in retryable_errors
                or "timeout" in str(err).lower()
                or "rate limit" in str(err).lower()
                or "connection" in str(err).lower()
            )
            if is_retryable and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)
                log.info(f"🔁 API 重试 {attempt + 1}/{max_retries}，{delay}s 后重试...")
                await asyncio.sleep(delay)
                continue
            raise
    raise last_error

# ============================================================
# Agent 工厂
# ============================================================

def create_agent(platform, *, system_prompt_base: str = "", compress_fn=None):
    """
    构建 Agent 实例

    Args:
        platform: 平台适配器实例（Mimo/MiniMax/DeepSeek）
        system_prompt_base: 基础 system prompt
        compress_fn: 压缩函数（默认 smart_compress）

    Returns:
        async function get_reply(prompt, options) -> str
    """
    if compress_fn is None:
        compress_fn = smart_compress

    async def get_reply(
        prompt: str,
        opts: Optional[Dict[str, Any]] = None,
    ) -> str:
        opts = opts or {}
        room_name = opts.get("roomName", "")
        asker_name = opts.get("askerName", "")
        session_id = opts.get("sessionId", "")

        # 构建 system prompt
        system_extra = ""
        if room_name:
            system_extra += f"\n当前所在群：「{room_name}」（查该群消息时 room 参数填\"{room_name}\"）"
        if asker_name:
            system_extra += f"\n提问者：{asker_name}"
        system_extra += """

🛠️ 工具使用规则（重要）：
【queryWechat】—— 只有当你需要查"谁说了什么"、"群里在聊什么"、"某话题的讨论"时才用。
不需要查聊天记录时（如闲聊、回答常识、写作等）直接回复，不要调用工具。

【触发词判断】—— 以下场景必须用 queryWechat：
  - "群里/群里谁..."、"@某人说了什么"、"查一下..."、"统计..."
  - "有人提到..."、"说说关于..."、"大家觉得..."、"昨天/上周群里..."
  - "发言记录"、"聊天记录"、"多少人说过"

【mode 参数选择】：
  - 想了解"谁发言多、活跃时段"等统计 → mode='stats'
  - 想找"包含某关键词的消息" → mode='search'（必须传 query 参数）
  - 想分析"某人说的话有什么特点" → mode='detail'
  - 想找"图片/视频/附件" → mode='images'

【重要】：queryWechat 结果已自动压缩，无需再调用任何优化工具。
【禁止】：不要在回复末尾加上"已查询微信消息"等说明。
"""
        full_system = system_prompt_base + system_extra

        log.info(f"🚀🚀🚀 / {prompt[:60]} | room: {room_name} | asker: {asker_name}")

        # 从 session 恢复对话历史
        turns = load_session(session_id)
        messages = []
        if not turns:
            messages.append({"role": "system", "content": full_system})
        else:
            system_turn = next((t for t in turns if t.get("role") == "system"), None)
            if system_turn:
                messages.append({"role": "system", "content": system_turn["content"]})
            else:
                messages.append({"role": "system", "content": full_system})
            for t in turns[1:]:
                messages.append(t)

        # 追加当前用户消息
        messages.append({"role": "user", "content": prompt})

        # ReAct 循环：最多 3 轮
        for round_num in range(3):
            response = await with_retry(
                platform.get_reply,
                messages=messages,
                model=platform.model,
                tools=TOOLS,
                max_retries=3,
                base_delay=1.0,
            )

            msg = response.choices[0].message

            # 推理内容（如果平台有）
            reasoning_content = ""
            if hasattr(platform, "extract_reasoning"):
                reasoning_content = platform.extract_reasoning(msg.model_dump() if hasattr(msg, "model_dump") else {})

            # 无工具调用 → 最终回复
            if not msg.tool_calls or len(msg.tool_calls) == 0:
                reply = clean_reply(msg.content or "")
                messages.append({"role": "assistant", "content": reply})
                save_session(session_id, extract_dialog_turns(messages))
                return reply

            # 有工具调用 → 顺序执行
            for tc in msg.tool_calls:
                fn = tc.function
                try:
                    args = fn.arguments if isinstance(fn.arguments, dict) else {}
                except Exception:
                    args = {}

                log.info(f"🔧 [{round_num}] {fn.name} {args}")

                result = await execute_tool(fn.name, args)

                # 注入 assistant 消息（含推理内容）
                assistant_msg: Dict[str, Any] = {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {"name": fn.name, "arguments": fn.arguments if isinstance(fn.arguments, str) else str(fn.arguments)},
                        }
                    ],
                }
                if reasoning_content:
                    assistant_msg["reasoning_content"] = reasoning_content
                messages.append(assistant_msg)
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

        # 超轮数限制
        last = messages[-1]
        fallback = last.get("content", "")[:300] if isinstance(last.get("content"), str) else "...处理超时"
        save_session(session_id, extract_dialog_turns(messages))
        return fallback

    return get_reply
