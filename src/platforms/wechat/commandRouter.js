import { analyzeWechatMessages } from '../../analysis/wechatAnalyzer.js'
import { getWechatRuntimeConfig } from '../../config/env.js'
import { runOpenCli } from '../../adapters/opencli.js'

function stripMention(content, botName) {
  return content.replace(botName, '').trim()
}

function parseTarget(tokens) {
  const type = tokens[1]
  const value = tokens.slice(2).join(' ').trim()

  if (['群', '群聊', 'room', 'group'].includes(type)) {
    return { room: value }
  }

  if (['好友', 'friend', 'contact'].includes(type)) {
    return { friend: value }
  }

  if (['说', '发言', 'talk', 'speaker'].includes(type)) {
    return { speaker: value }
  }

  // 显式指定了发言人（如：/分析 @张三）
  if (type && (type.startsWith('@') || type.startsWith('说'))) {
    return { speaker: value || type.replace('@', '') }
  }

  return {}
}

export async function handleWechatCommand(content, context = {}) {
  const config = getWechatRuntimeConfig()
  const normalized = stripMention(content, config.botName)

  if (!normalized.startsWith(config.commandPrefix)) {
    return { handled: false }
  }

  const commandLine = normalized.slice(config.commandPrefix.length).trim()
  const tokens = commandLine.split(/\s+/).filter(Boolean)
  const command = tokens[0]

  if (['分析', 'analyze', '统计', 'stats'].includes(command)) {
    const statsOnly = ['统计', 'stats'].includes(command)
    let target = parseTarget(tokens)

    // 如果 parseTarget 没识别到发言人，尝试从自然语言中提取
    // 匹配 "xxx的发言"、"xxx说"、"@xxx" 等模式
    if (!target.speaker && !target.room && !target.friend) {
      const rest = tokens.slice(1).join(' ')

      // 单token情况（如 "/分析 彭宇的发言" 整体算一个token的情况做兜底）
      const singlePatterns = [
        /([\u4e00-\u9fa5]{1,6})的(?:发言|说|聊聊?)/,
        /([\u4e00-\u9fa5]{1,4})\s+(?:说|发言)/,
        /@(\S+)/
      ]
      for (const p of singlePatterns) {
        const m = rest.match(p)
        if (m && m[1] && !['一下', '今天', '昨天', '总结', '分析'].includes(m[1])) {
          target.speaker = m[1]
          break
        }
      }
    }
    const result = await analyzeWechatMessages({
      ...target,
      serviceType: context.serviceType,
      dataDir: config.dataDir,
      statsOnly,
    })

    if (statsOnly || !result.analysis) {
      return {
        handled: true,
        reply: [
          `${result.target}`,
          `消息数：${result.stats.totalMessages}`,
          `文本消息：${result.stats.textMessages}`,
          `平均长度：${result.stats.averageTextLength}`,
          `高频发言：${result.stats.topSpeakers.map((item) => `${item.name}(${item.count})`).join('，') || '无'}`,
        ].join('\n'),
      }
    }

    return {
      handled: true,
      reply: result.analysis,
    }
  }

  if (command === 'opencli') {
    if (!config.enableRemoteOpenCli) {
      return {
        handled: true,
        reply: '远程 OpenCLI 执行未开启。需要在 .env 中显式设置 ENABLE_REMOTE_OPENCLI=true。',
      }
    }

    await runOpenCli(tokens.slice(1))
    return {
      handled: true,
      reply: 'OpenCLI 命令已执行，结果请看本机控制台。',
    }
  }

  return { handled: false }
}
