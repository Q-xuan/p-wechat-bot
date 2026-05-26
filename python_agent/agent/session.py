"""
agent/session.py — Session 持久化（进程重启不丢）

对标 Node.js agent-core 的 session 管理：
- load_session: 加载对话历史（TTL 30 分钟）
- save_session: 保存对话历史
- clean_expired_sessions: 清理过期 session
"""

import json
import logging
import os
import re
import time as time_module
from pathlib import Path
from typing import List, Dict, Any, Optional

log = logging.getLogger(__name__)

# Session 目录（放在 .data/sessions/ 下，与 Node.js 共享）
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent
SESSION_DIR = PROJECT_ROOT / ".data" / "sessions"
SESSION_TTL_MS = 30 * 60 * 1000  # 30 分钟
MAX_SESSION_AGE_MS = 7 * 24 * 60 * 60 * 1000  # 7 天
MAX_TURNS = 10
# 简单 token 估算：中文≈2 token/字，英文≈0.25 token/字符
_MAX_TOKEN_ESTIMATE_PER_TURN = 800
_MAX_TOTAL_TOKEN = 32000  # 留 2K buffer 给 response

# 确保目录存在
SESSION_DIR.mkdir(parents=True, exist_ok=True)


def _safe_id(session_id: str) -> str:
    """把 sessionId 转为安全的文件名"""
    return re.sub(r"[^a-zA-Z0-9_:-]", "_", session_id)


def _session_path(session_id: str) -> Path:
    return SESSION_DIR / f"{_safe_id(session_id)}.json"


def load_session_file(session_id: str) -> Optional[Dict[str, Any]]:
    """从文件加载 session"""
    if not session_id:
        return None
    path = _session_path(session_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_session_file(session_id: str, entry: Dict[str, Any]) -> None:
    """保存 session 到文件（原子写：先写临时文件再 rename）"""
    if not session_id:
        return
    path = _session_path(session_id)
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.rename(path)  # atomic on POSIX
    except Exception as e:
        log.warning("⚠️ session 保存失败: %s", e)
        if tmp.exists():
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass


def clean_expired_sessions() -> None:
    """清理过期 session（TTL 过期或 7 天以上）"""
    import time
    now = int(time.time() * 1000)
    try:
        for file in SESSION_DIR.glob("*.json"):
            try:
                entry = json.loads(file.read_text(encoding="utf-8"))
                ts = entry.get("ts", 0)
                if now - ts > SESSION_TTL_MS or now - ts > MAX_SESSION_AGE_MS:
                    file.unlink()
                    log.info("🗑️ 清理过期 session: %s", file.name)
            except Exception:
                pass
    except Exception:
        pass


def load_session(session_id: str) -> List[Dict[str, str]]:
    """
    加载对话历史（自动 TTL 过滤）

    Args:
        session_id: session 标识符

    Returns:
        [{role, content}, ...] 格式的对话历史
    """
    import time

    if not session_id:
        return []

    entry = load_session_file(session_id)
    if not entry:
        return []

    # TTL 过期则删除文件
    if int(time_module.time() * 1000) - entry.get("ts", 0) > SESSION_TTL_MS:
        try:
            _session_path(session_id).unlink(missing_ok=True)
        except Exception:
            pass
        return []

    return entry.get("turns", [])


def _estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文×2，英文×0.25"""
    chinese = len(re.findall(r"[\u4e00-\u9fa5]", text))
    other = len(re.sub(r"[\u4e00-\u9fa5]", "", text))
    return chinese * 2 + int(other * 0.25)


def _total_tokens(turns: List[Dict[str, str]]) -> int:
    """估算所有 turns 的总 token 数"""
    return sum(_estimate_tokens(t.get("content", "") or "") for t in turns)


def save_session(session_id: str, turns: List[Dict[str, str]]) -> None:
    """
    保存对话历史到文件（自动截断防止 token 超限）

    Args:
        session_id: session 标识符
        turns: 对话历史
    """
    if not session_id:
        return

    # Token 上限保护：从最新的往回保留，直到不超限
    protected_turns = [t for t in turns if t.get("role") == "system"]
    mutable_turns = [t for t in turns if t.get("role") != "system"]

    while mutable_turns and _total_tokens(protected_turns + mutable_turns) > _MAX_TOTAL_TOKEN:
        if len(mutable_turns) <= 2:
            # 保留最近 2 轮即可
            mutable_turns = mutable_turns[-2:]
            break
        mutable_turns.pop(0)  # 从最老开始删

    save_session_file(session_id, {
        "ts": int(time_module.time() * 1000),
        "turns": protected_turns + mutable_turns,
    })


def extract_dialog_turns(messages: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    """
    从完整 messages 数组中提取纯对话轮次（去掉 tool_calls / tool 结果）
    工具结果不进 session，防止 context 膨胀
    """
    turns = []
    for m in messages:
        if m.get("role") == "system":
            turns.append({"role": "system", "content": m.get("content", "")})
        elif m.get("role") == "user":
            content = m.get("content", "")
            if isinstance(content, list):
                text = next((c["text"] for c in content if c.get("type") == "text"), "")
            else:
                text = content
            turns.append({"role": "user", "content": text or ""})
        elif m.get("role") == "assistant" and not m.get("tool_calls"):
            turns.append({"role": "assistant", "content": m.get("content", "") or ""})
        # tool role 和带 tool_calls 的 assistant 消息：跳过，不进入 session
    return turns


# 启动时清理一次
clean_expired_sessions()
