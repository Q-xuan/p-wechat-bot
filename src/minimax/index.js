/**
 * MiniMax 服务
 *
 * 配置：MINIMAX_API_KEY / MINIMAX_BASE_URL / MINIMAX_MODEL / MINIMAX_SYSTEM_MESSAGE
 * 模型：MiniMax-Text-01（不支持工具调用）或 MiniMax-M2.5（支持工具调用）
 *
 * 特有逻辑：
 * - AI 二次压缩（MiniMax 非推理模型，响应快，用 AI 压缩质量更好）
 * - 不需要 reasoning_content 回传
 */

import OpenAI from 'openai'
import dotenv from 'dotenv'
const env = dotenv.config().parsed
import fs from 'fs'
import path from 'path'

const __dirname = path.resolve()
const envPath = path.join(__dirname, '.env')
if (!fs.existsSync(envPath)) {
  console.log('❌ 请先根据文档，创建并配置.env文件！')
  process.exit(1)
}

let config = { apiKey: env.MINIMAX_API_KEY }
if (env.MINIMAX_BASE_URL) config.baseURL = env.MINIMAX_BASE_URL
const openai = new OpenAI(config)
const chosenModel = env.MINIMAX_MODEL || 'MiniMax-Text-01'

// ============================================================
// 压缩策略：AI 二次调用（MiniMax 响应快，用 AI 压缩质量更好）
// ============================================================
async function compressByAI(rawText, maxCount = 4, hint = '') {
  const lines = rawText.split('\n').filter(l => l.trim().length > 0)
  if (lines.length <= 2 && rawText.length <= 80) return rawText

  const hintText = hint ? `\n用户补充：${hint}` : ''

  const resp = await openai.chat.completions.create({
    messages: [
      {
        role: 'system',
        content:
          `你是"黑瑞"，微信里的毒舌损友。把你收到的长内容拆成简洁的微信消息。\n` +
          `风格：毒舌、调侃、幽默，该损就损，保持人设。\n` +
          `规则：最多${maxCount}条，每条不超过30字，纯口语，不解释不补充不准用markdown。${hintText}\n` +
          `直接发消息内容，不要前缀，每条独立。`
      },
      { role: 'user', content: '把下面这段话拆成微信消息：\n\n' + rawText },
    ],
    model: chosenModel,
    max_tokens: 600,
  })

  let reply = `${resp.choices[0].message.content || ''}`
  reply = reply.replace(/<think>[\s\S]*?<\/think>/g, '').trim()
  reply = reply
    .replace(/\*\*(.+?)\*\*/g, '$1')
    .replace(/\*(.+?)\*/g, '$1')
    .replace(/`{1,3}(.+?)`{1,3}/gs, '$1')
    .replace(/^---+$/gm, '')
    .replace(/^#{1,6}\s+/gm, '')

  if (reply.length < 5 && lines.length > 0) {
    reply = lines.slice(0, 2).join(' ').slice(0, 150)
  }
  return reply
}

// ============================================================
// 引入共享 Agent 基础设施
// ============================================================
import { createAgent } from '../agent-core/index.js'

const getMinimaxReply = createAgent(
  { openai, chosenModel },
  {
    systemPromptBase: env.MINIMAX_SYSTEM_MESSAGE || '你是黑瑞，微信里的毒舌损友。风格：毒舌、调侃、幽默，该损就损。',
    modelReasoning: false,
    botName: env.BOT_NAME || '',
    getReasoningContent: () => '',
    compressFn: compressByAI,
  }
)

export { getMinimaxReply }
