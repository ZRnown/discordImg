#!/bin/bash

# 清理不必要的文件和目录
# 用法: ./cleanup.sh

echo "🧹 清理不必要的文件..."

# 删除开发文档
rm -f AI_RULES.md all_code.txt README_ENV.md DEPLOYMENT.md DEPLOYMENT_FINAL.md

# 删除临时脚本
rm -f setup_env.sh stop.sh

# 删除前端缓存和日志
rm -f frontend/cookies.txt frontend/tsconfig.tsbuildinfo
rm -rf frontend/.next 2>/dev/null || true

# 删除后端缓存
find backend -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find backend -name "*.pyc" -delete 2>/dev/null || true

echo "✅ 清理完成"
echo "📁 保留的核心文件:"
echo "   ├── .env (环境配置)"
echo "   ├── start.sh (启动脚本)"
echo "   ├── quick_start.sh (快速启动)"
echo "   ├── cleanup.sh (清理脚本)"
echo "   ├── backend/ (后端代码)"
echo "   └── frontend/ (前端代码)"
