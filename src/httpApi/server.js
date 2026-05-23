/**
 * HTTP API Server — Wechat-Bot Node.js 侧接口
 *
 * Phase 1 解耦目标：
 * 将 queryWechat() 暴露为 HTTP 端点，供 Python Agent 调用
 *
 * 启动方式：
 *   import { startHttpApi } from './src/httpApi/server.js'
 *   await startHttpApi({ port: 3001 })
 *
 * 端点：
 *   GET  /health            — 健康检查
 *   POST /api/queryWechat   — 查询微信消息记录
 */

import http from 'http'
import { URL } from 'url'
import { queryWechat } from '../agent-core/index.js'
import { smartCompress } from '../agent-core/index.js'

const PORT = process.env.HTTP_API_PORT || 3001

/**
 * 解析请求体（JSON）
 */
function parseBody(req) {
  return new Promise((resolve, reject) => {
    let body = ''
    req.on('data', chunk => { body += chunk })
    req.on('end', () => {
      try {
        resolve(body ? JSON.parse(body) : {})
      } catch {
        reject(new Error('Invalid JSON'))
      }
    })
    req.on('error', reject)
  })
}

/**
 * 发送 JSON 响应
 */
function sendJson(res, statusCode, data) {
  res.writeHead(statusCode, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    'Access-Control-Allow-Headers': 'Content-Type',
  })
  res.end(JSON.stringify(data))
}

/**
 * 处理 POST /api/queryWechat
 * 请求体：{ mode, speaker, room, friend, query, limit, sessionId }
 * 返回：{ result: string }
 */
async function handleQueryWechat(req, res, pathname, body) {
  if (pathname !== '/api/queryWechat') return false

  try {
    const {
      mode = 'stats',
      speaker = undefined,
      room = undefined,
      friend = undefined,
      query = undefined,
      limit = 2000,
    } = body

    const result = await queryWechat(
      { mode, speaker, room, friend, query, limit },
      { maxCount: 4, compressFn: smartCompress }
    )

    sendJson(res, 200, { result })
  } catch (err) {
    console.error('❌ /api/queryWechat error:', err.message)
    sendJson(res, 500, { error: err.message })
  }
  return true
}

/**
 * 主请求处理
 */
async function handleRequest(req, res) {
  // CORS 预检
  if (req.method === 'OPTIONS') {
    sendJson(res, 204, null)
    return
  }

  const url = new URL(req.url, `http://localhost:${PORT}`)
  const pathname = url.pathname

  // GET /health
  if (req.method === 'GET' && pathname === '/health') {
    sendJson(res, 200, { status: 'ok', service: 'wechat-bot-http-api' })
    return
  }

  // POST /api/* 需要请求体
  if (req.method === 'POST') {
    try {
      const body = await parseBody(req)
      if (await handleQueryWechat(req, res, pathname, body)) return
    } catch (err) {
      sendJson(res, 400, { error: err.message })
      return
    }
  }

  // 404
  sendJson(res, 404, { error: 'Not found' })
}

/**
 * 启动 HTTP API Server
 * @param {object} options
 * @param {number} [options.port]  监听端口，默认 3001
 * @returns {Promise<http.Server>}
 */
export function startHttpApi({ port = PORT } = {}) {
  return new Promise((resolve, reject) => {
    const server = http.createServer(handleRequest)

    server.on('error', (err) => {
      if (err.code === 'EADDRINUSE') {
        console.warn(`⚠️  HTTP API 端口 ${port} 已被占用，尝试 +1...`)
        server.listen(port + 1, () => {
          console.log(`✅ HTTP API Server 已启动: http://localhost:${port + 1}`)
          resolve(server)
        })
      } else {
        reject(err)
      }
    })

    server.listen(port, () => {
      console.log(`✅ HTTP API Server 已启动: http://localhost:${port}`)
      resolve(server)
    })
  })
}

// 直接运行：node src/httpApi/server.js
if (process.argv[1] && process.argv[1].endsWith('server.js') && process.argv[1].includes('httpApi')) {
  startHttpApi({ port: Number(process.env.HTTP_API_PORT || 3001) })
    .then(() => console.log(`🔌 HTTP API 监听中...`))
    .catch(err => { console.error(err); process.exit(1) })
}
