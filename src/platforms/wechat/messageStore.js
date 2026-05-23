import fs from 'fs'
import path from 'path'

const MESSAGE_FILE = 'messages.jsonl'

function ensureDir(dir) {
  fs.mkdirSync(dir, { recursive: true })
}

export function getMessageStorePath(dataDir = '.data/wechat') {
  return path.resolve(process.cwd(), dataDir, MESSAGE_FILE)
}

export async function captureWechatMessage(message, bot, options = {}) {
  const dataDir = options.dataDir || '.data/wechat'
  const storeMessages = options.storeMessages !== false
  if (!storeMessages) return null

  const talker = message.talker()
  const receiver = message.to()
  const room = message.room()
  const isText = message.type() === bot.Message.Type.Text
  const roomName = room ? await room.topic() : ''
  const talkerAlias = talker ? await talker.alias() : ''
  const talkerName = talker ? await talker.name() : ''
  const receiverName = receiver ? await receiver.name() : ''

  const record = {
    id: message.id,
    timestamp: new Date().toISOString(),
    type: message.type(),
    typeName: bot.Message.Type[message.type()] || String(message.type()),
    isText,
    isRoom: Boolean(room),
    roomName,
    talkerName,
    talkerAlias,
    receiverName,
    text: isText ? message.text() : '',
    self: Boolean(talker?.self?.()),
  }

  const storePath = getMessageStorePath(dataDir)
  ensureDir(path.dirname(storePath))
  fs.appendFileSync(storePath, `${JSON.stringify(record)}\n`, 'utf8')

  return record
}

export function loadWechatMessages(options = {}) {
  const storePath = getMessageStorePath(options.dataDir)
  if (!fs.existsSync(storePath)) return []

  const lines = fs
    .readFileSync(storePath, 'utf8')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)

  const limit = Number(options.limit || 0)
  const selectedLines = limit > 0 ? lines.slice(-limit) : lines

  return selectedLines
    .map((line) => {
      try {
        return JSON.parse(line)
      } catch (error) {
        return null
      }
    })
    .filter(Boolean)
}

export function filterWechatMessages(records, filters = {}) {
  const startTime = filters.start ? new Date(filters.start).getTime() : null
  const endTime = filters.end ? new Date(filters.end).getTime() : null
  const query = filters.query ? filters.query.toLowerCase() : ''
  const speaker = filters.speaker ? filters.speaker.toLowerCase() : ''

  return records.filter((record) => {
    if (filters.room && record.roomName !== filters.room) return false
    if (filters.friend) {
      const names = [record.talkerName, record.talkerAlias, record.receiverName].filter(Boolean)
      if (!names.includes(filters.friend)) return false
    }
    if (speaker) {
      const talker = (record.talkerAlias || record.talkerName || '').toLowerCase()
      if (!talker.includes(speaker)) return false
    }
    if (
      query &&
      !String(record.text || '')
        .toLowerCase()
        .includes(query)
    )
      return false
    if (startTime && new Date(record.timestamp).getTime() < startTime) return false
    if (endTime && new Date(record.timestamp).getTime() > endTime) return false
    return true
  })
}
