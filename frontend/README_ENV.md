# 前端环境变量配置说明

## 环境变量设置

在项目根目录创建 `.env.local` 文件（前端专用）：

```bash
# 前端环境变量
NEXT_PUBLIC_BACKEND_URL=http://localhost:5001
```

## 生产环境配置

如果部署到生产环境，需要根据实际情况设置：

### 本地开发环境
```bash
NEXT_PUBLIC_BACKEND_URL=http://localhost:5001
```

### Docker容器环境
```bash
NEXT_PUBLIC_BACKEND_URL=http://host.docker.internal:5001
```

### 生产服务器环境
```bash
NEXT_PUBLIC_BACKEND_URL=http://your-server-ip:5001
```

## 注意事项

1. **不要设置成前端地址**: `NEXT_PUBLIC_BACKEND_URL` 应该是后端Flask API的地址，不是前端Next.js的地址
2. **端口区别**:
   - 前端: `http://localhost:3000` (Next.js)
   - 后端: `http://localhost:5001` (Flask API)
3. **CORS设置**: 确保后端允许前端域名访问

## 常见错误

- **404错误**: 检查API路径是否正确，环境变量是否设置
- **CORS错误**: 检查后端CORS配置
- **连接超时**: 检查后端服务是否运行，端口是否正确
