#!/bin/bash

# Discord营销系统环境变量自动设置脚本
# 用法: ./setup_env.sh [服务器IP]

set -e

# 检查参数
if [ $# -eq 0 ]; then
    echo "❌ 错误: 请提供服务器IP地址"
    echo "用法: $0 <服务器IP>"
    echo "例如: $0 192.168.1.100"
    exit 1
fi

SERVER_IP=$1

# 验证IP地址格式
if ! [[ $SERVER_IP =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "❌ 错误: 无效的IP地址格式: $SERVER_IP"
    exit 1
fi

echo "🚀 设置Discord营销系统环境变量"
echo "📍 服务器IP: $SERVER_IP"
echo "========================================"

# 生成安全的随机密钥
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))" 2>/dev/null || openssl rand -hex 32 2>/dev/null || echo "dev-secret-key-change-in-production")

if [ "$SECRET_KEY" = "dev-secret-key-change-in-production" ]; then
    echo "⚠️  警告: 无法生成随机密钥，使用默认密钥（生产环境请手动修改）"
fi

# 创建.env文件
cat > .env << EOF
# Discord营销系统环境变量配置 - 自动生成
# 生成时间: $(date)
# 服务器IP: $SERVER_IP

# === 🚨 重要配置 ===
YOUR_SERVER_IP=$SERVER_IP

# === 基础服务配置 ===
HOST=0.0.0.0
PORT=5001
DEBUG=false
DEVICE=cpu

# === 🔐 安全配置 ===
SECRET_KEY=$SECRET_KEY
SESSION_LIFETIME=86400

# === 🌐 CORS配置（HTTP IP访问必需） ===
CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://$SERVER_IP:3000

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

# === 💬 Discord配置 ===
DISCORD_CHANNEL_ID=0
DISCORD_SIMILARITY_THRESHOLD=0.6
GLOBAL_REPLY_MIN_DELAY=3.0
GLOBAL_REPLY_MAX_DELAY=8.0

# === 📺 频道配置 ===
CNFANS_CHANNEL_ID=0
ACBUY_CHANNEL_ID=0
FORWARD_KEYWORDS=商品,货源,进货,批发,代理
FORWARD_TARGET_CHANNEL_ID=0

# === 🔍 FAISS配置 ===
FAISS_HNSW_M=64
FAISS_EF_CONSTRUCTION=80
FAISS_EF_SEARCH=64

# === 🎨 前端配置（HTTP IP访问设置） ===
NODE_ENV=development
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:5001
EOF

echo "✅ .env文件已创建"
echo ""
echo "📋 生成的环境变量配置:"
echo "   - 服务器IP: $SERVER_IP"
echo "   - 后端端口: 5001"
echo "   - 前端端口: 3000"
echo "   - SECRET_KEY: 已生成安全的随机密钥"
echo "   - CORS: 已包含服务器IP地址"
echo ""
echo "🔧 下一步操作:"
echo "1. 检查 .env 文件内容是否正确"
echo "2. 如需修改，请编辑 .env 文件"
echo "3. 运行系统: ./start.sh"
echo ""
echo "📝 如果前端和后端不在同一台服务器，请修改:"
echo "   NEXT_PUBLIC_BACKEND_URL=http://$SERVER_IP:5001"
echo ""
echo "⚠️  安全提醒:"
echo "   - 生产环境请定期更换 SECRET_KEY"
echo "   - 确保防火墙只开放必要端口 (3000, 5001)"
echo "   - 定期备份数据目录"
