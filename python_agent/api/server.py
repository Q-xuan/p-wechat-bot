"""
api/server.py — FastAPI HTTP 层

暴露 /reply 接口，供 Node.js 调用 Python Agent

POST /reply
  Body: { "prompt", "sessionId", "roomName", "askerName", "platform" }
  Returns: { "reply": string }
"""

import logging
import os
import re
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 从 .env 文件直接读取（处理多行值，python-dotenv 会解析失败）
ENV_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env")
if os.path.exists(ENV_FILE):
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.rstrip()
                if "=" not in line or line.startswith("#"):
                    continue
                k, v = line.split("=", 1)
                v = v.strip().strip("'\"").strip()
                # 跳过占位符
                if v in ("", "***"):
                    continue
                # 跳过多行值（包含未闭合引号或换行的）
                if "\n" in v:
                    continue
                if k not in os.environ:
                    os.environ[k] = v
    except Exception:
        pass

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

app = FastAPI(title="Wechat-Bot Python Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type"],
)


# ============================================================
# 平台初始化（全局单例）
# ============================================================

class AgentFactory:
    _agents = {}

    @classmethod
    def get_agent(cls, platform_name: str):
        if platform_name in cls._agents:
            return cls._agents[platform_name]

        platform_map = {
            "Mimo": ("python_agent.platforms.mimo", "MimoPlatform"),
            "MiniMax": ("python_agent.platforms.minimax", "MiniMaxPlatform"),
            "deepseek": ("python_agent.platforms.deepseek", "DeepSeekPlatform"),
        }

        if platform_name not in platform_map:
            raise HTTPException(status_code=400, detail=f"不支持的平台: {platform_name}")

        import importlib
        mod_path, cls_name = platform_map[platform_name]
        try:
            mod = importlib.import_module(mod_path)
            platform = getattr(mod, cls_name)()
            from python_agent.agent.core import create_agent
            agent = create_agent(platform, system_prompt_base=platform.system_message)
            cls._agents[platform_name] = agent
            log.info(f"✅ Agent 已就绪: {platform_name}")
            return agent
        except Exception as e:
            log.error(f"❌ Agent 初始化失败 ({platform_name}): {e}")
            raise HTTPException(status_code=500, detail=f"Agent 初始化失败: {e}")


# ============================================================
# 请求/响应模型
# ============================================================

class ReplyRequest(BaseModel):
    prompt: str
    sessionId: str = ""
    roomName: str = ""
    askerName: str = ""
    platform: str = "Mimo"


class ReplyResponse(BaseModel):
    reply: str


# ============================================================
# 端点
# ============================================================

@app.get("/health")
async def health():
    return {"status": "ok", "service": "wechat-bot-python-agent"}


@app.post("/reply", response_model=ReplyResponse)
async def reply(req: ReplyRequest):
    """
    接收 Node.js 的 Agent 调用请求
    """
    agent = AgentFactory.get_agent(req.platform)

    reply_text = await agent(
        req.prompt,
        {"sessionId": req.sessionId, "roomName": req.roomName, "askerName": req.askerName},
    )

    return ReplyResponse(reply=reply_text)


# ============================================================
# 直接运行
# ============================================================

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PYTHON_AGENT_PORT", "3002"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
