module.exports = {
  apps: [
    // ==================== 后端服务 ====================
    {
      name: "discord-backend",
      script: "backend/app.py",
      // 跨平台Python解释器配置
      // Windows: 通常是 "python"
      // Mac/Linux: 通常是 "python3"
      // PM2会自动查找系统中的Python
      interpreter: process.platform === 'win32' ? 'python' : 'python3',
      instances: 1,           // 【关键】强制单实例，避免多进程冲突
      exec_mode: "fork",      // Python脚本使用fork模式
      autorestart: true,
      watch: false,           // 【关键】关闭文件监听，避免无限重启
      max_memory_restart: "1G",
      env: {
        NODE_ENV: "production",
        FLASK_ENV: "production",
        PYTHONUNBUFFERED: "1"  // 确保日志实时输出
      },
      error_file: "./logs/backend-error.log",
      out_file: "./logs/backend-out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z"
    },

    // ==================== 前端服务 ====================
    {
      name: "discord-frontend",
      cwd: "./frontend",      // 工作目录设置为frontend文件夹
      script: "npm",
      args: "start",          // 执行 npm start
      instances: 1,
      exec_mode: "fork",
      autorestart: true,
      watch: false,
      max_memory_restart: "500M",
      env: {
        NODE_ENV: "production",
        PORT: 3000             // Next.js默认端口
      },
      error_file: "../logs/frontend-error.log",
      out_file: "../logs/frontend-out.log",
      log_date_format: "YYYY-MM-DD HH:mm:ss Z"
    }
  ]
};
