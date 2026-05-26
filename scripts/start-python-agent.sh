#!/bin/bash
# scripts/start-python-agent.sh
# 启动 Python Agent 服务
#
# 用法：
#   ./scripts/start-python-agent.sh        # 前台运行（手动）
#   作为 PM2 进程运行（PM2 自动加载 .env）

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON_AGENT_DIR="$PROJECT_ROOT/python_agent"
cd "$PYTHON_AGENT_DIR"

# 从 .env 文件读取单行配置，export 给 Python
# 跳过多行值（python-dotenv 不支持）
ENV_FILE="$PROJECT_ROOT/.env"
if [ -f "$ENV_FILE" ]; then
    while IFS= read -r line; do
        [[ "$line" =~ ^# ]] && continue
        [[ -z "$line" ]] && continue
        [[ "$line" =~ ^[^=]+= ]] || continue
        key="${line%%=*}"
        val="${line#*=}"
        # 去掉首尾引号和换行
        val="$(echo "$val" | sed "s/^[\"']//;s/[\"']$//" | tr -d '\n\r')"
        [[ -z "$val" ]] && continue
        [[ "$val" == "***" ]] && continue
        # 跳过含换行的值
        echo "$val" | grep -q $'\n' && continue
        export "$key=$val"
    done < "$ENV_FILE"
fi

PORT="${PYTHON_AGENT_PORT:-3002}"
cd "$PROJECT_ROOT"
exec /Users/pyu/.hermes/hermes-agent/venv/bin/python3.11 -m uvicorn python_agent.api.server:app --host 0.0.0.0 --port "$PORT" --log-level info
