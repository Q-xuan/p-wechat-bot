"""
mcp_client.py — 智谱 BigModel 联网搜索 MCP 客户端
使用官方 MCP Python SDK (StreamableHTTP 传输)

协议：MCP over StreamableHTTP
端点：POST https://open.bigmodel.cn/api/mcp/web_search_prime/mcp
认证：Bearer Token (ZHIPU_API_KEY)

架构：
- 后台 Task 用 anyio.create_task_group() 维护 keepalive 连接
- search() 在连接就绪后被调用（通过 _started Event 同步）
- keepalive 循环每 0.5 秒检查 _started，直到 session 关闭
"""

import os
import json
import logging
from typing import Any, Optional

try:
    from mcp.client.streamable_http import streamable_http_client
    from mcp.client.session import ClientSession
    from mcp.types import InitializedNotification
    import anyio
except ImportError:
    raise ImportError(
        "mcp Python SDK 未安装。请运行：\n"
        "  /Users/pyu/.hermes/hermes-agent/venv/bin/python3.11 -m pip install git+https://github.com/modelcontextprotocol/python-sdk.git"
    )

log = logging.getLogger(__name__)


class ZhipuMCPClient:
    """
    智谱 BigModel 联网搜索 MCP 客户端
    使用官方 MCP StreamableHTTP 传输协议
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or os.getenv("ZHIPU_API_KEY", "").strip()
        self.base_url = (base_url or os.getenv("ZHIPU_BASE_URL", "https://open.bigmodel.cn")).rstrip("/")
        self.mcp_url = f"{self.base_url}/api/mcp/web_search_prime/mcp"

        self._session: Optional[ClientSession] = None
        self._http_client: Optional[Any] = None
        self._started = anyio.Event()   # 连接就绪信号
        self._running = False                  # keepalive 运行标志

    async def start(self) -> None:
        """启动 MCP 客户端（后台连接，首次 search 前完成）"""
        if self._running:
            return

        api_key = self.api_key
        if not api_key or api_key in ("", "***"):
            raise RuntimeError("⚠️ 智谱搜索 API Key 未配置（ZHIPU_API_KEY）")

        self._running = True
        log.info(f"MCP 后台启动: {self.mcp_url}")

        async def _run() -> None:
            """后台 keepalive 循环"""
            import httpx

            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=60.0),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json, text/event-stream",
                },
            )

            try:
                async with streamable_http_client(
                    url=self.mcp_url,
                    http_client=self._http_client,
                    terminate_on_close=True,
                ) as (rs, ws, _):
                    self._session = ClientSession(
                        read_stream=rs,
                        write_stream=ws,
                        client_info={"name": "wechat-bot", "version": "1.0"},
                    )
                    async with self._session:
                        await self._session.initialize()
                        await self._session.send_notification(InitializedNotification())
                        log.info("MCP 连接已就绪")
                        self._started.set()

                        # keepalive：保持连接直到 close()
                        while self._running and self._session is not None:
                            await anyio.sleep(0.5)

            except Exception as e:
                log.error(f"MCP 连接异常: {e}")
                self._started.set()
                raise
            finally:
                self._session = None

        # 在 async 上下文中用 task group 启动后台 keepalive
        async def _start_bg():
            async with anyio.create_task_group() as tg:
                tg.start_soon(_run)
                # 等待 close() 时 running 被设为 False
                while self._running:
                    await anyio.sleep(0.5)
                tg.cancel_scope.cancel()

        await _start_bg()

    async def search(self, query: str, limit: int = 5) -> str:
        """调用 web_search_prime 工具（等待连接就绪后执行）"""
        # 懒启动
        if not self._running:
            await self.start()

        # 等待连接就绪（最多 30 秒）
        try:
            with anyio.fail_after(30.0):
                await self._started.wait()
        except Exception:
            return "⚠️ MCP 连接超时，请稍后重试"

        if self._session is None:
            return "⚠️ MCP 连接未建立，请检查日志"

        # 429 时最多重试 3 次，每次等待递增
        last_err = ""
        for attempt in range(4):
            try:
                result = await self._session.call_tool(
                    "web_search_prime",
                    {
                        "search_query": query[:70],
                        "content_size": "medium",
                        "location": "cn",
                    },
                )
                return self._format_result(query, result, limit)
            except Exception as e:
                last_err = str(e)
                err_str = str(e)
                # 检测 429 速率限制
                if "429" in err_str or "1302" in err_str:
                    if attempt < 3:
                        wait = (attempt + 1) * 2  # 2s, 4s, 6s
                        log.warning(f"MCP 速率限制，{wait}秒后重试（第{attempt+1}次）...")
                        await anyio.sleep(wait)
                        continue
                    else:
                        return "🔌 网卡了，搜索请求被限流了，稍等一下再试 😅"
                # 其他错误直接返回
                log.error(f"MCP search error: {e}")
                return f"⚠️ 搜索服务异常: {e}"

        # 理论上不会走到这里，但如果走到了
        return f"⚠️ 搜索服务异常: {last_err}"

    def _format_result(self, query: str, result: Any, limit: int) -> str:
        """解析 MCP 工具返回内容，格式化为易读字符串"""
        try:
            content = getattr(result, "content", None) or []
            if hasattr(result, "content") and isinstance(result.content, list):
                content = result.content
        except Exception:
            content = []

        if not content:
            return f"🔍 没有找到与「{query}」相关的搜索结果"

        items = []
        for item in content:
            item_type = getattr(item, "type", None)
            if item_type == "text":
                text = getattr(item, "text", "") or ""
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, str):
                        parsed = json.loads(parsed)
                    if isinstance(parsed, list):
                        items = parsed
                    elif isinstance(parsed, dict):
                        items = [parsed]
                except Exception:
                    if text:
                        try:
                            items = json.loads(text)
                            if not isinstance(items, list):
                                items = [items]
                        except Exception:
                            items = [{"content": text[:300]}]
            elif item_type == "resource":
                pass

        if not items:
            return f"🔍 没有找到与「{query}」相关的搜索结果"

        lines = [f"📰 今日热搜"]
        for i, item in enumerate(items[:limit], 1):
            if isinstance(item, dict):
                title = item.get("title", "") or ""
                snippet = item.get("content", "") or item.get("snippet", "") or ""
                url = item.get("link", "") or item.get("url", "") or ""

                # 清理空白
                title = title.strip()
                snippet = snippet.strip()

                if snippet and len(snippet) > 60:
                    snippet = snippet[:60].strip() + "..."

                # 提取域名作为来源标注
                source = ""
                if url:
                    try:
                        from urllib.parse import urlparse
                        parsed = urlparse(url)
                        netloc = parsed.netloc.replace("www.", "").split(".")[-2] if parsed.netloc else ""
                        if netloc:
                            source = f"（{netloc}）"
                    except Exception:
                        pass

                if snippet:
                    lines.append(f"{i}. {title} {source}\n   💬 {snippet}")
                else:
                    lines.append(f"{i}. {title} {source}\n   🔗 {url}")
            else:
                text = str(item).strip()
                if text:
                    lines.append(f"{i}. {text}")

        return "\n".join(lines)

    async def close(self) -> None:
        """关闭 MCP 连接"""
        self._running = False

        if self._session:
            try:
                await self._session.__aexit__(None, None, None)
            except Exception as e:
                log.warning(f"MCP session 关闭异常: {e}")
            self._session = None

        if self._http_client:
            try:
                await self._http_client.aclose()
            except Exception as e:
                log.warning(f"HTTP 客户端关闭异常: {e}")
            self._http_client = None

        log.info("MCP 连接已关闭")


# ================================================================
# 全局单例（进程级复用，懒启动）
# ================================================================

_client: Optional[ZhipuMCPClient] = None


async def get_mcp_client() -> ZhipuMCPClient:
    """获取全局 MCP 客户端单例（首次调用时启动后台连接）"""
    global _client
    if _client is None:
        _client = ZhipuMCPClient()
        await _client.start()
    return _client


async def close_mcp_client() -> None:
    """关闭全局 MCP 客户端"""
    global _client
    if _client:
        await _client.close()
        _client = None