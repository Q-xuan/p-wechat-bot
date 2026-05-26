"""
tools/registry.py — 工具注册表（安全设计：最小权限 + MCP 白名单）

设计原则（方案 B）：
- 工具注册表保持最小化，只包含明确授权的"只读查询"类工具
- MCP 接入需白名单审查，禁止带 shell/file/subprocess 工具的 MCP 服务器
- 每个工具执行前验证在 ALLOWED_MCP_TOOLS 白名单中

已授权工具：
  ✅ queryWechat — HTTP 调用 Node.js 读取聊天 JSON 文件（只读）
  ✅ searchWeb   — 调用外部搜索 API（无本地 I/O）

禁止的工具类型：
  ❌ shell / exec / subprocess
  ❌ file/read / file/write
  ❌ 未经白名单审查的 MCP 工具
"""

import logging
import os
import re
import asyncio as _asyncio
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

# ================================================================
# MCP 白名单配置
# ================================================================

# MCP 工具白名单（方案 B）
# 只有在这里登记的工具才能被执行
# 格式：tool_name -> { "source": "mcp" | "builtin", "description": str }
ALLOWED_MCP_TOOLS: Dict[str, Dict] = {
    # 内置工具
    "queryWechat": {
        "source": "builtin",
        "description": "查询微信聊天记录（只读 HTTP 调用）",
    },
    # 搜索工具（外部 API，无本地 I/O）
    "searchWeb": {
        "source": "mcp",
        "description": "搜索网页获取信息（只读）",
    },
}

# ================================================================
# Node.js HTTP API 地址
# ================================================================

HTTP_API_HOST = "localhost"
HTTP_API_PORT = 3001


# ================================================================
# 工具函数实现
# ================================================================

async def call_query_wechat_http(
    mode: str = "stats",
    speaker: Optional[str] = None,
    room: Optional[str] = None,
    friend: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 2000,
) -> str:
    """
    调用 Node.js HTTP API 查询微信消息记录（只读）
    """
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            response = await client.post(
                f"http://{HTTP_API_HOST}:{HTTP_API_PORT}/api/queryWechat",
                json={
                    "mode": mode,
                    "speaker": speaker,
                    "room": room,
                    "friend": friend,
                    "query": query,
                    "limit": limit,
                },
            )
            data = response.json()
            if "error" in data:
                return f"⚠️ 查询失败: {data['error']}"
            return data.get("result", "")
        except httpx.TimeoutException:
            return "⚠️ 查询超时，请稍后重试"
        except Exception as e:
            log.error("query_wechat HTTP error: %s", e)
            return f"⚠️ 查询服务不可用: {e}"


async def call_search_web(query: str, limit: int = 5) -> str:
    """
    搜索网页（调用智谱 BigModel web_search_prime MCP）
    使用官方 MCP Python SDK (StreamableHTTP transport)
    """
    from python_agent.tools.mcp_client import get_mcp_client

    api_key = os.getenv("ZHIPU_API_KEY", "").strip()
    if not api_key or api_key in ("", "***"):
        return "⚠️ 智谱搜索 API Key 未配置（ZHIPU_API_KEY）"

    enabled = os.getenv("ENABLE_WEB_SEARCH", "true").strip().lower()
    if enabled not in ("true", "1", "yes"):
        return "⚠️ 网络搜索已关闭（ENABLE_WEB_SEARCH=false）"

    try:
        client = await get_mcp_client()
        result = await client.search(query, limit=limit)
        return result
    except Exception as e:
        log.error("search_web error: %s", e)
        return f"⚠️ 搜索服务异常: {e}"


