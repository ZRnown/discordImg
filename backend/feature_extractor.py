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

logger = logging.getLogger(__name__)

class DINOv2FeatureExtractor:
    """
    "猎鹰"架构特征提取器
    DINOv2 (大脑) + YOLOv8-Nano (眼睛)
    专为图像识别优化，自动裁剪主体后提取高精度特征
    """

    def __init__(self):
        self.device = torch.device(config.DEVICE)
        logger.info(f"正在初始化猎鹰AI引擎，使用设备: {self.device}")

        # 加载YOLOv8-Nano (眼睛 - 主体检测)
        self._load_yolo_detector()

        # 加载DINOv2 (大脑 - 特征提取)
        self._load_dino_model()

    def _load_yolo_detector(self):
        """加载YOLOv8-Nano用于主体检测和裁剪"""
        try:
            logger.info("加载YOLOv8-Nano主体检测模型...")
            # 首次运行会自动下载yolov8n.pt到当前目录
            self.detector = YOLO(config.YOLO_MODEL_PATH)
            logger.info("✅ YOLOv8-Nano模型加载成功")
        except Exception as e:
            logger.error(f"❌ YOLOv8-Nano模型加载失败: {e}")
            raise RuntimeError("YOLO模型加载失败") from e

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
        """使用YOLO裁剪出图片中最大的物体"""
        try:
            if not config.USE_YOLO_CROP:
                return Image.open(image_path).convert("RGB")

            # 运行YOLO推理
            results = self.detector(image_path, conf=0.25, verbose=False)

            if not results or len(results[0].boxes) == 0:
                logger.debug("未检测到物体，使用原图")
                return Image.open(image_path).convert("RGB")

            boxes = results[0].boxes
            img = Image.open(image_path).convert("RGB")
            w, h = img.size

            # 找面积最大的框
            max_area = 0
            best_box = None
            for box in boxes:
                coords = box.xyxy[0].cpu().numpy()  # x1, y1, x2, y2
                area = (coords[2] - coords[0]) * (coords[3] - coords[1])
                if area > max_area:
                    max_area = area
                    best_box = coords

            if best_box is None:
                return img

            # 裁剪并留一点边距
            x1, y1, x2, y2 = best_box

            # 扩充5%的边缘，防止切掉边缘特征
            pad_x = (x2 - x1) * 0.05
            pad_y = (y2 - y1) * 0.05

            crop_box = (
                max(0, x1 - pad_x),
                max(0, y1 - pad_y),
                min(w, x2 + pad_x),
                min(h, y2 + pad_y)
            )

            cropped = img.crop(crop_box)
            logger.debug(f"YOLO裁剪成功: {crop_box}")
            return cropped

        except Exception as e:
            logger.warning(f"YOLO裁剪失败，使用原图: {e}")
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
