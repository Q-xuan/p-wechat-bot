# 微信群聊分析 Bot

基于 [wechat-bot](https://github.com/wangrongding/wechat-bot) 的定制 fork，专注于**微信群聊消息查询与 AI 分析**。

支持 MiniMax、Mimo 等模型作为 Agent，提供了消息统计、成员发言查询、关键词搜索等能力。

## 快速开始

### 1. 安装依赖

```sh
npm i
npm link   # 可选，注册 wb 全局命令
```

### 2. 配置环境

```sh
cp .env.example .env
```

编辑 `.env`，至少填入：

```env
# 微信配置
BOT_NAME='@你的微信昵称'
ROOM_WHITELIST='群名1,群名2'
ALIAS_WHITELIST='好友备注1,好友备注2'

# Agent 选择（选一个）
MINIMAX_API_KEY='你的MiniMax API Key'
# 或者
MIMO_API_KEY='你的Mimo API Key'
```

### 3. 启动

```sh
# 方式一：直接运行（调试用）
./scripts/start.sh

# 方式二：PM2 后台运行（推荐，重启不丢登录状态）
./scripts/start.sh pm2
```

> **首次启动**：扫码登录后，登录状态会自动保存到 `WechatEveryDay.memory-card.json`，下次重启不需要再扫码。

终端出现二维码后用微信扫码登录。

## PM2 进程管理

| 命令 | 说明 |
|------|------|
| `./scripts/start.sh pm2` | 后台启动 |
| `./scripts/start.sh stop` | 停止 |
| `./scripts/start.sh restart` | 重启 |
| `./scripts/start.sh logs` | 查看最近日志 |
| `./scripts/start.sh status` | 查看进程状态 |

> **重要**：PM2 进程运行期间，微信登录状态（cookie/session）会持久化到本地文件。进程被 kill 或机器重启后，下次 `pm2 start` 可以跳过扫码直接恢复登录。

## 支持的 Agent

| Agent | 说明 |
|-------|------|
| **MiniMax** | MiniMax 模型，需配置 `MINIMAX_API_KEY` |
| **Mimo** | Mimo 模型，需配置 `MIMO_API_KEY` |
| **DeepSeek** | DeepSeek 模型，需配置 `DEEPSEEK_API_KEY` |
| **Pi** | 本地 Pi agent，适合离线场景 |
| **Ollama** | 本地模型，适合离线场景 |

启动时通过 `--agent` 指定：

```sh
wb agent --im wechat --agent minimax
wb agent --im wechat --agent deepseek
wb agent --im wechat --agent pi
```

## 核心功能

启动后，群里 `@机器人` 或私聊发送命令即可：

| 命令 | 说明 |
|------|------|
| `/统计` | 当前群/好友的发言统计 |
| `/分析 群友名` | 分析某成员的发言记录 |
| `/分析 @某人` | 同上 |
| `/搜索 关键词` | 搜索包含关键词的消息 |

消息会自动存入 `.data/wechat/messages.jsonl`，支持离线查询。

## 消息查询工具

Agent 内置 `queryWechat` 工具，支持以下模式：

- `mode=stats` — 发言统计（人数、消息数、高频成员、活跃时段）
- `mode=search` — 按关键词搜索消息
- `mode=detail` — 统计 + 最近消息样本
- `mode=images` — 搜索图片/视频/附件

支持按 `speaker`、`room`、`friend`、`query` 组合过滤。

## 项目结构

```
src/
├── agent-core/          # Agent 基础设施（ReAct、session、工具注册）
├── minimax/             # MiniMax 模型接入
├── mimo/                # Mimo 模型接入
├── analysis/            # 消息统计与分析
└── platforms/wechat/
    ├── commandRouter.js  # 命令解析
    └── messageStore.js   # 本地消息存储与查询
```
