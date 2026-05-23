/**
 * DeepSeek 服务
 *
 * 配置：DEEPSEEK_API_KEY / DEEPSEEK_URL / DEEPSEEK_MODEL / DEEPSEEK_SYSTEM_MESSAGE
 * 模型：deepseek-v4-flash 或 deepseek-chat（支持工具调用）
 *
 * 接入 agent-core：ReAct 循环 + queryWechat 工具 + session 管理
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

let config = { apiKey: env.DEEPSEEK_API_KEY }
if (env.DEEPSEEK_URL) config.baseURL = env.DEEPSEEK_URL
const openai = new OpenAI(config)
const chosenModel = env.DEEPSEEK_MODEL || 'deepseek-chat'

// ============================================================
// 引入共享 Agent 基础设施
// ============================================================
import { createAgent, smartCompress } from '../agent-core/index.js'

const getDeepseekReply = createAgent(
  { openai, chosenModel },
  {
    systemPromptBase: env.DEEPSEEK_SYSTEM_MESSAGE || '你是黑瑞，微信里的毒舌损友。风格：毒舌、调侃、幽默，该损就损。',
    modelReasoning: false,   // DeepSeek 非推理模型
    botName: env.BOT_NAME || '',
    getReasoningContent: () => '',
    compressFn: smartCompress,
  }
)

export { getDeepseekReply }
