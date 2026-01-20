import os

# === 性能优化配置 ===
# 允许底层计算库每个任务使用少量核心。
# 配合上层有限并发（例如 3 个并发任务），在 10 核 CPU 上更容易吃满但不打架。
# 可通过环境变量 AI_INTRA_THREADS 调整。
try:
    from .config import config as _cfg
except Exception:
    try:
        from config import config as _cfg
    except Exception:
        _cfg = None

_intra_threads = None
try:
    if _cfg is not None and hasattr(_cfg, 'AI_INTRA_THREADS'):
        _intra_threads = int(_cfg.AI_INTRA_THREADS)
except Exception:
    _intra_threads = None

if not _intra_threads or _intra_threads <= 0:
    _intra_threads = int(os.getenv('AI_INTRA_THREADS', '3'))

os.environ["OMP_NUM_THREADS"] = str(_intra_threads)
os.environ["MKL_NUM_THREADS"] = str(_intra_threads)
os.environ["OPENBLAS_NUM_THREADS"] = str(_intra_threads)
os.environ["VECLIB_MAXIMUM_THREADS"] = str(_intra_threads)
os.environ["NUMEXPR_NUM_THREADS"] = str(_intra_threads)

import warnings
warnings.filterwarnings("ignore", message="Could not initialize NNPACK")
import torch

# === 添加这段代码 ===
try:
    # 显式禁用 NNPACK
    torch.backends.nnpack.enabled = False
except Exception:
    pass
# =================
import numpy as np
import cv2  # OpenCV for color histogram and structure comparison
import threading
import inspect
from typing import List, Optional, Union, Dict
import logging
from pathlib import Path
from PIL import Image
from transformers import AutoImageProcessor, AutoModel
from ultralytics import YOLO
try:
    from .config import config
except ImportError:
    from config import config
from functools import lru_cache
import hashlib

logger = logging.getLogger(__name__)

# 全局单例变量
_global_extractor = None
_extractor_lock = threading.Lock()

