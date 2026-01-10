1. 核心目标与约束
核心目标: 在单机环境下（无 GPU 强制要求），对 100万 - 200万 量级图片实现超高准确率和毫秒级搜索响应。
硬件约束: 16GB - 32GB 内存服务器，CPU 运算。
部署约束: 禁止使用 Docker。所有组件必须作为纯 Python 库运行。
性能要求: 低内存占用（模型显存/内存 < 2GB），高并发查询能力。
2. 技术栈定义 (AI & 向量引擎)
2.1 特征提取层 (The Brain)
模型架构: DINOv2 (Meta AI 自监督视觉 Transformer)。
具体选型:
默认: facebook/dinov2-small (384维)。推荐，速度极快，内存占用极低，准确率远超传统 CNN。
高配: facebook/dinov2-base (768维)。仅在 32G 内存且对准确率有极端要求时使用。
运行库: transformers, torch (CPU版)。
输出要求: 必须进行 L2 归一化 (L2-Normalized)，以便计算余弦相似度。
2.2 预处理与去噪层 (The Eye) - 可选
功能: 主体检测与裁剪 (Object Detection & Cropping)。去除背景干扰，只保留商品主体。
模型: YOLOv8-Nano (yolov8n.pt)。
运行库: ultralytics.
配置策略:
必须在 config.py 中提供开关 (如 USE_YOLO_CROP)。
逻辑: 若开启，检测图中最大物体并裁剪；若未检测到或关闭，使用原图。
2.3 向量检索引擎 (The Index)
引擎: FAISS (Facebook AI Similarity Search) CPU 版本。
索引类型: HNSW (IndexHNSWFlat)。
原因: 纯内存图索引，查询速度最快，召回率最高，适合百万级数据。
参数参考: M=32 (邻居数), efConstruction=80, efSearch=64。
度量方式: IP (Inner Product)。注：归一化后的向量内积等同于余弦相似度。
持久化: 必须支持 write_index 和 read_index 到本地磁盘文件。
3. 识别与处理流程 (Pipeline)
任何图片处理（入库或搜索）必须严格遵循以下流水线：
输入: 图片路径或二进制流。
环境检查: 读取 config.USE_YOLO_CROP。
主体裁剪 (如开启):
调用 YOLOv8n 推理。
过滤低置信度结果 (conf < 0.25)。
选取面积最大的检测框 (Bounding Box)。
向外扩充 5% 边缘 (Padding) 并裁剪。
异常处理: 若无检测结果，降级使用原图，不报错。
特征推理:
输入 DINOv2 模型。
提取 last_hidden_state 的第一个 Token (CLS Token)。
向量标准化 (Critical):
对输出向量执行 L2 Normalization。
vector = vector / np.linalg.norm(vector)。
输出: 384维 (或768维) Float32 数组。
4. 开发与优化准则
单例模式 (Singleton): AI 模型（YOLO 和 DINOv2）和 FAISS 索引必须作为全局单例加载，严禁在每次请求中重新加载模型。
错误处理 (Soft Fail):
图片损坏、格式不支持或模型推理错误时，应记录 ERROR 日志并返回 None，严禁导致整个服务崩溃。
YOLO 裁剪失败应自动回退到全图识别模式。
内存管理:
对于百万级数据，FAISS 索引文件可能达到数 GB。启动时需预留足够内存加载索引。
批量导入数据时，应分批写入 FAISS 并定期保存到磁盘，防止内存溢出或数据丢失。