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
# 微信扫码登录，消息自动存储并响应
wb agent --im wechat

# 或指定 agent
wb agent --im wechat --agent minimax
wb agent --im wechat --agent mimo
```

终端出现二维码后用微信扫码登录。

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