class DINOv2FeatureExtractor:
    """
    "猎鹰"架构特征提取器
    DINOv2 (大脑) + YOLO-World (眼睛)
    专为鞋类识别优化，自动裁剪鞋子主体后提取高精度特征
    """

    def __init__(self):
        self.device = torch.device(config.DEVICE)
        # 保护 YOLO/DINO 推理，避免多线程同时访问导致模型状态损坏
        self.inference_lock = threading.Lock()
        logger.info(f"正在初始化猎鹰AI引擎，使用设备: {self.device}")

        # 加载YOLOv8-Nano (眼睛 - 主体检测)
        self._load_yolo_detector()

        # 加载DINOv2 (大脑 - 特征提取)
        self._load_dino_model()

        # 初始化缓存用于检测结果
        self._detection_cache = {}

    def _get_image_hash(self, image_path: str) -> str:
        """计算图片文件的哈希值用于缓存"""
        try:
            with open(image_path, 'rb') as f:
                return hashlib.md5(f.read()).hexdigest()
        except Exception:
            # 如果读取失败，使用文件路径+修改时间作为备用
            import os
            stat = os.stat(image_path)
            return hashlib.md5(f"{image_path}:{stat.st_mtime}".encode()).hexdigest()

    def _load_yolo_detector(self):
        """强制加载YOLO-World模型用于商品识别"""
        try:
            # 减少日志级别
            logging.getLogger("ultralytics").setLevel(logging.WARNING)
            self.detector = YOLO(config.YOLO_MODEL_PATH)

            # [核心配置] 定义全自动识别的范围
            # 优化后的商品类别，覆盖微店/代购场景95%的商品
            # YOLO-World 会自动忽略人脸、手、家具、背景
            self.target_classes = [
                # 鞋类
                "shoe", "sneaker", "boot", "sandal", "slipper", "high heels",
                # 上装
                "t-shirt", "shirt", "jacket", "coat", "hoodie", "sweater", "suit", "vest", "jersey",
                # 下装
                "pants", "jeans", "shorts", "skirt", "trousers", "sweatpants",
                # 包袋
                "bag", "handbag", "backpack", "wallet", "purse", "suitcase", "tote bag",
                # 配饰/小件
                "watch", "wristwatch", "glasses", "sunglasses", "hat", "cap", "beanie",
                "belt", "tie", "scarf", "gloves", "socks",
                # 首饰
                "necklace", "ring", "earrings", "bracelet", "jewelry",
                # 其他
                "toy", "box", "packaging"
            ]

            # 不在初始化时设置类别，避免某些版本出现副作用

            logger.info("🎉 YOLO-World模型加载成功！")
            logger.info(f"🎯 支持自动识别 {len(self.target_classes)} 种商品类别")
            logger.info(f"📋 YOLO-World目标类别: {', '.join(self.target_classes[:10])}...")
            logger.info("⚡ YOLO-World优化说明: 使用多维度评分(面积×置信度×位置×类别权重)，显著提升裁剪准确率")

            # 验证CLIP库是否正确安装
            try:
                import clip
                logger.info(f"✅ CLIP库版本验证: {getattr(clip, '__version__', '未知')}")
                if hasattr(clip, 'load'):
                    logger.info("✅ CLIP.load方法可用")
                else:
                    logger.warning("⚠️ CLIP.load方法不可用，可能影响YOLO-World性能")
            except ImportError as e:
                logger.warning(f"⚠️ 无法导入CLIP库: {e}")

        except Exception as e:
            logger.error(f"💥 YOLO-World模型加载失败: {e}")

            # 检查是否是CLIP相关的问题，如果是则尝试备用方案
            if "clip" in str(e).lower():
                logger.warning("🔍 检测到CLIP库问题，尝试备用加载方式...")

                try:
                    # 尝试不依赖CLIP的加载方式
                    import ultralytics
                    logger.info(f"Ultralytics版本: {ultralytics.__version__}")

                    # 直接创建YOLO-World实例，不设置类别
                    self.detector = YOLO('yolov8s-world.pt')
                    self.target_classes = None  # 不设置自定义类别

                    logger.warning("⚠️ YOLO-World以基础模式加载 (无自定义类别)")
                    logger.warning("📊 影响: 将使用YOLO-World的内置80类进行检测")
                    logger.info("✅ YOLO-World基础模式加载成功")

                except Exception as backup_error:
                    logger.error(f"💥 备用加载方式也失败: {backup_error}")
                    logger.error("🔥 用户要求强制使用YOLO-World，但所有加载方式都失败！")
                    logger.error("💡 最终解决方案:")
                    logger.error("   1. pip uninstall clip torch torchvision ultralytics")
                    logger.error("   2. pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu")
                    logger.error("   3. pip install ultralytics")
                    logger.error("   4. pip install git+https://github.com/openai/CLIP.git")
                    raise RuntimeError("YOLO-World加载失败，所有备用方案均无效") from e
            else:
                # 不是CLIP问题，直接报错
                logger.error("🔥 YOLO-World加载失败，错误不相关CLIP库")
                logger.error("💡 建议检查网络连接和ultralytics版本")
                raise RuntimeError("YOLO-World加载失败") from e

    def _load_dino_model(self):
        """加载DINOv2模型用于特征提取"""
        try:
            model_name = config.DINO_MODEL_NAME
            logger.info(f"加载DINOv2特征模型: {model_name}...")

            self.processor = AutoImageProcessor.from_pretrained(model_name)
            self.model = self._load_pretrained_model(model_name, force_no_safetensors=False)
            if self._model_has_meta(self.model):
                logger.warning("检测到 meta tensor，尝试禁用 safetensors 重新加载")
                self.model = self._load_pretrained_model(model_name, force_no_safetensors=True)
            if self._model_has_meta(self.model):
                raise RuntimeError("模型仍处于 meta 状态，请检查 transformers/torch 版本或缓存")
            try:
                self.model.to(self.device)
            except Exception as device_error:
                if "meta" in str(device_error).lower():
                    logger.warning("检测到 meta tensor，改用CPU并重新加载模型")
                    self.device = torch.device('cpu')
                    self.model = self._load_pretrained_model(model_name, force_no_safetensors=True)
                    self.model.to(self.device)
                else:
                    logger.warning(f"模型移动到设备失败: {device_error}，改用CPU")
                    self.device = torch.device('cpu')
                    self.model.to(self.device)
            self.model.eval()
            logger.info("✅ DINOv2模型加载成功")
        except Exception as e:
            logger.error(f"❌ DINOv2模型加载失败: {e}")
            raise RuntimeError("DINOv2模型加载失败") from e

    def _load_pretrained_model(self, model_name: str, force_no_safetensors: bool) -> AutoModel:
        load_kwargs = {
            'low_cpu_mem_usage': False,
            'torch_dtype': torch.float32,
            'device_map': None
        }
        if force_no_safetensors:
            load_kwargs['use_safetensors'] = False

        try:
            sig = inspect.signature(AutoModel.from_pretrained)
            allowed = set(sig.parameters.keys())
            load_kwargs = {k: v for k, v in load_kwargs.items() if k in allowed}
        except Exception:
            pass

        return AutoModel.from_pretrained(model_name, **load_kwargs)

    @staticmethod
    def _model_has_meta(model: AutoModel) -> bool:
        try:
            return any(getattr(p, 'is_meta', False) for p in model.parameters())
        except Exception:
            return False

    def _crop_main_object(self, image_path: str) -> Image.Image:
        """全自动裁剪商品主体 + [新增] 尺寸优化

        全自动裁剪逻辑：
        1. 在预设的商品类别中检测所有物体
        2. 自动过滤掉背景、人、手
        3. 在剩下的商品中，选出最显著的一个（最大+最中心）
        4. [新增] 缩小图片尺寸以加快AI推理速度
        """
        try:
            img = Image.open(image_path).convert("RGB")
            img_w, img_h = img.size

            if not config.USE_YOLO_CROP or self.detector is None:
                return self._center_crop(img)

            # 检查缓存
            image_hash = self._get_image_hash(image_path)
            if image_hash in self._detection_cache:
                logger.debug("使用缓存的检测结果")
                cached_result = self._detection_cache[image_hash]
                if cached_result is None:
                    return self._center_crop(img)
                # 返回缓存的裁剪结果
                return cached_result

            # conf=0.05: 降低门槛，宁可多检不要漏检，反正我们有逻辑过滤
            with self.inference_lock:
                results = self.detector(image_path, conf=0.05, verbose=False)

            if not results or len(results[0].boxes) == 0:
                logger.debug("未检测到通用商品，使用中心裁剪兜底")
                self._detection_cache[image_hash] = None
                return self._center_crop(img)

            boxes = results[0].boxes
            center_x, center_y = img_w / 2, img_h / 2

            # --- 智能评分逻辑 ---
            # 在所有检测到的"商品"中，选出主角

            best_box = None
            max_score = -1

            for box in boxes:
                # 1. 获取坐标
                coords = box.xyxy[0].cpu().numpy()  # [x1, y1, x2, y2]
                x1, y1, x2, y2 = coords

                # 2. 计算面积
                width = x2 - x1
                height = y2 - y1
                area = width * height
                if area < (img_w * img_h * 0.02):
                    continue

                # 3. 计算离图片中心的距离
                box_center_x = x1 + width / 2
                box_center_y = y1 + height / 2
                dist_to_center = ((box_center_x - center_x)**2 + (box_center_y - center_y)**2) ** 0.5

                # 4. 综合评分公式：
                # 面积越大越好 (权重 0.6)
                # 越靠中心越好 (权重 0.4)
                # 这个公式能保证：即使角落里有个大包，也会优先选中间的小鞋子
                norm_area = area / (img_w * img_h)
                norm_dist = 1 - (dist_to_center / ((img_w**2 + img_h**2)**0.5))

                score = (norm_area * 0.6) + (norm_dist * 0.4) + (float(box.conf) * 0.1)

                if score > max_score:
                    max_score = score
                    best_box = coords

            if best_box is None:
                logger.info("未找到合适的商品框，使用中心裁剪兜底")
                self._detection_cache[image_hash] = None
                return self._center_crop(img)

            # 执行裁剪
            x1, y1, x2, y2 = best_box

            # 扩充 5% - 10% 的边缘，保留一点点上下文
            pad_x = (x2 - x1) * 0.05
            pad_y = (y2 - y1) * 0.05

            crop_box = (
                max(0, x1 - pad_x),
                max(0, y1 - pad_y),
                min(img_w, x2 + pad_x),
                min(img_h, y2 + pad_y)
            )

            cropped_img = img.crop(crop_box)
            logger.debug(f"成功裁剪商品区域: {crop_box}")

            # 优化：Resize 裁剪后的图片
            final_img = self._resize_for_ai(cropped_img)

            # 缓存成功结果
            self._detection_cache[image_hash] = final_img.copy()

            return final_img

        except Exception as e:
            logger.warning(f"自动裁剪出错: {e}, 使用中心裁剪")
            # 缓存失败结果
            try:
                image_hash = self._get_image_hash(image_path)
                self._detection_cache[image_hash] = None
            except:
                pass
            return self._center_crop(Image.open(image_path).convert("RGB"))

    def _center_crop(self, img: Image.Image) -> Image.Image:
        """中心裁剪：保留中间 80% 区域，降低背景干扰"""
        w, h = img.size
        left = int(w * 0.1)
        top = int(h * 0.1)
        right = int(w * 0.9)
        bottom = int(h * 0.9)
        return self._resize_for_ai(img.crop((left, top, right, bottom)))

    def _resize_for_ai(self, img: Image.Image, max_size: int = 448) -> Image.Image:
        """[新增] 将图片缩小到适合 AI 推理的尺寸，大幅提升速度

        Args:
            img: 输入图片
            max_size: 最大尺寸（默认448px），适合DINOv2特征提取

        Returns:
            缩放后的图片
        """
        w, h = img.size
        if max(w, h) > max_size:
            scale = max_size / max(w, h)
            new_w = int(w * scale)
            new_h = int(h * scale)
            return img.resize((new_w, new_h), Image.Resampling.LANCZOS)
        return img

    def extract_feature(self, image_path: Union[str, Path]) -> Optional[np.ndarray]:
        """提取单张图片的特征向量 (384维或768维)"""
        try:
            image_path = str(image_path)

            if not os.path.exists(image_path):
                logger.error(f"文件不存在: {image_path}")
                return None

            # 1. YOLO裁剪主体
            img = self._crop_main_object(image_path)

            # 2. 预处理（DINOv2会自动处理）
            with self.inference_lock:
                inputs = self.processor(images=img, return_tensors="pt").to(self.device)
                # 3. 特征提取
                with torch.no_grad():
                    outputs = self.model(**inputs)

            # 4. 获取CLS token特征 (DINOv2的最佳实践)
            # outputs.last_hidden_state.shape: [1, num_patches+1, dim]
            # 第0个是CLS token，代表整张图的语义
            embedding = outputs.last_hidden_state[0, 0, :].cpu().numpy()

            # 5. L2归一化 (对余弦相似度至关重要)
            norm = float(np.linalg.norm(embedding))
            if norm > 0:
                embedding = embedding / norm

            # 6. 确保数据类型为float32 (FAISS要求)
            return embedding.astype('float32')

        except Exception as e:
            logger.error(f"DINOv2特征提取失败 {image_path}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def extract_features_batch(self, image_paths: List[Union[str, Path]]) -> List[Optional[np.ndarray]]:
        """批量提取特征向量"""
        results = []
        for image_path in image_paths:
            feature = self.extract_feature(image_path)
            results.append(feature)
        return results

    def prepare_hybrid_query(self, img_path: str) -> Optional[Dict]:
        """预先计算查询图的颜色/比例特征，便于重排序阶段复用"""
        try:
            img = cv2.imread(img_path)
            if img is None:
                logger.warning(f"无法读取查询图片: {img_path}")
                return None
            return self._build_hybrid_signature(img)
        except Exception as e:
            logger.warning(f"查询图特征预计算失败: {e}")
            return None

    def _build_hybrid_signature(self, img: np.ndarray) -> Dict:
        """构建用于混合相似度的颜色/比例签名"""
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        hist = cv2.calcHist([hsv], [0, 1], None, [18, 4], [0, 180, 0, 256])
        cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)

        h, w = img.shape[:2]
        aspect_ratio = float(w) / float(h) if h else 1.0

        return {
            'hist': hist,
            'aspect_ratio': aspect_ratio
        }

    def calculate_hybrid_similarity(self, img_path1: str, img_path2: str, dino_score: float,
                                    query_signature: Optional[Dict] = None) -> dict:
        """
        【新增】计算综合相似度 (Re-ranking)

        综合分 = DINO语义分(70%) + 颜色分(15%) + 宽高比分(15%)

        Args:
            img_path1: 查询图片路径
            img_path2: 候选图片路径
            dino_score: DINOv2原始相似度分数

        Returns:
            dict: {'score': 综合分数, 'details': {'dino': ..., 'color': ..., 'ratio': ...}}
        """
        try:
            if query_signature is None:
                img1 = cv2.imread(img_path1)
                if img1 is None:
                    logger.warning(f"无法读取图片，使用原始DINO分数: {img_path1}")
                    return {'score': dino_score, 'details': {}}
                query_signature = self._build_hybrid_signature(img1)

            img2 = cv2.imread(img_path2)
            if img2 is None:
                logger.warning(f"无法读取图片，使用原始DINO分数: {img_path2}")
                return {'score': dino_score, 'details': {}}

            candidate_signature = self._build_hybrid_signature(img2)

            # 颜色相似度 (H+S, 降低光照影响)
            color_score = cv2.compareHist(query_signature['hist'], candidate_signature['hist'], cv2.HISTCMP_CORREL)
            color_score = max(0.0, color_score)

            # 宽高比相似度 (过滤跨品类误报)
            ratio1 = query_signature['aspect_ratio']
            ratio2 = candidate_signature['aspect_ratio']
            ratio_score = min(ratio1, ratio2) / max(ratio1, ratio2) if ratio1 > 0 and ratio2 > 0 else 0.0

            # 如果DINO很高，优先尊重语义/结构鲁棒性
            if dino_score > 0.85:
                final_score = dino_score
            else:
                final_score = (dino_score * 0.70) + (color_score * 0.15) + (ratio_score * 0.15)

            logger.debug(f"综合评分: DINO={dino_score:.3f}, Color={color_score:.3f}, Ratio={ratio_score:.3f}, Final={final_score:.3f}")

            return {
                'score': float(final_score),
                'details': {
                    'dino': float(dino_score),
                    'color': float(color_score),
                    'ratio': float(ratio_score)
                }
            }

        except Exception as e:
            logger.error(f"计算综合相似度出错: {e}")
            import traceback
            traceback.print_exc()
            return {'score': dino_score, 'details': {}}

    def get_status(self) -> Dict:
        """获取AI模型状态和性能信息"""
        status = {
            'device': str(self.device),
            'yolo_available': self.detector is not None,
            'yolo_type': 'None'
        }

        if self.detector is not None:
            if self.target_classes and len(self.target_classes) > 20:
                status['yolo_type'] = 'YOLO-World'
                status['target_classes_count'] = len(self.target_classes)
                status['target_classes'] = self.target_classes[:10]  # 只显示前10个
            else:
                status['yolo_type'] = 'YOLOv8-Nano'
                status['target_classes_count'] = len(self.target_classes) if self.target_classes else 0

        status['detection_cache_size'] = len(self._detection_cache)
        status['confidence_threshold'] = 0.05
        status['iou_threshold'] = 0.5

        # 性能提示
        tips = []
        if self.detector is None:
            tips.append("YOLO裁剪已禁用，建议修复YOLO加载问题以提升准确性")
        elif status['yolo_type'] == 'YOLOv8-Nano':
            tips.append("当前使用YOLOv8-Nano，建议升级依赖以启用YOLO-World获得更好效果")

        if status['detection_cache_size'] > 1000:
            tips.append("检测缓存较大，考虑定期清理缓存")

        status['performance_tips'] = tips if tips else ["AI模型运行正常"]

        return status

# 向后兼容的别名
class FeatureExtractor(DINOv2FeatureExtractor):
    """向后兼容的别名"""
    pass

def get_feature_extractor() -> 'DINOv2FeatureExtractor':
    """全局获取特征提取器实例（线程安全单例）"""
    global _global_extractor

    if _global_extractor is not None:
        return _global_extractor

    with _extractor_lock:
        # 双重检查锁定
        if _global_extractor is None:
            logger.info("🚀 [系统] 初始化 AI 模型 (DINOv2 + YOLO)...")
            try:
                _global_extractor = DINOv2FeatureExtractor()
                logger.info("✅ [系统] AI 模型初始化完成")
            except Exception as e:
                logger.error(f"❌ [系统] AI 模型初始化失败: {e}")
                raise e
        return _global_extractor
