#!/bin/bash
# wechat-bot 启动脚本
# 用法: ./scripts/start.sh          # 前台运行（调试用）
#        ./scripts/start.sh pm2      # PM2 后台运行

set -e

cd "$(dirname "$0")/.."

# 确保使用 nvm 的 node
export PATH="$HOME/.nvm/versions/node/v22.22.0/bin:$PATH"

# 检查 .env 是否存在
if [ ! -f .env ]; then
  echo "❌ .env 文件不存在，请先复制 .env.example 为 .env 并配置"
  exit 1
fi

# 检查依赖
if [ ! -d node_modules ]; then
  echo "📦 首次安装依赖..."
  npm install
fi

# 检查 pm2
check_pm2() {
  if ! command -v pm2 &>/dev/null; then
    echo "📦 安装 pm2..."
    npm install -g pm2
  fi
}

SERVICE=${SERVICE_TYPE:-Mimo}

if [ "$1" = "pm2" ]; then
  check_pm2

  # 确保 pm2 守护进程已启动
  pm2 startOrRestart ~/.pm2/pm2.dotenv.config.js 2>/dev/null || true

  echo "🚀 启动 wechat-bot ($SERVICE) via PM2..."
  pm2 start ecosystem.config.cjs --env production

elif [ "$1" = "stop" ]; then
  check_pm2
  echo "🛑 停止 wechat-bot..."
  pm2 stop wechat-bot 2>/dev/null || true

elif [ "$1" = "restart" ]; then
  check_pm2
  echo "🔄 重启 wechat-bot..."
  pm2 restart wechat-bot

elif [ "$1" = "logs" ]; then
  check_pm2
  pm2 logs wechat-bot --lines 50 --nostream

elif [ "$1" = "status" ]; then
  check_pm2
  pm2 status

else
  # 前台运行
  echo "🤖 启动 wechat-bot ($SERVICE) 前台模式..."
  echo "   按 Ctrl+C 停止"
  echo "   二维码在终端内显示，或访问:"
  echo "   https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=<二维码URL>"
  echo ""
  node cli.js start -s "$SERVICE"
fi
