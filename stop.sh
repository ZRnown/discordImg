#!/bin/bash

# Discord 营销系统 - 停止脚本

echo "=========================================="
echo "停止 Discord 营销系统..."
echo "=========================================="

# 进入项目目录
cd ~/discordImg || exit 1

# 优雅停止服务
echo "停止前端服务..."
pkill -f "next dev" 2>/dev/null
FRONTEND_STOPPED=$?

echo "停止后端服务..."
pkill -f "python app.py" 2>/dev/null
BACKEND_STOPPED=$?

# 等待进程完全停止
sleep 2

# 检查是否有残留进程
REMAINING=$(ps aux | grep -E "(next dev|python app.py)" | grep -v grep | wc -l)

if [ $REMAINING -gt 0 ]; then
    echo "发现残留进程，强制终止..."
    pkill -9 -f "next dev" 2>/dev/null
    pkill -9 -f "python app.py" 2>/dev/null
    sleep 1
fi

# 最终检查
FRONTEND_STATUS=$(ps aux | grep -E "next dev" | grep -v grep | wc -l)
BACKEND_STATUS=$(ps aux | grep -E "python app.py" | grep -v grep | wc -l)

echo ""
echo "=========================================="
if [ $FRONTEND_STATUS -eq 0 ] && [ $BACKEND_STATUS -eq 0 ]; then
    echo "✅ 所有服务已停止"
else
    echo "⚠️  部分服务可能仍在运行"
    if [ $FRONTEND_STATUS -gt 0 ]; then
        echo "   前端: 仍在运行"
    fi
    if [ $BACKEND_STATUS -gt 0 ]; then
        echo "   后端: 仍在运行"
    fi
    echo "   请手动检查: ps aux | grep -E '(next|python app.py)'"
fi
echo "=========================================="
echo ""
echo "重启服务: ~/discordImg/start.sh"
echo "查看日志: tail -f ~/discordImg/frontend.log (或 backend.log)"
echo "=========================================="
