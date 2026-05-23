"""
tools/registry.py — 工具注册表

对标 Node.js agent-core 的 buildTools()
- query_wechat: HTTP 调用 Node.js /api/queryWechat
- search_web: 搜索网页/新闻（Brave Search API，待接入）
"""

import logging
from typing import Any, Dict, List, Optional

import httpx

log = logging.getLogger(__name__)

# Node.js HTTP API 地址
HTTP_API_HOST = "localhost"
HTTP_API_PORT = 3001


# ============================================================
# 工具函数
# ============================================================

async def call_query_wechat_http(
    mode: str = "stats",
    speaker: Optional[str] = None,
    room: Optional[str] = None,
    friend: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 2000,
) -> str:
    """
    调用 Node.js HTTP API 查询微信消息记录

    Args:
        mode: stats | search | detail | images
        speaker: 发言人
        room: 群名
        friend: 好友名
        query: 搜索关键词
        limit: 最多条数

    Returns:
        格式化后的查询结果字符串
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
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            data = response.json()
            if "error" in data:
                return f"⚠️ 查询失败: {data['error']}"
            return data.get("result", "")
        except httpx.TimeoutException:
            return "⚠️ 查询超时，请稍后重试"
        except Exception as e:
            log.error("query_wechat HTTP error: %s", e)
            return f"⚠️ 查询服务不可用: {e}"


# ============================================================
# 工具定义（OpenAI tool_calls 格式）
# ============================================================

TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "queryWechat",
            "description": (
                "查询微信聊天记录。可查群聊、查某成员、搜关键词。\n"
                "mode=stats返回统计摘要；mode=search返回匹配的消息列表；\n"
                "mode=detail返回统计+消息样本；mode=images搜图片/视频/附件。\n"
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
            },
        },
    },
]


# ============================================================
# 工具执行器（根据 tool_call 执行对应函数）
# ============================================================

async def execute_tool(name: str, arguments: Dict[str, Any]) -> str:
    """
    根据工具名和参数执行对应工具函数

    Args:
        name: 工具名（如 "queryWechat"）
        arguments: 参数字典

    Returns:
        工具执行结果字符串
    """
    if name == "queryWechat":
        return await call_query_wechat_http(
            mode=arguments.get("mode", "stats"),
            speaker=arguments.get("speaker"),
            room=arguments.get("room"),
            friend=arguments.get("friend"),
            query=arguments.get("query"),
            limit=arguments.get("limit", 2000),
        )
    else:
        return f"未知工具: {name}"
