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
import json
import uuid
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from .compression import smart_compress
from .session import load_session, save_session, extract_dialog_turns
from ..tools.registry import TOOLS, execute_tool

log = logging.getLogger(__name__)

# Per-request trace context (propagates through async call chain)
_trace_vars: ContextVar[Dict[str, str]] = ContextVar("trace_vars", default={})

# ============================================================
# 安全护栏（防恶意消耗 token）
# ============================================================

# 提示词注入模式（越严格越好，但不能误伤正常对话）
_INJECTION_PATTERNS = [
    # 要求忽略/跳过系统指令
    re.compile(r"ignore\s+(all\s+)?previous|disregard\s+(all\s+)?(your|instruct)", re.I),
    # 要求扮演新角色/系统
    re.compile(r"act\s+as|pretend\s+you\s+are|you\s+are\s+now\s+|system\s*[:=]", re.I),
    # 要求以特定格式输出（绕过安全）
    re.compile(r"output\s+as\s+(raw\s+)?(json|xml|html|sql)", re.I),
    # 直接要求输出敏感内容
    re.compile(r"(给我)?完整的?\w{2,8}(论文|代码|密钥|密码)", re.I),
    # 要求生成恶意内容
    re.compile(r"(hack|exploit|sql\s*inject|xss)\s*方法", re.I),
]

# 超长请求阈值（token 估算：中文×2，英文×0.25）
_MAX_REQUEST_CHARS = 3000  # 约 6000 token


def _check_safety(prompt: str, asker_name: Optional[str] = None) -> Optional[str]:
    """
    安全检查，通过返回 None，拒绝返回错误消息。
    检测：超长请求、提示词注入、异常任务范围。
    """
    # 1. 超长请求保护
    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", prompt))
    other_chars = len(re.sub(r"[\u4e00-\u9fa5]", "", prompt))
    estimated_tokens = chinese_chars * 2 + other_chars * 0.25
    if estimated_tokens > 4000:
        return "⚠️ 输入内容过长，请精简问题（建议不超过1500字）"

    # 2. 提示词注入检测
    for pat in _INJECTION_PATTERNS:
        if pat.search(prompt):
            log.warning(f"[ANTI-INJECTION] blocked pattern: {pat.pattern} | prompt: {prompt[:80]}")
            return "⚠️ 检测到异常指令格式，已拒绝处理"

    # 3. 异常任务范围检测（如明显不是正常对话）
    if asker_name and len(prompt) > 500:
        # 检测是否在要求"写论文/文章"等超长内容（排除搜索类正常需求）
        long_content_request = (
            re.search(r"写.{0,10}(论文|毕业论文|报告|文章)", prompt) and
            len(prompt) > 800 and
            not re.search(r"搜索|查找|搜一下|帮我查", prompt)
        )
        if long_content_request:
            return "⚠️ 我只适合回答问题和搜索，不适合撰写长文（论文/报告等），请换个问题试试 😊"

    return None


# ============================================================
# 安全护栏（防恶意消耗 token）
# ============================================================

# 提示词注入模式（越严格越好，但不能误伤正常对话）
_INJECTION_PATTERNS = [
    # 要求忽略/跳过系统指令
    re.compile(r"ignore\s+(all\s+)?previous|disregard\s+(all\s+)?(your|instruct)", re.I),
    # 要求扮演新角色/系统
    re.compile(r"act\s+as|pretend\s+you\s+are|you\s+are\s+now\s+|system\s*[:=]", re.I),
    # 要求以特定格式输出（绕过安全）
    re.compile(r"output\s+as\s+(raw\s+)?(json|xml|html|sql)", re.I),
    # 直接要求输出敏感内容
    re.compile(r"(给我)?完整的?\w{2,8}(密钥|密码)", re.I),
    # 要求生成恶意内容
    re.compile(r"(hack|exploit|sql\s*inject|xss)\s*方法", re.I),
]

# 检测会触发超长回复的用户请求（直接拒绝，省 token）
_LONG_REPLY_TRIGGERS = [
    # 写任何长文（论文/报告/文章/小说等）
    (re.compile(r"写.{0,15}(论文|毕业论文|硕士论文|博士论文|研究报告?|完整代码)", re.I), "写论文这种事找导师去，别想套我 😏"),
    (re.compile(r"写.{0,10}(小说|故事|文章|散文|诗歌|歌词){5,}", re.I), "写长文我可不擅长，换个问题？🤪"),
    # 要求"完整"生成大段内容
    (re.compile(r"完整的.{0,5}(代码|项目|系统|程序|网站)", re.I), "别想套我，一行行写才是真本事 😏"),
    # 翻译整本书/整篇长文
    (re.compile(r"翻译.{0,10}(整本|全文|整篇|全书)", re.I), "翻译这么长，你是想累死我还是累死 API？ 😏"),
    # 详细分析/解读整个代码库
    (re.compile(r"详细解释.{0,10}(这个|那个|整个).{0,8}(代码库|项目|系统)", re.I), "代码库这么大，我脑子没那么大 🧠💀"),
]

