module.exports = {
  apps: [
    {
      name: "web-frontend",
      // 指向 next 的二进制执行文件
      script: "./node_modules/next/dist/bin/next",
      args: "start",
      cwd: "./frontend",
      // 默认就是 node 模式
      env: {
        NODE_ENV: "production",
        PORT: 3000
      }
    },
    {
      name: "python-api",
      // 脚本路径，相对于下面的 cwd
      script: "app.py",
      // 直接使用系统 python 解释器，避免 shell 产生多余进程
      interpreter: "python",
      cwd: "./backend",
      // 必须确保 kill_timeout 足够，防止重启时旧进程没杀掉
      kill_timeout: 3000,
      wait_ready: true,
      env: {
        NODE_ENV: "production",
        PYTHONIOENCODING: "utf-8",
        PYTHONUNBUFFERED: "1"
      }
    }
  ]
}
