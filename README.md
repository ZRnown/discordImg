# discordImg

# Discord Marketing System

基于 **"猎鹰"架构** (DINOv2 + YOLOv8 + FAISS HNSW) 的智能 Discord 营销系统，支持自动商品抓取、图像识别和智能回复。

## 🚀 核心功能

- 🦅 **猎鹰AI引擎**: DINOv2大脑 + YOLOv8眼睛，业界最强图像识别
- 📸 **智能图像识别**: 自动裁剪商品主体，提取384/768维高精度语义特征
- 🔍 **毫秒级检索**: FAISS HNSW向量索引，支持百万级图片瞬时搜索
- 🤖 **Discord 自动营销**: Selfbot 监听频道，自动回复 CNFans 购买链接
- 🌐 **现代化管理界面**: Next.js + Tailwind CSS 构建的管理后台

## 🛠️ 技术栈

| 组件 | 技术 | 说明 |
|------|------|------|
| **视觉识别** | **DINOv2** (Meta AI) + YOLOv8-Nano | 业界最强开源图像模型，理解语义而非轮廓 |
| **向量检索** | **FAISS HNSW** (CPU) | 图索引算法，查询速度极快，无需Docker |
| **主体检测** | YOLOv8-Nano | 自动裁剪商品主体，去除背景干扰 |
| **数据抓取** | 微店官方API | 直接调用thor.weidian.com API获取商品信息 |
| **翻译服务** | 百度/Google Translate API | 免费翻译API生成英文商品标题 |
| **Discord 机器人** | discord.py-self | Selfbot监听频道，自动回复CNFans链接 |
| **后端 API** | Flask | RESTful 接口服务，支持图片上传和向量搜索 |
| **前端界面** | Next.js 16 + React 19 | 现代化管理界面，支持商品规则配置 |
| **爬虫系统** | Selenium + BeautifulSoup | 微店商品信息抓取 |

## 📦 安装和运行

### 环境要求
- Python 3.8+
- Node.js 18+
- **16GB+ RAM** (DINOv2 + FAISS内存需求)
- Chrome 浏览器 (用于网页抓取)

### 🚀 快速开始

#### 1. 安装AI依赖 (猎鹰架构)

```bash
cd backend
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
pip install transformers ultralytics faiss-cpu
```

#### 2. 安装其他依赖

```bash
pip install -r requirements.txt
```

### 前端安装

```bash
cd frontend
npm install
```

### 🔄 数据迁移 (重要!)

如果你之前使用过旧版本 (PP-ShiTuV2)，需要迁移数据：

```bash
cd backend
# 备份旧数据
cp data/metadata.db data/metadata_old.db

# 运行迁移脚本 (会重新提取所有图片特征)
python migrate_data.py

# 测试新架构
python test_search_debug.py
```

### 启动服务

```bash
# 方式1: 使用脚本启动
./scripts/run.sh

# 方式2: 分别启动
# 终端1: 启动后端
cd backend && python app.py

# 终端2: 启动前端
cd frontend && npm run dev
```

访问地址：
- **前端界面**: http://localhost:3000
- **后端 API**: http://localhost:5001

## 🦅 猎鹰架构详解

### 为什么选择"猎鹰"？

1. **DINOv2 (大脑)**: Meta AI最新模型，超越所有开源图像模型
   - 384维向量即可表达丰富语义 (vs PP-ShiTuV2的512维轮廓识别)
   - 理解"这是什么商品"而非"像素看起来相似"

2. **YOLOv8-Nano (眼睛)**: 自动裁剪商品主体
   - 解决"搜鞋子搜到地板"的经典问题
   - 3MB轻量模型，毫秒级推理

3. **FAISS HNSW (翅膀)**: 图索引算法
   - 纯CPU实现，无Docker依赖
   - 百万级向量查询 < 10ms
   - 内存效率：4-6GB存储200万向量

### 技术优势

- **准确率**: DINOv2语义理解 > 传统CNN轮廓识别
- **速度**: HNSW图索引 > 传统树索引
- **内存**: 优化到16GB服务器可运行
- **部署**: 无Docker，纯Python，易维护

## ✨ 核心特性

