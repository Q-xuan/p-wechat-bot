function lazyServe(loader, exportName) {
  return async (...args) => {
    const module = await loader()
    return module[exportName](...args)
  }
}

/**
 * 获取 AI 服务
 * @param serviceType 服务类型
 * @returns {Function}
 */
export function getServe(serviceType) {
  switch (serviceType) {
    case 'ChatGPT':
      return lazyServe(() => import('../openai/index.js'), 'getGptReply')
    case 'doubao':
      return lazyServe(() => import('../doubao/index.js'), 'getDoubaoReply')
    case 'deepseek':
      return lazyServe(() => import('../deepseek/index.js'), 'getDeepseekReply')
    case 'MiniMax':
      return lazyServe(() => import('../minimax/index.js'), 'getMinimaxReply')
    case 'Mimo':
      // Phase 2: 优先走 Python Agent 服务
      if (process.env.PYTHON_AGENT_URL) {
        return buildPythonAgentServe('Mimo')
      }
      return lazyServe(() => import('../mimo/index.js'), 'getMimoReply')
    case 'Kimi':
      return lazyServe(() => import('../kimi/index.js'), 'getKimiReply')
    case 'Xunfei':
      return lazyServe(() => import('../xunfei/index.js'), 'getXunfeiReply')
    case 'deepseek-free':
      return lazyServe(() => import('../deepseek-free/index.js'), 'getDeepSeekFreeReply')
    case '302AI':
      return lazyServe(() => import('../302ai/index.js'), 'get302AiReply')
    case 'dify':
      return lazyServe(() => import('../dify/index.js'), 'getDifyReply')
    case 'ollama':
      return lazyServe(() => import('../ollama/index.js'), 'getOllamaReply')
    case 'tongyi':
      return lazyServe(() => import('../tongyi/index.js'), 'getTongyiReply')
    case 'claude':
      return lazyServe(() => import('../claude/index.js'), 'getClaudeReply')
    case 'pi':
      return lazyServe(() => import('../pi/index.js'), 'getPiReply')
    default:
      return lazyServe(() => import('../openai/index.js'), 'getGptReply')
  }
}

// ============================================================
// Python Agent 服务调用（Phase 2）
// ============================================================

const PYTHON_AGENT_HOST = process.env.PYTHON_AGENT_HOST || 'localhost'
const PYTHON_AGENT_PORT = process.env.PYTHON_AGENT_PORT || '3002'

/**
 * 调用 Python Agent HTTP 服务获取回复
 */
async function callPythonAgent({ prompt, sessionId, roomName, askerName, platform }) {
  const url = `http://${PYTHON_AGENT_HOST}:${PYTHON_AGENT_PORT}/reply`
  let attempt = 0
  const maxRetries = 3

  while (attempt < maxRetries) {
    try {
      const controller = new AbortController()
      const timeout = setTimeout(() => controller.abort(), 30000)

      const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt, sessionId, roomName, askerName, platform }),
        signal: controller.signal,
      })

      clearTimeout(timeout)

      if (!res.ok) {
        const text = await res.text().catch(() => '')
        throw new Error(`Python Agent HTTP ${res.status}: ${text}`)
      }

      const json = await res.json()
      return json.reply
    } catch (err) {
      attempt++
      if (attempt >= maxRetries) throw err
      await new Promise(r => setTimeout(r, 1000 * attempt))
    }
  }
}

/**
 * 构建 Python Agent 服务调用函数
 */
function buildPythonAgentServe(platform) {
  return async ({ prompt, sessionId, roomName, askerName }) => {
    return callPythonAgent({ prompt, sessionId, roomName, askerName, platform })
  }
}
