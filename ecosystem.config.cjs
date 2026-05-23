const path = require('path')
const ROOT = '/Users/pyu/wechat-bot'

module.exports = {
  apps: [
    // Python Agent 服务（用 shell 脚本启动）
    {
      name: 'python-agent',
      script: `${ROOT}/scripts/start-python-agent.sh`,
      env: {
        PATH: '/Users/pyu/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
        PYTHON_AGENT_PORT: '3002',
      },
      error_file: `${ROOT}/.pm2/logs/python-agent-error.log`,
      out_file: `${ROOT}/.pm2/logs/python-agent-out.log`,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      autorestart: true,
      watch: false,
      max_memory_restart: '512M',
      restart_delay: 1000,
      instances: 1,
      daemon: false,
    },
    // Node.js Wechaty Bot（依赖 Python Agent）
    {
      name: 'wechat-bot',
      script: `${ROOT}/cli.js`,
      args: 'start -s Mimo',
      interpreter: 'none',
      cwd: ROOT,
      env: {
        PATH: '/Users/pyu/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
        SERVICE_TYPE: 'Mimo',
        PYTHON_AGENT_URL: 'http://localhost:3002',
        PYTHON_AGENT_HOST: 'localhost',
        PYTHON_AGENT_PORT: '3002',
        HTTP_API_PORT: '3001',
      },
      env_production: {
        NODE_ENV: 'production',
      },
      error_file: `${ROOT}/.pm2/logs/wechat-bot-error.log`,
      out_file: `${ROOT}/.pm2/logs/wechat-bot-out.log`,
      log_date_format: 'YYYY-MM-DD HH:mm:ss',
      autorestart: true,
      watch: false,
      max_memory_restart: '1G',
      restart_delay: 3000,
      instances: 1,
      daemon: false,
    },
  ],
}