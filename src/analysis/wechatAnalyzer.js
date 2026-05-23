import { getServe } from '../wechaty/serve.js'
import { filterWechatMessages, loadWechatMessages } from '../platforms/wechat/messageStore.js'

function increment(map, key, step = 1) {
  if (!key) return
  map.set(key, (map.get(key) || 0) + step)
}

function topEntries(map, limit = 10) {
  return [...map.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit)
    .map(([name, count]) => ({ name, count }))
}

export function buildWechatStats(records) {
  const speakers = new Map()
  const rooms = new Map()
  const hourly = new Map()
  let textMessages = 0
  let totalTextLength = 0

  for (const record of records) {
    increment(speakers, record.talkerAlias || record.talkerName || 'unknown')
    increment(rooms, record.roomName || 'private')
    if (record.timestamp) {
      increment(hourly, new Date(record.timestamp).getHours().toString().padStart(2, '0'))
    }
    if (record.text) {
      textMessages += 1
      totalTextLength += record.text.length
    }
  }

  return {
    totalMessages: records.length,
    textMessages,
    averageTextLength: textMessages ? Number((totalTextLength / textMessages).toFixed(1)) : 0,
    topSpeakers: topEntries(speakers),
    topRooms: topEntries(rooms),
    hourly: topEntries(hourly, 24).sort((a, b) => a.name.localeCompare(b.name)),
  }
}

export function buildWechatAnalysisPrompt({ records, stats, target }) {
  const recentMessages = records
    .slice(-120)
    .map((record) => {
      const speaker = record.talkerAlias || record.talkerName || 'unknown'
      return `[${record.timestamp}] ${speaker}: ${record.text || `[${record.typeName}]`}`
    })
    .join('\n')

  return [
    '你是一个严谨的中文聊天数据分析助手。',
    '请基于用户显式提供的本地微信聊天记录做分析，不要编造记录之外的事实。',
    '输出结构：1. 关键统计；2. 主要话题；3. 互动模式；4. 风险或误读提醒；5. 可执行建议。',
    `分析对象：${target}`,
    `基础统计：${JSON.stringify(stats, null, 2)}`,
    '最近消息样本：',
    recentMessages || '无文本消息样本。',
  ].join('\n\n')
}

export async function analyzeWechatMessages(options = {}) {
  const allRecords = loadWechatMessages({
    dataDir: options.dataDir,
    limit: options.limit || 5000,
  })

  const records = filterWechatMessages(allRecords, {
    room: options.room,
    friend: options.friend,
    speaker: options.speaker,
    query: options.query,
    start: options.start,
    end: options.end,
  })

  const stats = buildWechatStats(records)
  const target =
    options.speaker
      ? `群友「${options.speaker}」`
      : options.room
        ? `群聊「${options.room}」`
        : options.friend
          ? `好友「${options.friend}」`
          : '全部本地记录'

  if (options.statsOnly || !records.length) {
    return {
      target,
      stats,
      analysis: records.length ? '' : '没有匹配到可分析的本地微信消息。',
    }
  }

  const getReply = getServe(options.serviceType || 'ChatGPT')
  const prompt = buildWechatAnalysisPrompt({ records, stats, target })
  const analysis = await getReply(prompt)

  return { target, stats, analysis }
}
