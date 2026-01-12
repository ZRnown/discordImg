#!/bin/bash

# Discord营销系统快速启动脚本
# 用法: ./quick_start.sh

set -e

echo "🚀 启动Discord营销系统"
echo "========================"

# 检查.env文件
if [ ! -f ".env" ]; then
    echo "❌ 错误: 未找到.env文件，请先运行 ./setup_env.sh 你的服务器IP"
    exit 1
fi

# 检查Python环境
if ! command -v python3 &> /dev/null; then
    echo "❌ 错误: 未找到python3"
    exit 1
fi

# 检查Node.js环境
if ! command -v npm &> /dev/null; then
    echo "❌ 错误: 未找到npm"
    exit 1
fi

echo "✅ 环境检查通过"

# 启动后端
echo "🔧 启动后端服务..."
cd backend
nohup python3 app.py > ../backend.log 2>&1 &
BACKEND_PID=$!
cd ..
echo "✅ 后端服务已启动 (PID: $BACKEND_PID)"

# 等待后端启动
sleep 3

# 启动前端
echo "🎨 启动前端服务..."
cd frontend
npm run build
nohup npm start > ../frontend.log 2>&1 &
FRONTEND_PID=$!
cd ..
echo "✅ 前端服务已启动 (PID: $FRONTEND_PID)"

echo ""
echo "🎉 系统启动完成！"
echo "=================="
echo "📍 前端地址: http://localhost:3000"
echo "📍 后端API: http://localhost:5001"
echo "📊 日志文件:"
echo "   - 后端日志: backend.log"
echo "   - 前端日志: frontend.log"
echo ""
echo "🛑 停止服务: kill $BACKEND_PID $FRONTEND_PID"
echo ""
echo "📝 首次使用请:"
echo "   1. 访问 http://localhost:3000"
echo "   2. 使用 admin/admin 登录"
echo "   3. 开始配置和使用系统"

# 保存PID到文件
echo "$BACKEND_PID $FRONTEND_PID" > .pids
