/**
 * agent-core — 微信机器人共享 Agent 基础设施
 *
 * 包含：ReAct 循环、session 管理、工具注册、数据层、markdown 处理、重试与流式输出
 * 被 mimo/minimax 等服务模块继承（传入 API 配置和选项函数）
 */

import { remark } from 'remark'
import stripMarkdown from 'strip-markdown'
import fs from 'fs'
import path from 'path'
import http from 'http'
import { buildWechatStats } from '../analysis/wechatAnalyzer.js'
import { filterWechatMessages, loadWechatMessages } from '../platforms/wechat/messageStore.js'
import { getWechatRuntimeConfig } from '../config/env.js'

// HTTP API 服务地址（供工具调用）
const HTTP_API_HOST = process.env.HTTP_API_HOST || 'localhost'
const HTTP_API_PORT = process.env.HTTP_API_PORT || '3001'

/**
 * 通过 HTTP 调用 queryWechat（供 Python Agent 模拟 / 实际使用）
 * @param {object} params
 * @returns {Promise<string>} 格式化后的查询结果
 */
function callQueryWechatHttp(params) {
  return new Promise((resolve, reject) => {
    const body = JSON.stringify(params)
    const options = {
      hostname: HTTP_API_HOST,
      port: HTTP_API_PORT,
      path: '/api/queryWechat',
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Content-Length': Buffer.byteLength(body),
      },
      timeout: 10000,
    }
    const req = http.request(options, (res) => {
      let data = ''
      res.on('data', chunk => { data += chunk })
      res.on('end', () => {
        try {
          const json = JSON.parse(data)
          if (json.error) reject(new Error(json.error))
          else resolve(json.result)
        } catch {
          reject(new Error(`HTTP ${res.statusCode}: ${data.slice(0, 100)}`))
        }
      })
    })
    req.on('error', reject)
    req.on('timeout', () => { req.destroy(); reject(new Error('HTTP 请求超时')) })
    req.write(body)
    req.end()
  })
}

// ============================================================
// 重试工具函数（指数退避）
// ============================================================
/**
 * 带指数退避的重试封装
 * @param {Function} fn - 要执行的异步函数
 * @param {number} maxRetries - 最大重试次数（默认 3）
 * @param {number} baseDelay - 基础延迟 ms（默认 1000）
 * @param {Array<number>} retryableErrors - 可重试的错误状态码
 * @returns {Promise<any>}
 */
export async function withRetry(fn, { maxRetries = 3, baseDelay = 1000, retryableErrors = [429, 500, 502, 503, 504] } = {}) {
  let lastError
  for (let attempt = 0; attempt < maxRetries; attempt++) {
    try {
      return await fn()
    } catch (err) {
      lastError = err
      const isRetryable = err?.status && retryableErrors.includes(err.status)
        || err?.message?.includes('timeout')
        || err?.message?.includes('rate limit')
        || err?.message?.includes('connection')

      if (isRetryable && attempt < maxRetries) {
        const delay = baseDelay * Math.pow(2, attempt)
        console.log(`🔁 API 重试 ${attempt + 1}/${maxRetries}，${delay}ms 后重试...`)
        await new Promise(r => setTimeout(r, delay))
        continue
      }
      throw err
    }
  }
  throw lastError
}

// ============================================================
// Markdown 处理
// ============================================================
const processor = remark().use(stripMarkdown)

/**
 * 清理 AI 回复中的各种格式，输出纯文本
 * @param {string} raw
 * @returns {string}
 */
