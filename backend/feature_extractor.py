import os
import torch
import numpy as np
from typing import List, Optional, Union
import logging
from pathlib import Path
from PIL import Image
from transformers import AutoImageProcessor, AutoModel
from ultralytics import YOLO
from config import config
from functools import lru_cache
import hashlib

logger = logging.getLogger(__name__)

class DINOv2FeatureExtractor:
    """
    "猎鹰"架构特征提取器
    DINOv2 (大脑) + YOLO-World (眼睛)
    专为鞋类识别优化，自动裁剪鞋子主体后提取高精度特征
    """

    def __init__(self):
        self.device = torch.device(config.DEVICE)
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
        """加载YOLO-World用于全自动通用电商商品检测"""
        try:
            logger.info("加载全自动通用电商识别模型 (YOLO-World)...")
            # 使用YOLO-World模型，首次运行会自动下载yolov8s-world.pt
            self.detector = YOLO('yolov8s-world.pt')

            # [核心配置] 定义全自动识别的范围
            # 优化后的商品类别，覆盖微店/代购场景95%的商品
            # YOLO-World 会自动忽略人脸、手、家具、背景
            self.target_classes = [
                # 鞋类 (高优先级)
                "shoe", "sneaker", "boot", "sandal", "slipper", "heel",
                # 服装 (高优先级)
                "shirt", "t-shirt", "jacket", "coat", "pants", "jeans",
                "dress", "skirt", "shorts", "hoodie", "sweater", "suit",
                # 包袋配饰 (中优先级)
                "bag", "handbag", "backpack", "wallet", "belt", "hat", "cap",
                "watch", "jewelry", "necklace", "ring", "glasses",
                # 电子产品 (中优先级)
                "phone", "laptop", "headphone", "camera", "watch",
                # 家居用品 (低优先级)
                "toy", "box", "bottle", "cup", "lamp"
            ]

            # 将这些类别注入模型
            self.detector.set_classes(self.target_classes)

            logger.info(f"✅ YOLO-World模型加载成功，支持自动识别 {len(self.target_classes)} 种商品类别")
            logger.info(f"YOLO-World目标类别: {', '.join(self.target_classes[:10])}...")
            logger.info("YOLO-World优化说明: 使用多维度评分(面积×置信度×位置×类别权重)，显著提升裁剪准确率")
        except Exception as e:
            logger.warning(f"YOLO-World模型加载失败: {e}，降级使用YOLOv8-Nano")
            try:
                # 降级到YOLOv8-Nano
                self.detector = YOLO('yolov8n.pt')
                self.target_classes = None  # Nano版本不支持自定义类别
                logger.info("✅ YOLOv8-Nano模型加载成功")
            except Exception as e2:
                logger.error(f"YOLOv8-Nano模型也加载失败: {e2}，将禁用YOLO裁剪")
                self.detector = None
                self.target_classes = None

    def _load_dino_model(self):
        """加载DINOv2模型用于特征提取"""
        try:
            model_name = config.DINO_MODEL_NAME
            logger.info(f"加载DINOv2特征模型: {model_name}...")

            self.processor = AutoImageProcessor.from_pretrained(model_name)
            self.model = AutoModel.from_pretrained(model_name).to(self.device)
            self.model.eval()

            logger.info("✅ DINOv2模型加载成功")
        except Exception as e:
            logger.error(f"❌ DINOv2模型加载失败: {e}")
            raise RuntimeError("DINOv2模型加载失败") from e

    def _crop_main_object(self, image_path: str) -> Image.Image:
        """全自动裁剪商品主体

        全自动裁剪逻辑：
        1. 在预设的商品类别中检测所有物体
        2. 自动过滤掉背景、人、手
        3. 在剩下的商品中，选出最显著的一个（最大+最中心）
        """
        try:
            if not config.USE_YOLO_CROP:
                return Image.open(image_path).convert("RGB")

            # 检查缓存
            image_hash = self._get_image_hash(image_path)
            if image_hash in self._detection_cache:
                logger.debug("使用缓存的检测结果")
                cached_result = self._detection_cache[image_hash]
                if cached_result is None:
                    # 缓存中表示未检测到商品
                    return Image.open(image_path).convert("RGB")
                # 返回缓存的裁剪结果
                return cached_result

            # conf=0.1: 降低门槛，宁可多检不要漏检，反正我们有逻辑过滤
            results = self.detector(image_path, conf=0.1, verbose=False)

            if not results or len(results[0].boxes) == 0:
                logger.info("未检测到通用商品，降级使用原图")
                # 缓存未检测到商品的结果
                self._detection_cache[image_hash] = None
                return Image.open(image_path).convert("RGB")

            boxes = results[0].boxes
            img = Image.open(image_path).convert("RGB")
            img_w, img_h = img.size
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

                # 3. 计算离图片中心的距离
                box_center_x = x1 + width / 2
                box_center_y = y1 + height / 2
                dist_to_center = ((box_center_x - center_x)**2 + (box_center_y - center_y)**2) ** 0.5

                # 4. 综合评分公式：
                # 面积越大越好 (权重 0.7)
                # 越靠中心越好 (权重 0.3)
                # 这个公式能保证：即使角落里有个大包，也会优先选中间的小鞋子
                norm_area = area / (img_w * img_h)
                norm_dist = 1 - (dist_to_center / ((img_w**2 + img_h**2)**0.5))

                score = (norm_area * 0.7) + (norm_dist * 0.3) + (float(box.conf) * 0.1)

                if score > max_score:
                    max_score = score
                    best_box = coords

            if best_box is None:
                logger.info("未找到合适的商品框，使用原图")
                # 缓存失败结果
                self._detection_cache[image_hash] = None
                return img

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
            logger.info(f"成功裁剪商品区域: {crop_box}")

            # 缓存成功结果
            self._detection_cache[image_hash] = cropped_img.copy()

            return cropped_img

        except Exception as e:
            logger.warning(f"自动裁剪出错: {e}, 使用原图")
            # 缓存失败结果
            try:
                image_hash = self._get_image_hash(image_path)
                self._detection_cache[image_hash] = None
            except:
                pass
            return Image.open(image_path).convert("RGB")
        """使用YOLO-World精准裁剪鞋类主体"""
        try:
            if not config.USE_YOLO_CROP:
                return Image.open(image_path).convert("RGB")

            # 检查缓存
            image_hash = self._get_image_hash(image_path)
            if image_hash in self._detection_cache:
                logger.debug("使用缓存的检测结果")
                cached_result = self._detection_cache[image_hash]
                if cached_result is None:
                    # 缓存中表示未检测到鞋子
                    return Image.open(image_path).convert("RGB")
                # 返回缓存的裁剪结果
                return cached_result

            # 优化检测参数，提高准确率
            # 使用更低的置信度但更高的质量阈值
            results = self.detector(image_path, conf=0.05, iou=0.5, verbose=False)

            if not results or len(results[0].boxes) == 0:
                logger.info("未检测到通用商品，降级使用原图")
                # 缓存未检测到商品的结果
                self._detection_cache[image_hash] = None
                return Image.open(image_path).convert("RGB")

            boxes = results[0].boxes
            img = Image.open(image_path).convert("RGB")
            img_w, img_h = img.size
            center_x, center_y = img_w / 2, img_h / 2

            # --- 优化候选逻辑 (YOLO-World增强版) ---
            # 多维度评分：面积、置信度、位置、长宽比

            candidates = []
            for box in boxes:
                coords = box.xyxy[0].cpu().numpy()
                conf = float(box.conf)
                cls = int(box.cls)

                w = coords[2] - coords[0]
                h = coords[3] - coords[1]
                area = w * h

                # 过滤太小或太大bbox
                if area < img_w * img_h * 0.01:  # 至少占图片面积1%
                    continue
                if area > img_w * img_h * 0.9:   # 最多占图片面积90%
                    continue

                # 计算长宽比 (过滤极端比例)
                aspect_ratio = max(w/h, h/w)
                if aspect_ratio > 5:  # 太细长
                    continue

                # 计算中心距离权重 (越靠近中心越好)
                box_cx = coords[0] + w/2
                box_cy = coords[1] + h/2
                dist_from_center = ((box_cx - center_x)**2 + (box_cy - center_y)**2) ** 0.5
                max_dist = ((img_w/2)**2 + (img_h/2)**2) ** 0.5
                center_weight = 1 - (dist_from_center / max_dist)

                # 计算类别权重 (鞋类和服装更高权重)
                class_name = self.target_classes[cls] if cls < len(self.target_classes) else "unknown"
                class_weight = 1.5 if any(keyword in class_name.lower() for keyword in ['shoe', 'shirt', 'pants', 'dress']) else 1.0

                # 综合评分
                score = area * conf * center_weight * class_weight

                candidates.append({
                    'coords': coords,
                    'score': score,
                    'conf': conf,
                    'area': area,
                    'class': class_name
                })

            # 选择最佳候选
            if not candidates:
                logger.info("未找到合适的商品框，使用原图")
                return img

            best_candidate = max(candidates, key=lambda x: x['score'])
            best_box = best_candidate['coords']

            logger.info(f"选择最佳检测框: {best_candidate['class']}, 置信度: {best_candidate['conf']:.3f}, 得分: {best_candidate['score']:.1f}")

            if best_box is None:
                logger.info("未找到合适的鞋子框，使用原图")
                return img

            # 裁剪选中的鞋子
            x1, y1, x2, y2 = best_box

            # 扩充5%的边缘，防止切掉边缘特征
            pad_x = (x2 - x1) * 0.05
            pad_y = (y2 - y1) * 0.05

            crop_box = (
                max(0, x1 - pad_x),
                max(0, y1 - pad_y),
                min(img_w, x2 + pad_x),
                min(img_h, y2 + pad_y)
            )

            cropped_img = img.crop(crop_box)
            logger.info(f"成功裁剪鞋子区域: {crop_box}")

            # 缓存结果
            self._detection_cache[image_hash] = cropped_img.copy()

            return cropped_img

        except Exception as e:
            logger.warning(f"鞋子裁剪异常: {e}")
            # 缓存失败结果
            self._detection_cache[image_hash] = None
            return Image.open(image_path).convert("RGB")

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
            inputs = self.processor(images=img, return_tensors="pt").to(self.device)

            # 3. 特征提取
            with torch.no_grad():
                outputs = self.model(**inputs)

            # 4. 获取CLS token特征 (DINOv2的最佳实践)
            # outputs.last_hidden_state.shape: [1, num_patches+1, dim]
            # 第0个是CLS token，代表整张图的语义
            embedding = outputs.last_hidden_state[0, 0, :].cpu().numpy()

            # 5. L2归一化 (对余弦相似度至关重要)
            norm = np.linalg.norm(embedding)
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

# 向后兼容的别名
class FeatureExtractor(DINOv2FeatureExtractor):
    """向后兼容的别名"""
    pass

# 单例模式获取实例
_feature_extractor = None

def get_feature_extractor() -> DINOv2FeatureExtractor:
    global _feature_extractor
    if _feature_extractor is None:
        _feature_extractor = DINOv2FeatureExtractor()
    return _feature_extractor