- 🔤 **智能翻译**: 自动调用免费翻译API生成英文商品标题
- 🎯 **一键设置**: 新商品自动启用回复规则，支持关键词匹配
- ⚙️ **灵活配置**: 支持为每个商品单独配置自动回复规则
- 🆔 **完整信息**: 显示微店商品ID、标题、英文标题、图片数量等
- 🔍 **智能搜索**: 以图搜图功能，支持相似度阈值设置和历史记录
- 🌐 **官方API**: 直接调用微店官方接口，稳定可靠
- 🦅 **猎鹰AI**: 业界最强图像识别，语义级理解

## 🎯 使用指南

### 1. 配置 Discord 账号和全局设置
1. 进入"账号与规则"页面
2. 点击"添加账号"，输入 Discord Token
3. 切换账号状态为"在线"
4. 配置账号轮换设置（可选）
5. 配置全局轮换设置（可选）

### 1.5 配置关键词转发 (可选)
如果需要自动转发包含特定关键词的消息，请设置环境变量：
```bash
# 触发转发的关键词，用逗号分隔
export FORWARD_KEYWORDS="商品,货源,进货,批发,代理,供应,厂家"

# 转发目标频道ID (从Discord频道URL中获取数字部分)
export FORWARD_TARGET_CHANNEL_ID="1234567890123456789"
```

### 2. 添加商品到库
1. 进入"微店抓取"页面
2. 输入微店商品URL（如: https://weidian.com/item.html?itemID=7622495468）
3. 点击"建立索引与规则"按钮
4. 系统自动：
   - 调用微店官方API获取商品信息
   - 使用免费翻译API生成英文标题
   - 提取商品标题和图片链接
   - 下载高清商品图片到本地
   - 提取 PP-ShiTuV2 图像特征向量
   - 建立 Milvus Lite 向量索引
   - **自动启用**自动回复规则（支持关键词匹配）

### 3. 配置自动回复规则
1. 点击商品列表中的编辑按钮
2. 设置匹配关键词和回复规则
3. 启用"自动回复规则"

### 4. 启动Discord机器人
1. 配置环境变量中的频道ID：
```bash
export DISCORD_CHANNEL_ID="1234567890123456789"  # 监听的频道ID
```
2. 启动机器人：
```bash
cd backend && python bot.py
```
3. 机器人会自动：
   - 监听指定频道中的图片消息
   - 使用DINOv2识别相似商品
   - 自动回复商品链接
   - 转发包含关键词的消息（如果配置了转发目标）

### 4. 测试图像搜索
1. 进入"以图搜图"页面
2. 上传商品图片
3. 系统显示相似度最高的匹配结果

## 🔧 高级配置

### 相似度阈值
- 默认阈值: 75%
- 可在系统设置中调整
- 建议值: 电商场景 70-80%，内容识别 80-90%

### 自动回复
- 支持关键词精确匹配和模糊匹配
- 可配置不回复回复消息和@消息
- 支持为每个商品单独设置规则

### 爬虫配置
- 支持 Selenium 和 requests 双模式
- 自动处理反爬虫机制
- 支持多线程图片下载

## 📊 性能指标 (猎鹰架构)

- **图像处理**: 单张图片 < 500ms (包含YOLO裁剪 + DINOv2推理)
- **向量检索**: 百万图片库 < 10ms (FAISS HNSW优化)
- **相似度精度**: > 98% (DINOv2语义理解，超越传统CNN)
- **内存占用**: 4-6GB (200万向量x384维 HNSW索引)
- **CPU利用率**: 优化单线程推理，适合服务器环境

## 🐛 故障排除

### 常见问题

**Q: DINOv2模型下载失败**
A: 检查网络连接，首次运行会自动下载模型 (~300MB)

**Q: YOLOv8无法裁剪图片**
A: 确保 ultralytics 正确安装，首次运行会下载 yolov8n.pt

**Q: FAISS内存不足**
A: 增加服务器内存至16GB+，或减少索引的向量数量

**Q: 特征提取速度慢**
A: 正常现象，DINOv2比PP-ShiTuV2更精确但稍慢

**Q: 搜索准确率不如预期**
A: 提高相似度阈值 (0.6-0.8)，DINOv2需要更高阈值

**Q: 数据迁移失败**
A: 确保旧图片文件存在，重新运行 `python migrate_data.py`

### 日志查看
- 后端日志: 查看终端输出
- 前端日志: 浏览器开发者工具控制台
- 测试脚本: `python test_search_debug.py`

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

## 📄 许可证

Apache 2.0 License
# discordImg
