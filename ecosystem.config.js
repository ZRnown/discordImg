module.exports = {
  apps: [
    {
      name: "discord-backend",
      script: "backend/app.py",
      interpreter: "python3", // 或者你的虚拟环境路径，例如 "venv/bin/python"
      instances: 1,           // 【关键】强制单实例
      exec_mode: "fork",      // Python 脚本通常使用 fork 模式
      autorestart: true,
      watch: false,           // 【关键】默认关闭监听，避免日志写入导致重启
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
        FLASK_ENV: "production",
        PYTHONUNBUFFERED: "1" // 确保日志实时输出
      },
      // 如果你想开启 watch，必须忽略 data 目录，否则会死循环
      // watch: ["backend"],
      // ignore_watch: ["backend/data", "backend/logs", "backend/__pycache__", "*.db", "*.log"],
    }
  ]
};
