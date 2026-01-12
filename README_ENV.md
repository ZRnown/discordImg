# 🔧 环境变量配置指南

## 📋 概述

Discord营销系统支持通过 `.env` 文件进行环境变量配置，这使得在不同服务器环境下的部署变得简单和安全。

## 🚀 快速开始（推荐）

### 自动配置脚本

对于 **HTTP IP访问** 的场景，使用自动配置脚本：

```bash
# 替换为你的实际服务器IP
./setup_env.sh 69.30.204.184

# 或者其他IP
./setup_env.sh 192.168.1.100
```

脚本会自动：
- ✅ 创建 `.env` 文件
- ✅ 生成安全的随机 `SECRET_KEY`
- ✅ 配置正确的 CORS 设置
- ✅ 设置 HTTP IP访问 所需的参数

## 📝 手动配置

如果需要手动配置，请按以下步骤操作：

### 1. 创建 .env 文件

```bash
# 在项目根目录创建 .env 文件
touch .env
```

### 2. 编辑 .env 文件

复制以下内容到 `.env` 文件，并根据你的实际情况修改：

```bash
# === 🚨 重要配置 ===
YOUR_SERVER_IP=69.30.204.184

# === 基础服务 ===
HOST=0.0.0.0
PORT=5001
DEBUG=false
DEVICE=cpu

# === 🔐 安全配置 ===
SECRET_KEY=your-production-secret-key-change-this-immediately
SESSION_LIFETIME=86400

# === 🌐 CORS配置（HTTP IP访问必需） ===
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://69.30.204.184:3000

# === 🎨 前端配置 ===
NODE_ENV=development
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:5001

# === 🤖 AI模型配置 ===
DINO_MODEL_NAME=facebook/dinov2-small
YOLO_MODEL_PATH=yolov8s-world.pt
USE_YOLO_CROP=true

# === ⚡ 性能配置 ===
SCRAPE_THREADS=10
DOWNLOAD_THREADS=10
FEATURE_EXTRACT_THREADS=4

# === 📡 网络配置 ===
REQUEST_TIMEOUT=30
MAX_RETRIES=3
```

### 3. 生成安全的 SECRET_KEY

```bash
# 使用Python生成随机密钥
python3 -c "import secrets; print(secrets.token_hex(32))"

# 或者使用openssl
openssl rand -hex 32
```

将生成的密钥设置到 `.env` 文件的 `SECRET_KEY` 字段。

## 🔍 配置说明

### HTTP IP访问的关键配置

| 变量 | 说明 | HTTP IP访问设置 |
|------|------|----------------|
| `NODE_ENV` | 前端环境 | `development` (必须，解决Cookie问题) |
| `YOUR_SERVER_IP` | 服务器IP | 你的实际服务器IP |
| `CORS_ORIGINS` | 允许的源 | 必须包含 `http://你的IP:3000` |
| `NEXT_PUBLIC_BACKEND_URL` | 后端API地址 | `http://127.0.0.1:5001` |

### 安全配置

| 变量 | 说明 | 重要性 |
|------|------|--------|
| `SECRET_KEY` | 会话加密密钥 | 🔴 必须修改，生产环境必需 |
| `SESSION_LIFETIME` | 会话过期时间 | 🟡 可选，默认24小时 |

### 性能配置

| 变量 | 说明 | 默认值 | 建议 |
|------|------|--------|------|
| `SCRAPE_THREADS` | 商品抓取线程数 | 10 | 根据CPU核心数调整 |
| `DOWNLOAD_THREADS` | 图片下载线程数 | 10 | 根据网络带宽调整 |
| `FEATURE_EXTRACT_THREADS` | 特征提取线程数 | 4 | CPU密集型，建议4-8 |

## 🧪 测试配置

### 1. 检查环境变量加载

```bash
# 运行后端，查看是否加载了.env文件
python backend/app.py
```

应该看到输出：
```
✅ 已加载环境变量文件: /path/to/your/project/.env
```

### 2. 运行诊断脚本

```bash
# 检查配置是否正确
python backend/diagnose_403.py
```

### 3. 启动服务

```bash
# 启动完整系统
./start.sh
```

## 🚨 常见问题

### Q: 为什么还是403 Forbidden？

A: 检查以下几点：
1. `NODE_ENV=development` 是否设置
2. `CORS_ORIGINS` 是否包含你的服务器IP
3. 浏览器是否清除了Cookie缓存
4. 防火墙是否开放了3000和5001端口

### Q: 前端和后端在不同服务器怎么办？

A: 修改 `NEXT_PUBLIC_BACKEND_URL`：
```bash
NEXT_PUBLIC_BACKEND_URL=http://后端服务器IP:5001
```

### Q: 如何更新配置？

A: 编辑 `.env` 文件后，重启服务：
```bash
./start.sh
```

### Q: 生产环境安全建议？

A:
- 使用强密码的 `SECRET_KEY`
- 设置 `DEBUG=false`
- 定期更新依赖包
- 监控日志文件
- 定期备份数据

## 📞 技术支持

如果配置仍有问题：

1. 运行 `python backend/diagnose_403.py` 获取诊断信息
2. 检查日志文件：`frontend.log` 和 `backend.log`
3. 确认防火墙和安全组设置

---

**🎯 记住**：对于HTTP IP访问，`NODE_ENV=development` 和正确的CORS配置是最重要的！