# 估计触发超长回复的特征词
_LONG_REPLY_KEYWORDS = re.compile(
    r"(论文|毕业论文|硕士|博士|完整代码|整本|全书|全部|详细解释|详细说明).{0,20}"
    r"(写|生成|给出|翻译|分析|解读|实现)",
    re.I
)


def _check_safety(prompt: str, asker_name: Optional[str] = None) -> Optional[str]:
    """
    安全检查，通过返回 None，拒绝返回错误消息。
    检测：超长请求、提示词注入、异常任务范围。
    """
    # 1. 检测会触发超长回复的请求（直接拦截，省 token）
    for pat, response in _LONG_REPLY_TRIGGERS:
        if pat.search(prompt):
            log.info(f"[ANTI-ABUSE] long reply trigger matched: {pat.pattern}")
            return response

    # 2. 提示词注入检测
    for pat in _INJECTION_PATTERNS:
        if pat.search(prompt):
            log.warning(f"[ANTI-INJECTION] blocked pattern: {pat.pattern} | prompt: {prompt[:80]}")
            return "⚠️ 检测到异常指令格式，已拒绝处理"

    # 3. 超长请求保护（> 4000 token 约 2000 中文字）
    chinese_chars = len(re.findall(r"[\u4e00-\u9fa5]", prompt))
    other_chars = len(re.sub(r"[\u4e00-\u9fa5]", "", prompt))
    estimated_tokens = chinese_chars * 2 + other_chars * 0.25
    if estimated_tokens > 4000:
        return "⚠️ 输入内容过长，请精简问题（建议不超过1500字）"

    return None


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


# 回复超长截断 + 幽默拒绝
_MAX_REPLY_CHARS = 1000
_LONG_REPLY_REJECTION = "别想套我，我只会回答问题，不会写长文 😏 想聊别的吗？"

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

        # 🔒 安全护栏检查
        safety_result = _check_safety(prompt, asker_name)
        if safety_result:
            log.info(f"[{session_id[:8] if session_id else '?'}] ⛔ {safety_result}")
            return safety_result

        # 构建 system prompt（统一由 platform.build_system_prompt 管理工具规则）
        # 只传上下文信息（room/asker），工具规则由 platform 统一追加
        if room_name or asker_name:
            context_extra = ""
            if room_name:
                context_extra += f"\n当前所在群：「{room_name}」（查该群消息时 room 参数填\"{room_name}\"）"
            if asker_name:
                context_extra += f"\n提问者：{asker_name}"
        else:
            context_extra = ""

        # 调用 platform 的 build_system_prompt（它会追加完整的工具规则）
        full_system = platform.build_system_prompt(room_name, asker_name)

        # Generate trace context (propagates through async call chain)
        trace_id = str(uuid.uuid4())[:8]
        token = _trace_vars.set({"trace_id": trace_id, "session_id": session_id})

        log.info(f"[{trace_id}] 🚀 session={session_id[:8] if session_id else 'new'} prompt={prompt[:60]}")

        try:
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
                    # 回复超长检测：超过 1000 字直接幽默拒绝（省 token）
                    if len(reply) > _MAX_REPLY_CHARS:
                        log.info(f"[{trace_id}] ⛔ 回复过长 ({len(reply)} chars)，幽默拒绝")
                        return _LONG_REPLY_REJECTION
                    messages.append({"role": "assistant", "content": reply})
                    save_session(session_id, extract_dialog_turns(messages))
                    return reply

                # 有工具调用 → 并行执行（独立工具无依赖，可并发）
                parsed_calls = []
                for tc in msg.tool_calls:
                    fn = tc.function
                    try:
                        raw_args = fn.arguments
                        args = raw_args if isinstance(raw_args, dict) else json.loads(raw_args) if isinstance(raw_args, str) else {}
                        log.info(f"[{trace_id}] 🔍 [args_parse] type={type(raw_args)} raw={repr(raw_args)[:100]} parsed={args}")
                    except Exception as ex:
                        args = {}
                        log.error(f"[{trace_id}] 🔍 [args_parse] EXCEPTION: {ex}, raw={repr(fn.arguments)[:100]}")
                    log.info(f"[{trace_id}] 🔧 [r{round_num}] {fn.name} {args}")
                    parsed_calls.append((tc, fn.name, args))

                # 并发执行所有工具调用
                results = await asyncio.gather(
                    *[execute_tool(name, args) for _, name, args in parsed_calls],
                    return_exceptions=True,
                )

                # 注入 assistant 消息 + tool 结果（保持顺序）
                for idx, (tc, fn_name, _) in enumerate(parsed_calls):
                    result = results[idx]
                    if isinstance(result, Exception):
                        result = f"⚠️ 工具执行异常: {result}"
                    reasoning_content = ""
                    if hasattr(platform, "extract_reasoning"):
                        reasoning_content = platform.extract_reasoning(
                            msg.model_dump() if hasattr(msg, "model_dump") else {}
                        )
                    assistant_msg: Dict[str, Any] = {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": fn_name,
                                    "arguments": tc.function.arguments
                                    if isinstance(tc.function.arguments, str)
                                    else str(tc.function.arguments),
                                },
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
        finally:
            _trace_vars.reset(token)

    return get_reply