export function cleanReply(raw) {
  if (!raw) return ''
  let text = raw.replace(/<think>[\s\S]*?<\/think>/g, '')
  text = text.replace(/\*\*(.+?)\*\*/g, '$1')
  text = text.replace(/\*(.+?)\*/g, '$1')
  text = text.replace(/`{1,3}(.+?)`{1,3}/gs, '$1')
  text = text.replace(/^---+$/gm, '')
  text = text.replace(/^#{1,6}\s+/gm, '')
  text = processor.processSync(text).toString()
  return text.trim()
}

// ============================================================
// 智能压缩策略
// ============================================================
/**
 * 语义压缩：按行分组、提取关键词、生成摘要
 * 比分段截断更有信息量，比纯 AI 调用更快
 *
 * @param {string} rawText - 原始文本
 * @param {number} maxLines - 最多保留几行/几条
 * @param {string} hint - 补充提示
 * @returns {string} 压缩后的文本
 */
export function smartCompress(rawText, maxLines = 4, hint = '') {
  const allLines = rawText.split('\n').filter(l => l.trim())

  // 太短不需要压缩
  if (allLines.length <= 2 && rawText.length <= 80) return rawText

  // 过滤装饰线和空白行
  const filtered = allLines.filter(l =>
    !l.match(/^[\s]*[━━‑——=*_]{3,}[\s]*$/) &&
    l.trim().length > 0
  )

  // 提取关键信息行（按语义权重排序）
  const weight = (line) => {
    let score = 0
    // 数字多 → 信息密度高
    score += (line.match(/\d+/g) || []).length * 2
    // 包含中文人名/地名
    score += (line.match(/[\u4e00-\u9fa5]{2,}/g) || []).length
    // 时间词
    if (/[今昨前后几天上下左右早晚凌晨傍晚]/.test(line)) score += 2
    // Emoji 少 → 更正式的信息
    score += (line.match(/[^\x00-\x7F]/g) || []).length < 3 ? 1 : 0
    // 短行（精华往往简短）
    if (line.length < 60) score += 1
    // 排除纯分隔符
    if (line.match(/^[\s]*[^\u4e00-\u9fa5a-zA-Z0-9]+[\s]*$/)) score -= 5
    return score
  }

  const scored = filtered.map(l => ({ line: l, w: weight(l) }))
  // 高权重优先，相同权重按原文顺序（stable sort）
  const sorted = scored.sort((a, b) => b.w - a.w || 0)
  const top = sorted.slice(0, maxLines)
  // 恢复原文顺序
  const finalLines = top.sort((a, b) => filtered.indexOf(a.line) - filtered.indexOf(b.line))

  let result = finalLines.map(x => x.line).join('\n')

  if (hint) result += `\n\n📌 ${hint}`

  return result
}

// ============================================================
// 数据目录
// ============================================================
function getDataDir() {
  try {
    return getWechatRuntimeConfig().dataDir || '.data/wechat'
  } catch {
    return '.data/wechat'
  }
}

// ============================================================
// 数据层：统计摘要构建
// ============================================================
export function buildStatsResult(records, target) {
  const stats = buildWechatStats(records)
  return [
    `📊 ${target}`,
    `消息数：${stats.totalMessages} | 均长：${stats.averageTextLength} 字`,
    `高频发言：${stats.topSpeakers.slice(0, 5).map(i => `${i.name}(${i.count})`).join('、') || '暂无'}`,
    stats.hourly.length > 0
      ? `活跃时段：${stats.hourly.slice(0, 3).map(i => `${i.name}点(${i.count}条)`).join('、')}`
      : '',
  ].filter(Boolean).join('\n')
}

// ============================================================
// 数据层：消息查询
// ============================================================
/**
 * 查询微信聊天记录。
 * 支持三种模式：stats / search / detail
 * 工具内部直接处理压缩，不产生额外 API 调用。
 *
 * @param {object} params
 * @param {string} params.mode      - stats | search | detail
 * @param {string} [params.speaker] - 发言人（模糊匹配）
 * @param {string} [params.room]    - 群名（精确匹配）
 * @param {string} [params.friend]  - 好友名
 * @param {string} [params.query]    - 搜索关键词
 * @param {number} [params.limit]    - 最多加载条数
 * @param {object} [params.options]  - 压缩选项 { maxCount, hint }
 */
export async function queryWechat({ speaker, room, friend, query, mode = 'stats', limit = 2000 }, options = {}) {
  const { maxCount = 4, compressFn } = options

  const allRecords = loadWechatMessages({ dataDir: getDataDir(), limit })
  const records = filterWechatMessages(allRecords, { speaker, room, friend, query })

  const target =
    speaker ? `群友「${speaker}」` :
    room   ? `群聊「${room}」` :
    friend ? `好友「${friend}」` : '全部记录'

  // ── speaker 查不到 0 条时：fallback 到 query 模式搜包含该词的消息 ──
  if (records.length === 0 && speaker) {
    const fallbackRecords = filterWechatMessages(allRecords, { room, query: speaker })
    if (fallbackRecords.length > 0) {
      const recent = fallbackRecords.slice(-50)
      const lines = recent.map(r => {
        const who = r.talkerAlias || r.talkerName || '?'
        const text = r.text || `[${r.typeName}]`
        const time = r.timestamp
          ? new Date(r.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
          : ''
        return `${time} ${who}: ${text.slice(0, 100)}`
      })
      const raw = [
        `🔍 群聊中提到「${speaker}」的消息 ${fallbackRecords.length} 条：` ,
        ...lines,
        fallbackRecords.length > 50 ? `\n...还有 ${fallbackRecords.length - 50} 条` : '',
      ].join('\n')
      if (lines.length > 6 && compressFn) {
        return await compressFn(raw, maxCount, `精炼摘要，包含数量和时间分布`)
      }
      return raw
    }
  }

  if (records.length === 0) {
    return `🔍 ${target} — 暂无匹配消息`
  }

  // ── images 模式：搜图片/视频/附件类消息 ──
  if (mode === 'images') {
    const mediaRecords = records.filter(r =>
      !r.isText || ['Image', 'Video', 'Attachment', 'App'].includes(r.typeName)
    )
    if (mediaRecords.length === 0) {
      return `🖼️ ${target} — 暂无图片/视频/附件记录`
    }
    const lines = mediaRecords.slice(-30).map(r => {
      const who = r.talkerAlias || r.talkerName || '?'
      const time = r.timestamp
        ? new Date(r.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        : ''
      return `${time} ${who}: [${r.typeName}] ${(r.text || '').slice(0, 60)}`
    })
    return [
      `🖼️ ${target} 有 ${mediaRecords.length} 条媒体消息：` ,
      ...lines,
    ].join('\n')
  }

  if (mode === 'search') {
    const recent = records.slice(-50)
    const lines = recent.map(r => {
      const who = r.talkerAlias || r.talkerName || '?'
      const text = r.text || `[${r.typeName}]`
      const time = r.timestamp
        ? new Date(r.timestamp).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
        : ''
      return `${time} ${who}: ${text.slice(0, 100)}`
    })
    const raw = [
      `🔍 找到 ${records.length} 条${query ? `含「${query}」的` : ''}消息：` ,
      ...lines,
      records.length > 50 ? `\n...还有 ${records.length - 50} 条` : '',
    ].join('\n')
    if (lines.length > 6 && compressFn) {
      return await compressFn(raw, maxCount, `精炼摘要，包含数量和时间分布`)
    }
    return raw
  }

  // stats 或 detail
  const statsText = buildStatsResult(records, target)
  if (mode === 'stats') {
    return statsText
  }

  // detail 模式
  const sample = records.slice(-30)
  const samples = sample.map(r => {
    const who = r.talkerAlias || r.talkerName || '?'
    const text = r.text || `[${r.typeName}]`
    return `[${who}] ${text.slice(0, 80)}`
  }).join('\n')

  const raw = [
    statsText,
    '\n最近消息：',
    samples,
  ].join('\n')

  if (raw.length > 600 && compressFn) {
    return await compressFn(raw, maxCount, '简洁概括消息特点和内容分布')
  }
  return raw
}

// ============================================================
// 工具清单
// ============================================================
export function buildTools() {
  return [
    {
      type: 'function',
      function: {
        name: 'queryWechat',
        description: '查询微信聊天记录。可查群聊、查某成员、搜关键词。mode=stats返回统计摘要；mode=search返回匹配的消息列表；mode=detail返回统计+消息样本供分析。结果自动压缩（超长内容只返回关键摘要），无需再调用optimizeReply。',
        parameters: {
          type: 'object',
          properties: {
            mode: {
              type: 'string',
              enum: ['stats', 'search', 'detail', 'images'],
              description: 'stats=统计摘要(默认)，search=搜文本消息，detail=统计+样本，images=搜图片/视频/附件消息'
            },
            speaker: { type: 'string', description: '发言人名字（模糊匹配）' },
            room:   { type: 'string', description: '群名称（精确匹配）' },
            friend: { type: 'string', description: '好友名字' },
            query:  { type: 'string', description: '搜索关键词（仅 mode=search 时必填）' },
            limit:  { type: 'number', description: '最多加载条数（默认2000）' }
          },
          required: ['mode']
        }
      }
    }
  ]
}

// ============================================================
// Session 管理（持久化到文件，进程重启不丢）
// ============================================================
const SESSION_DIR = path.join(process.cwd(), '.data/sessions')
const SESSION_TTL = 30 * 60 * 1000
const MAX_TURNS = 10
const MAX_SESSION_AGE = 7 * 24 * 60 * 60 * 1000

try {
  fs.mkdirSync(SESSION_DIR, { recursive: true })
} catch {}

function loadSessionFile(sessionId) {
  const safeId = sessionId.replace(/[^a-zA-Z0-9_:-]/g, '_')
  const filePath = path.join(SESSION_DIR, `${safeId}.json`)
  if (!fs.existsSync(filePath)) return null
  try {
    const raw = fs.readFileSync(filePath, 'utf-8')
    return JSON.parse(raw)
  } catch {
    return null
  }
}

function saveSessionFile(sessionId, entry) {
  const safeId = sessionId.replace(/[^a-zA-Z0-9_:-]/g, '_')
  const filePath = path.join(SESSION_DIR, `${safeId}.json`)
  try {
    fs.writeFileSync(filePath, JSON.stringify(entry, null, 2), 'utf-8')
  } catch (e) {
    console.warn('⚠️ session 保存失败:', e.message)
  }
}

export function cleanExpiredSessions() {
  try {
    const files = fs.readdirSync(SESSION_DIR)
    const now = Date.now()
    for (const file of files) {
      if (!file.endsWith('.json')) continue
      const filePath = path.join(SESSION_DIR, file)
      try {
        const raw = fs.readFileSync(filePath, 'utf-8')
        const entry = JSON.parse(raw)
        if (now - entry.ts > MAX_SESSION_AGE || now - entry.ts > SESSION_TTL) {
          fs.unlinkSync(filePath)
          console.log(`🗑️ 清理过期 session: ${file}`)
        }
      } catch {}
    }
  } catch {}
}

cleanExpiredSessions()

/**
 * 加载对话历史（自动取 TTL 过滤）
 * @param {string} sessionId
 * @returns {Array} [{role, content}, ...]
 */
export function loadSession(sessionId) {
  if (!sessionId) return []
  const entry = loadSessionFile(sessionId)
  if (!entry) return []
  // TTL 过期则删除文件
  if (Date.now() - entry.ts > SESSION_TTL) {
    try {
      const safeId = sessionId.replace(/[^a-zA-Z0-9_:-]/g, '_')
      fs.unlinkSync(path.join(SESSION_DIR, `${safeId}.json`))
    } catch {}
    return []
  }
  return entry.turns
}

/**
 * 保存对话历史到文件
 * @param {string} sessionId
 * @param {Array} turns
 */
export function saveSession(sessionId, turns) {
  if (!sessionId) return
  saveSessionFile(sessionId, {
    ts: Date.now(),
    turns: turns.slice(-MAX_TURNS),
  })
}

/**
 * 从完整 messages 数组中提取纯对话轮次（去掉 tool_calls / tool 结果）
 * 工具结果不进 session，防止 context 膨胀
 */
export function extractDialogTurns(messages) {
  const turns = []
  for (const m of messages) {
    if (m.role === 'system') {
      turns.push(m)
    } else if (m.role === 'user') {
      const text = Array.isArray(m.content)
        ? m.content.find(c => c.type === 'text')?.text || ''
        : m.content
      turns.push({ role: 'user', content: text })
    } else if (m.role === 'assistant' && !m.tool_calls) {
      turns.push({ role: 'assistant', content: m.content || '' })
    }
    // tool role 和带 tool_calls 的 assistant 消息：跳过，不进入 session
  }
  return turns
}

// ============================================================
// 核心 Agent 循环
// ============================================================
/**
 * 构建 Agent 实例。
 *
 * @param {object} apiConfig       - { openai, chosenModel }
 * @param {object} options
 * @param {string} [options.systemPromptBase] - 基础 system prompt
 * @param {string} [options.modelReasoning]   - 是否为推理模型（影响 reasoning_content 处理）
 * @param {string} [options.botName]          - 机器人名称（用于 @提及）
 * @param {function} [options.getReasoningContent] - 从 API 响应提取 reasoning_content
 * @param {boolean} [options.enableStreaming]  - 是否启用流式输出（默认 false）
 * @returns {function} getReply(prompt, options) -> string
 */
export function createAgent(apiConfig, options = {}) {
  const { openai, chosenModel } = apiConfig
  const {
    systemPromptBase = '你是黑瑞，微信里的毒舌损友。风格：毒舌、调侃、幽默，该损就损。',
    modelReasoning = false,
    botName = '',
    getReasoningContent = (msg) => msg.reasoning_content || '',
    compressFn = smartCompress,
    enableStreaming = false,
  } = options

  const availableTools = buildTools()

  return async function getReply(prompt, opts = {}) {
    const {
      img_url = '',
      roomName = '',
      askerName = '',
      sessionId = '',
    } = opts

    // 构建 system prompt
    let systemExtra = ''
    if (roomName) {
      systemExtra += `\n当前所在群：「${roomName}」（查该群消息时 room 参数填"${roomName}"）`
    }
    if (askerName) {
      systemExtra += `\n提问者：${askerName}（群聊回复时无需你加 @，应用层会自动处理）`
    }
    systemExtra += `\n\n🛠️ 工具使用规则（重要）：\n` +
      `【queryWechat】—— 只有当你需要查"谁说了什么"、"群里在聊什么"、"某话题的讨论"时才用。\n` +
      `不需要查聊天记录时（如闲聊、回答常识、写作等）直接回复，不要调用工具。\n` +
      `\n` +
      `【触发词判断】—— 以下场景必须用 queryWechat：\n` +
      `  - "群里/群里谁..."、"@某人说了什么"、"查一下..."、"统计..."\n` +
      `  - "有人提到..."、"说说关于..."、"大家觉得..."、"昨天/上周群里..."\n` +
      `  - "发言记录"、"聊天记录"、"多少人说过"\n` +
      `  \n` +
      `【mode 参数选择】：\n` +
      `  - 想了解"谁发言多、活跃时段"等统计 → mode='stats'\n` +
      `  - 想找"包含某关键词的消息" → mode='search'（必须传 query 参数）\n` +
      `  - 想分析"某人说的话有什么特点" → mode='detail'\n` +
      `  - 想找"图片/视频/附件" → mode='images'\n` +
      `  - 找人发言记录 → 用 speaker 参数 + mode='stats'\n` +
      `  \n` +
      `【room 参数】：默认填当前所在群（由应用层自动注入）。\n` +
      `【重要】：queryWechat 结果已自动压缩，无需再调用任何优化工具。\n` +
      `【禁止】：不要在回复末尾加上"已查询微信消息"等说明，结果自己会说话。\n`

    const systemPrompt = systemPromptBase + systemExtra

    console.log('🚀🚀🚀 /', prompt.slice(0, 60), '| room:', roomName, '| asker:', askerName)

    // 从 session 恢复对话历史（不含工具结果）
    const turns = loadSession(sessionId)
    const messages = []
    if (turns.length === 0) {
      messages.push({ role: 'system', content: systemPrompt })
    } else {
      const systemTurn = turns.find(t => t.role === 'system')
      if (systemTurn) messages.push(systemTurn)
      else messages.push({ role: 'system', content: systemPrompt })
      for (const t of turns.slice(1)) messages.push(t)
    }

    // 追加当前用户消息
    if (img_url && img_url !== '') {
      messages.push({
        role: 'user',
        content: [
          { type: 'text', text: prompt },
          { type: 'image_url', image_url: { url: img_url } },
        ],
      })
    } else {
      messages.push({ role: 'user', content: prompt })
    }

    // ── ReAct 循环：最多 3 轮 ──────────────────────────────
    for (let round = 0; round < 3; round++) {
      const kwargs = {
        messages,
        model: chosenModel,
        max_tokens: 1024,
        tools: availableTools,
        tool_choice: 'auto',
      }

      const response = await withRetry(
        () => openai.chat.completions.create(kwargs),
        { maxRetries: 3, baseDelay: 1000 }
      )
      const msg = response.choices[0].message

      // 推理模型需要回传 reasoning_content
      const reasoningContent = getReasoningContent(msg)

      // ── 无工具调用 → 最终回复 ────────────────────────────
      if (!msg.tool_calls || msg.tool_calls.length === 0) {
        const reply = cleanReply(msg.content || '')
        messages.push({ role: 'assistant', content: reply })
        saveSession(sessionId, extractDialogTurns(messages))
        return reply
      }

      // ── 有工具调用 → 顺序执行每个工具 ───────────────────
      for (const tc of msg.tool_calls) {
        const fn = tc.function
        let args = {}
        try {
          args = JSON.parse(fn.arguments || '{}')
        } catch (e) {
          const errResult = `工具参数解析失败: ${fn.name}，请检查参数格式`
          messages.push({ role: 'tool', tool_call_id: tc.id, content: errResult })
          continue
        }
        console.log(`🔧 [${round}] ${fn.name}`, args)

        let result = ''
        if (fn.name === 'queryWechat') {
          result = await callQueryWechatHttp({
            mode: args.mode || 'stats',
            speaker: args.speaker,
            room: args.room,
            friend: args.friend,
            query: args.query,
            limit: args.limit || 2000,
          })
        } else {
          result = `未知工具: ${fn.name}`
        }

        // 统一注入推理内容（无论是否为推理模型，有就给）
        const assistantMsg = { role: 'assistant', content: null, tool_calls: [tc] }
        if (reasoningContent) {
          assistantMsg.reasoning_content = reasoningContent
        }
        messages.push(assistantMsg)
        messages.push({ role: 'tool', tool_call_id: tc.id, content: result })
      }
      // 循环继续，把工具结果给模型，让它判断是否继续或结束
    }

    // 超轮数限制，取最后一条 assistant 消息
    const last = messages[messages.length - 1]
    const fallback = (last?.content && typeof last.content === 'string')
      ? last.content.slice(0, 300)
      : '...处理超时'
    saveSession(sessionId, extractDialogTurns(messages))
    return fallback
  }
}
