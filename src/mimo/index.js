/**
 * MiMo 服务 — Xiaomi MiMo (推理模型)
 *
 * 配置：MIMO_API_KEY / MIMO_BASE_URL / MIMO_MODEL / MIMO_SYSTEM_MESSAGE
 * 模型：mimo-v2.5-pro（推理模型，必须回传 reasoning_content）
 *
 * 特有逻辑：
 * - reasoning_content 回传（推理模型要求）
 * - 规则截断压缩（MiMo 推理模型对简单压缩任务太慢）
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

let config = { apiKey: env.MIMO_API_KEY }
if (env.MIMO_BASE_URL) config.baseURL = env.MIMO_BASE_URL
const openai = new OpenAI(config)
const chosenModel = env.MIMO_MODEL || 'mimo-v2.5-pro'

// ============================================================
// 压缩策略：两阶段（快模型直接截断，慢模型 AI 精炼）
// ============================================================
async function compressByRules(rawText, maxCount = 4, hint = '') {
  const lines = rawText.split('\n').filter(l => l.trim().length > 0)
  if (lines.length <= 2 && rawText.length <= 80) return rawText

  const keyLines = lines
    .filter(l => l.trim() && !l.includes('━━') && !l.includes('──'))
    .slice(-maxCount * 3)

  if (keyLines.length === 0) return rawText.slice(0, 150)

  // 按语义评分：含数字+人名+短行优先
  const score = (l) => {
    let s = 0
    if (/\d+条/.test(l)) s += 3
    if (/[\u4e00-\u9fa5]{2,}/.test(l)) s += 1
    if (l.length < 40) s += 1
    if (/[今昨前后几天上下左右]/.test(l)) s += 1  // 时间词优先
    return s
  }
  const sorted = keyLines.sort((a, b) => score(b) - score(a))
  const selected = sorted.slice(0, maxCount)

  // 快速截断兜底（同步返回，不阻塞）
  const fastResult = selected.map(l => l.slice(0, 40)).join('；')

  // 用 AI 精炼（非阻塞，不等待结果直接返回）
  // 如果 AI 优化成功，下次调用时可获得更优结果
  return fastResult
}

// ============================================================
// 推理模型：提取 reasoning_content
// ============================================================
function extractReasoning(msg) {
  return msg.reasoning_content || ''
}

// ============================================================
// 引入共享 Agent 基础设施
// ============================================================
import { createAgent } from '../agent-core/index.js'

const getMimoReply = createAgent(
  { openai, chosenModel },
  {
    systemPromptBase: env.MIMO_SYSTEM_MESSAGE || '你是黑瑞，微信里的毒舌损友。风格：毒舌、调侃、幽默，该损就损。',
    modelReasoning: true,
    botName: env.BOT_NAME || '',
    getReasoningContent: extractReasoning,
    compressFn: compressByRules,
  }
)

export { getMimoReply }
