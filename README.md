# 🎯 Discord营销系统 - 快速开始指南

## 🚀 3步快速启动

### 1. 配置环境变量
```bash
# 自动配置（替换为你的服务器IP）
./setup_env.sh 69.30.204.184

# 或手动创建 .env 文件
cp env-example.txt .env
# 编辑 .env 文件，设置你的服务器IP
```

### 2. 启动系统
```bash
# 快速启动（推荐）
./quick_start.sh

# 或使用原始启动脚本
./start.sh
```

### 3. 访问系统
- **前端**: http://localhost:3000
- **后端API**: http://localhost:5001
- **默认账号**: admin / admin

## 🔧 系统配置

### 环境变量说明
```bash
# 服务器配置
HOST=0.0.0.0          # 监听地址
PORT=5001             # 服务端口
DEBUG=false           # 生产模式

# 安全配置
SECRET_KEY=xxx        # 会话密钥
SESSION_LIFETIME=86400 # 会话有效期(秒)

# CORS配置 (HTTP IP访问必需)
CORS_ORIGINS=*        # 允许所有来源

# 前端配置
NODE_ENV=development  # HTTP环境下必须
NEXT_PUBLIC_BACKEND_URL=http://127.0.0.1:5001
```

### 故障排除

#### 403 Forbidden 错误
```bash
# 运行诊断脚本
cd backend && python3 diagnose_403.py

# 检查配置
cat .env | grep -E "(CORS|NODE_ENV|SECRET_KEY)"
```

#### 商品不显示
```bash
# 检查数据库
cd backend && python3 -c "
from database import db
with db.get_connection() as conn:
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM products')
    print(f'商品数量: {cursor.fetchone()[0]}')
"
```

#### 服务无法启动
```bash
# 检查端口占用
lsof -i :5001
lsof -i :3000

# 杀死进程
kill -9 PID
```

## 📊 系统特性

- ✅ **智能图片去重** - 99%相似度检测
- ✅ **多线程处理** - 高速批量抓取
- ✅ **权限管理** - Admin/User角色区分
- ✅ **HTTP IP访问** - 无需HTTPS配置
- ✅ **实时监控** - 日志流和状态追踪

## 🛠️ 维护命令

```bash
# 清理临时文件
./cleanup.sh

# 重新构建前端
cd frontend && npm run build

# 重启服务
./start.sh restart

# 查看日志
tail -f backend.log
tail -f frontend.log
```

## 📞 技术支持

遇到问题时请提供：
1. 错误日志 (`backend.log`, `frontend.log`)
2. 诊断结果 (`python3 backend/diagnose_403.py`)
3. 环境信息 (`cat .env`)

---

**🎉 祝你使用愉快！系统已优化为生产就绪状态。**