# ================================================================
# 工具定义（OpenAI tool_calls 格式）
# ================================================================

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "queryWechat",
            "description": (
                "查询微信聊天记录。可查群聊、查某成员、搜关键词。\n"
                "mode=stats返回统计摘要；mode=search返回匹配的消息列表；\n"
                "mode=detail返回统计+样本；mode=images搜图片/视频/附件。\n"
                "结果自动压缩，无需再调用任何优化工具。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["stats", "search", "detail", "images"],
                        "description": "stats=统计摘要(默认)，search=搜文本消息，detail=统计+样本，images=搜图片/视频/附件",
                    },
                    "speaker": {"type": "string", "description": "发言人名字（模糊匹配）"},
                    "room": {"type": "string", "description": "群名称（精确匹配）"},
                    "friend": {"type": "string", "description": "好友名字"},
                    "query": {"type": "string", "description": "搜索关键词（仅 mode=search 时使用）"},
                    "limit": {"type": "number", "description": "最多加载条数（默认2000）"},
                },
                "required": ["mode"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchWeb",
            "description": (
                "搜索互联网获取实时信息。当用户问以下问题时必须使用：\n"
                "- 今天有什么新闻 / 现在热点 / 最新消息\n"
                "- 查一下 xxx 是什么 / 搜索 xxx\n"
                "- 帮我找 xxx 相关内容 / 有什么关于 xxx 的\n"
                "返回格式：标题 + 摘要 + 链接。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词（用简洁的中文关键词，不要加问号或完整句子）",
                    },
                    "limit": {
                        "type": "number",
                        "description": "最多返回结果条数（默认5条）",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
]


# ================================================================
# MCP 工具注册（方案 B 白名单模式）
# ================================================================

def register_mcp_tools(mcp_tools: List[Dict[str, Any]]) -> None:
    """
    将 MCP 工具注册到 TOOLS 列表（仅白名单中的工具）

    Args:
        mcp_tools: MCP 服务器返回的工具列表
    """
    for tool in mcp_tools:
        name = tool.get("name", "")
        if name not in ALLOWED_MCP_TOOLS:
            log.warning("MCP tool '%s' NOT in whitelist — skipped", name)
            continue
        # 白名单中有，但 source 不是 mcp（已内置）则跳过
        if ALLOWED_MCP_TOOLS[name]["source"] == "builtin":
            log.debug("MCP tool '%s' is builtin — skipping duplicate registration", name)
            continue
        TOOLS.append(tool)
        log.info("Registered MCP tool: %s", name)


# ================================================================
# 工具执行器（安全验证）
# ================================================================

async def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """
    根据工具名和参数执行对应工具函数（白名单验证）

    安全设计：
    1. 工具必须在 ALLOWED_MCP_TOOLS 白名单中
    2. 参数不包含可疑的路径穿越（如 ../ 路径）
    3. 参数长度合理（防止注入）
    """
    # ---- 安全检查 1：白名单验证 ----
    if name not in ALLOWED_MCP_TOOLS:
        return f"⛔ 未知工具 '{name}' — 未授权执行（不在白名单中）"

    # ---- 安全检查 2：路径穿越检测 ----
    for key, value in arguments.items():
        if isinstance(value, str):
            # 检测路径穿越尝试
            if ".." in value or value.startswith("/") or value.startswith("~"):
                log.warning("Tool '%s' blocked: suspicious path in arg '%s'", name, key)
                return f"⛔ 参数 '{key}' 含有可疑路径 — 拒绝执行"

    # ---- 安全检查 3：参数长度限制 ----
    for key, value in arguments.items():
        if isinstance(value, str) and len(value) > 10000:
            log.warning("Tool '%s' blocked: arg '%s' too long (%d chars)", name, key, len(value))
            return f"⛔ 参数 '{key}' 过长（>{10000} 字符）— 拒绝执行"

    # ---- 执行白名单工具 ----
    try:
        if name == "queryWechat":
            return await call_query_wechat_http(
                mode=arguments.get("mode", "stats"),
                speaker=arguments.get("speaker"),
                room=arguments.get("room"),
                friend=arguments.get("friend"),
                query=arguments.get("query"),
                limit=arguments.get("limit", 2000),
            )
        elif name == "searchWeb":
            log.info(f"🔍 [execute_tool] searchWeb query={arguments.get('query')} limit={arguments.get('limit')}")
            result = await call_search_web(
                query=arguments.get("query", ""),
                limit=arguments.get("limit", 5),
            )
            log.info(f"🔍 [execute_tool] searchWeb result[:100]={result[:100]}")
            return result
    except Exception as e:
        log.error(f"execute_tool({name}) 异常: {e}", exc_info=True)
        return f"⚠️ 工具执行异常: {e}"
    else:
        # 理论上不会走到这里（白名单已过滤）
        return f"⛔ 工具 '{name}' 在白名单中但未实现"