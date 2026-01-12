# Discord 营销系统 - 部署指南

## 🚀 快速开始（3 步）

### 1. 上传代码到服务器

```bash
# 在本地执行
cd /Users/wanghaixin/Development/DiscordBotWork/DiscordImg/discord-marketing-system\ copy
git add .
git commit -m "Add startup and stop scripts"
git push origin main
```

### 2. SSH 登录服务器并拉取代码

```bash
ssh root@69.30.204.184
su administrator
cd ~/discordImg
git pull origin main
```

### 3. 启动服务

```bash
chmod +x start.sh stop.sh
./start.sh
```

## ✅ 验证服务

```bash
# 检查进程
ps aux | grep -E "(next|python app.py)" | grep -v grep

# 测试 API
curl -I http://69.30.204.184:3000/api/logs?endpoint=recent
curl -I http://69.30.204.184:5001/api/shops
```

浏览器访问：
- 前端: http://69.30.204.184:3000
- 后端 API: http://69.30.204.184:5001/api/shops

## 📋 常用命令

```bash
# 启动服务
~/discordImg/start.sh

# 停止服务
~/discordImg/stop.sh

# 重启服务
~/discordImg/stop.sh && ~/discordImg/start.sh

# 查看前端日志
tail -f ~/discordImg/frontend.log

# 查看后端日志
tail -f ~/discordImg/backend.log
```

## 🔍 问题排查

### 问题1: 端口被占用
```bash
# 查看端口占用
lsof -i :3000
lsof -i :5001

# 杀死占用进程
kill -9 <PID>
```

### 问题2: 服务启动失败
```bash
# 查看详细日志
cat ~/discordImg/frontend.log
cat ~/discordImg/backend.log
```

### 问题3: Cookie 401/403 错误
```bash
# 确认环境变量已设置
grep "NODE_ENV\|NEXT_PUBLIC_BACKEND_URL" ~/discordImg/frontend.log

# 应该看到：
# NODE_ENV=development
# NEXT_PUBLIC_BACKEND_URL=http://your-server-ip:5001
```

## 🎯 核心原理

**零代码修改解决方案：**

1. **NODE_ENV=development**
   - 禁用 Cookie 的 Secure 属性
   - 解决 HTTP 无法传输 Cookie 导致的 401/403 错误

2. **NEXT_PUBLIC_BACKEND_URL=http://your-server-ip:5001**
   - 指定后端服务器地址
   - 解决前端访问 localhost 导致的 404 错误

## 📝 环境变量说明

### 前端环境变量

| 环境变量 | 作用 | 默认值 | 服务器设置 |
|---------|------|--------|-----------|
| **NODE_ENV** | 控制 Cookie 的 secure 属性 | development | **development** ❗ |
| **NEXT_PUBLIC_BACKEND_URL** | 后端 API 地址 | http://127.0.0.1:5001 | **http://your-server-ip:5001** ❗ |

### 后端环境变量 (config.py)

| 环境变量 | 作用 | 默认值 | 说明 |
|---------|------|--------|------|
| **HOST** | 服务器监听地址 | 0.0.0.0 | 0.0.0.0监听所有接口 |
| **PORT** | 服务器端口 | 5001 | Flask应用端口 |
| **DEBUG** | 调试模式 | True | 生产环境设为False |
| **DEVICE** | 计算设备 | cpu | cpu/cuda |
| **SECRET_KEY** | 会话密钥 | dev-secret-key | 生产环境必须修改 |
| **SESSION_LIFETIME** | 会话生命周期(秒) | 86400 | 24小时 |
| **CORS_ORIGINS** | 允许的CORS源 | localhost:3000,127.0.0.1:3000 | 逗号分隔的URL列表 |
| **DOWNLOAD_THREADS** | 图片下载线程数 | 10 | 根据服务器性能调整 |
| **FEATURE_EXTRACT_THREADS** | 特征提取线程数 | 4 | CPU密集型任务 |
| **SCRAPE_THREADS** | 商品抓取线程数 | 10 | I/O密集型任务 |
| **DINO_MODEL_NAME** | DINOv2模型 | facebook/dinov2-small | small/base/large |
| **YOLO_MODEL_PATH** | YOLO模型路径 | yolov8s-world.pt | 目标检测模型 |
| **USE_YOLO_CROP** | 启用YOLO裁剪 | True | True/False |
| **REQUEST_TIMEOUT** | HTTP请求超时(秒) | 30 | 网络请求超时时间 |
| **MAX_RETRIES** | 最大重试次数 | 3 | 请求失败重试次数 |

## ⚙️ 高级配置

### 修改服务端口

编辑 `start.sh`:

```bash
# 后端端口（修改 backend/app.py）
PORT=8001

# 前端端口（修改 package.json 的启动脚本）
PORT=4000
```

### 修改服务器 IP

如果服务器 IP 变更，只需修改 `start.sh`:

```bash
# 找到这一行
NEXT_PUBLIC_BACKEND_URL=http://新IP:5001
```

## 🔄 持久化运行（可选）

如果希望服务在服务器重启后自动运行，使用 systemd：

```bash
# 创建服务文件
sudo nano /etc/systemd/system/discord-marketing.service
```

添加以下内容：

```ini
[Unit]
Description=Discord Marketing System
After=network.target

[Service]
Type=simple
User=administrator
WorkingDirectory=/home/administrator/discordImg
Environment=NODE_ENV=development
Environment=NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:5001
ExecStart=/home/administrator/discordImg/start.sh
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

```bash
# 启用服务
sudo systemctl enable discord-marketing
sudo systemctl start discord-marketing

# 查看状态
sudo systemctl status discord-marketing

# 查看日志
sudo journalctl -u discord-marketing -f
```

## 📞 技术支持

遇到问题？
- 查看日志: `tail -f ~/discordImg/frontend.log`
- 检查进程: `ps aux | grep -E "(next|python)"`
- 测试 API: `curl http://69.30.204.184:3000/api/auth/me`
