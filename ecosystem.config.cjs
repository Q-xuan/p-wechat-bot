module.exports = {
  apps: [{
    name: 'wechat-bot',
    script: 'cli.js',
    args: 'start -s Mimo',
    interpreter: 'none',
    env: {
      PATH: '/Users/pyu/.nvm/versions/node/v22.22.0/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
      SERVICE_TYPE: 'Mimo',
      // 其他环境变量可在 .env 中配置，PM2 会自动加载同名变量
    },
    // PM2 重启后自动加载 .env（需要 pm2-dotenv 插件）
    env_production: {
      NODE_ENV: 'production',
    },
    // 日志
    error_file: '.pm2/logs/wechat-bot-error.log',
    out_file: '.pm2/logs/wechat-bot-out.log',
    log_date_format: 'YYYY-MM-DD HH:mm:ss',
    // 自动重启
    autorestart: true,
    watch: false,
    max_memory_restart: '1G',
    // 重启策略：异常退出 1 秒后重启，正常退出不重启
    restart_delay: 1000,
    // 进程数量（微信机器人只能单实例）
    instances: 1,
    // 关闭守护模式（设为 true 会在 PM2 退出后关闭所有进程）
    daemon: false,
  }],
};
