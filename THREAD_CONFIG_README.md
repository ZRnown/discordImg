# 线程配置说明

## 概述
系统现在使用环境变量来配置图片下载和特征提取的并发线程数，不再通过UI界面配置。

## 配置方法

1. 创建 `.env` 文件在项目根目录
2. 添加以下环境变量：

```bash
# 线程配置 - 图片下载和特征提取的并发线程数
DOWNLOAD_THREADS=4
FEATURE_EXTRACT_THREADS=4
```

## 默认值
- `DOWNLOAD_THREADS`: 4（图片下载线程数）
- `FEATURE_EXTRACT_THREADS`: 4（特征提取线程数）

## 配置范围
- 线程数建议设置为 1-8 之间
- 根据服务器CPU核心数和内存情况调整
- 过高的线程数可能导致系统负载过高

## 生效方式
修改 `.env` 文件后需要重启后端服务：

```bash
# 停止后端
pkill -f "python app.py"

# 重新启动
cd backend && python app.py
```

## 其他环境变量
系统中还支持以下环境变量配置：

```bash
# Discord配置
DISCORD_CHANNEL_ID=
DISCORD_SIMILARITY_THRESHOLD=0.6

# 全局回复延迟配置（秒）
GLOBAL_REPLY_MIN_DELAY=3.0
GLOBAL_REPLY_MAX_DELAY=8.0

# 服务配置
PORT=5001
DEBUG=True
DEVICE=cpu
```
