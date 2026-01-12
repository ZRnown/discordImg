#!/bin/bash

# Discord 营销系统 - 启动脚本
# 无需修改代码，通过环境变量解决所有问题

echo "=========================================="
echo "Discord 营销系统启动中..."
echo "=========================================="

# 进入项目目录
cd ~/discordImg || exit 1

# 停止现有服务
echo "停止现有服务..."
pkill -f "next dev" 2>/dev/null
pkill -f "python app.py" 2>/dev/null

# 等待进程完全停止
sleep 3

# 检查是否还有残留进程
REMAINING=$(ps aux | grep -E "(next dev|python app.py)" | grep -v grep | wc -l)
if [ $REMAINING -gt 0 ]; then
    echo "强制终止残留进程..."
    pkill -9 -f "next dev" 2>/dev/null
    pkill -9 -f "python app.py" 2>/dev/null
    sleep 1
fi

# 启动后端
echo "启动后端服务 (端口 5001)..."
cd backend
nohup python app.py > ../backend.log 2>&1 &
BACKEND_PID=$!
cd ..

# 等待后端启动
sleep 3

# 检查后端是否启动成功
if ! ps -p $BACKEND_PID > /dev/null 2>&1; then
    echo "❌ 后端启动失败！查看日志："
    tail -20 backend.log
    exit 1
fi

echo "✅ 后端服务已启动 (PID: $BACKEND_PID)"

# 启动前端（关键环境变量设置）
echo "启动前端服务 (端口 3000)..."
echo "   NODE_ENV=development (解决 Cookie 401/403 问题)"
echo "   NEXT_PUBLIC_BACKEND_URL=${NEXT_PUBLIC_BACKEND_URL:-http://127.0.0.1:5001} (使用环境变量或默认本地地址)"
cd frontend

NODE_ENV=development \
NEXT_PUBLIC_BACKEND_URL=${NEXT_PUBLIC_BACKEND_URL:-http://127.0.0.1:5001} \
nohup npm run dev > ../frontend.log 2>&1 &

FRONTEND_PID=$!
cd ..

# 等待前端启动
sleep 5

# 检查前端是否启动成功
if ! ps -p $FRONTEND_PID > /dev/null 2>&1; then
    echo "❌ 前端启动失败！查看日志："
    tail -20 frontend.log
    exit 1
fi

echo "✅ 前端服务已启动 (PID: $FRONTEND_PID)"

# 显示服务状态
echo ""
echo "=========================================="
echo "✅ 服务启动成功！"
echo "=========================================="
echo "📍 前端地址: http://${FRONTEND_HOST:-127.0.0.1}:3000"
echo "📍 后端地址: http://${BACKEND_HOST:-127.0.0.1}:5001"
echo ""
echo "📋 运行状态:"
echo "   前端: PID $FRONTEND_PID ✅"
echo "   后端: PID $BACKEND_PID ✅"
echo ""
echo "📊 查看日志:"
echo "   前端: tail -f ~/discordImg/frontend.log"
echo "   后端: tail -f ~/discordImg/backend.log"
echo ""
echo "🛑 停止服务:"
echo "   ~/discordImg/stop.sh"
echo ""
echo "🔄 重启服务:"
echo "   ~/discordImg/stop.sh && ~/discordImg/start.sh"
echo "=========================================="

# 自动打开浏览器（可选）
# echo "3秒后自动打开浏览器..."
# sleep 3
# xdg-open http://69.30.204.184:3000 2>/dev/null || open http://69.30.204.184:3000 2>/dev/null
