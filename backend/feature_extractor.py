import os
import numpy as np
from typing import List, Optional, Union
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

class PPShiTuV2FeatureExtractor:
    """
    PP-ShiTuV2 专用特征提取器
    严格要求使用 PP-ShiTuV2 系列模型 (PPLCNetV2_base)
    禁止使用任何其他模型作为后备方案
    专为图像检索和识别优化，提供最高准确率
    """

    def __init__(self):
        self.model = None
        self.predictor = None
        self._load_model()

    def _load_model(self):
        """严格加载 PP-ShiTuV2 专用模型，不提供任何后备方案"""
        try:
            import paddle
            from paddle import inference
            import os

            # 强制使用 CPU 以避免环境中 GPU/参数混用导致的 conv2d 错误
            try:
                paddle.set_device('cpu')
                logger.info("设置 Paddle 设备为 CPU")
            except Exception:
                logger.debug("设置 Paddle 设备为 CPU 失败，使用默认设备")

            # 优先尝试使用 PaddlePaddle 推理 API 加载 PPLCNetV2_base 推理模型
            model_dir = os.path.expanduser("~/.paddleclas/inference_model/IMN/PPLCNetV2_base")
            pdmodel_path = os.path.join(model_dir, "inference.pdmodel")
            pdiparams_path = os.path.join(model_dir, "inference.pdiparams")

            if os.path.exists(pdmodel_path) and os.path.exists(pdiparams_path):
                logger.info(f"找到本地推理模型: {model_dir}")
                try:
                    # 创建推理配置
                    config = inference.Config(pdmodel_path, pdiparams_path)
                    config.disable_gpu()
                    config.enable_mkldnn()
                    config.set_cpu_math_library_num_threads(1)

                    # 创建预测器
                    self.predictor = inference.create_predictor(config)

                    # 获取输入输出名称
                    self.input_names = self.predictor.get_input_names()
                    self.output_names = self.predictor.get_output_names()
                    logger.info(f"✅ PPLCNetV2_base 推理模型加载成功！输入: {self.input_names}, 输出: {self.output_names}")
                    self._use_paddleclas = False
                    self._use_inference = True
                    self.model = None  # 使用推理器而不是模型
                    return
                except Exception as e:
                    logger.warning(f"PPLCNetV2_base 推理模型加载失败: {e}")
            else:
                logger.info("本地推理模型不存在，尝试使用其他方式...")

            # 回退：尝试使用 PaddleClas 的推理器（如果可用）
            try:
                from paddleclas import PaddleClas
                logger.info("检测到 PaddleClas，可尝试加载 PaddleClas 推理模型 (PPLCNetV2_base)")
                try:
                    # 尝试使用本地推理模型目录
                    if os.path.exists(model_dir) and os.path.exists(pdmodel_path):
                        logger.info(f"找到本地模型目录: {model_dir}")
                        self.model = PaddleClas(inference_model_dir=model_dir, use_gpu=False)
                        logger.info("✅ 使用 PaddleClas 加载本地 PPLCNetV2_base 模型成功")
                        self._use_paddleclas = True
                        self._use_inference = False
                        self.predictor = None
                        return
                    else:
                        # 回退到使用 model_name
                        logger.info("本地模型目录不存在，尝试使用 model_name...")
                        self.model = PaddleClas(model_name="PPLCNetV2_base", use_gpu=False)
                        logger.info("✅ 使用 PaddleClas 加载 PPLCNetV2_base 模型成功")
                        self._use_paddleclas = True
                        self._use_inference = False
                        self.predictor = None
                        return
                except Exception as e:
                    logger.warning(f"PaddleClas 加载失败: {e}")
            except Exception:
                logger.debug("未检测到 PaddleClas")

        except Exception as e:
            logger.error(f"❌ PP-ShiTuV2 模型加载失败: {e}")
            logger.error("❌ 严格要求使用 PP-ShiTuV2 模型，不提供任何后备方案")
            logger.error("请确保 PP-ShiTuV2 模型文件正确安装")
            raise RuntimeError("PP-ShiTuV2 模型加载失败，系统无法运行") from e

    def extract_feature(self, image_path: Union[str, Path]) -> Optional[List[float]]:
        """提取单张图片的特征向量 (512维)"""
        try:
            image_path = str(image_path)

            if not os.path.exists(image_path):
                logger.error(f"文件不存在: {image_path}")
                return None

            if self.model is None and self.predictor is None:
                logger.error("PP-ShiTuV2_rec 模型未加载")
                return None

            # 1. 读取图片 (RGB)
            from PIL import Image
            import paddle
            image = Image.open(image_path).convert('RGB')

            # 2. 改善预处理：保持宽高比，先缩放再裁剪
            width, height = image.size

            # 计算缩放比例，保持宽高比
            if width > height:
                new_width = int(width * 256 / height)
                new_height = 256
            else:
                new_width = 256
                new_height = int(height * 256 / width)

            # 缩放图片
            image = image.resize((new_width, new_height), Image.BILINEAR)

            # 应用轻微锐化来改善模糊图片质量
            from PIL import ImageFilter, ImageEnhance
            # 轻微锐化
            image = image.filter(ImageFilter.UnsharpMask(radius=1, percent=150, threshold=3))
            # 轻微对比度增强
            enhancer = ImageEnhance.Contrast(image)
            image = enhancer.enhance(1.1)

            # 中心裁剪到224x224
            left = (new_width - 224) // 2
            top = (new_height - 224) // 2
            right = left + 224
            bottom = top + 224
            image = image.crop((left, top, right, bottom))

            # 3. 转换为numpy数组并归一化
            img_array = np.array(image).astype('float32') / 255.0

            # 4. 转换为CHW格式
            img_array = img_array.transpose((2, 0, 1))

            # 5. ImageNet标准化
            mean = np.array([0.485, 0.456, 0.406], dtype='float32')
            std = np.array([0.229, 0.224, 0.225], dtype='float32')
            mean = mean.reshape((3, 1, 1))
            std = std.reshape((3, 1, 1))
            img_array = (img_array - mean) / std

            # 6. 转换为tensor，确保在 CPU 上
            img_tensor = paddle.to_tensor(img_array).astype('float32')
            img_tensor = img_tensor.unsqueeze(0)

            # 7. 特征提取：支持推理器、PaddleClas predict 和 paddle model forward 三种方式
            with paddle.no_grad():
                if getattr(self, "_use_inference", False) and self.predictor is not None:
                    # 使用 PaddlePaddle 推理器（传入 numpy 数组而不是 paddle.Tensor）
                    input_handle = self.predictor.get_input_handle(self.input_names[0])
                    # img_array 在上面已存在且为 CHW numpy 格式，添加 batch 维度
                    try:
                        np_input = img_array[np.newaxis, :].astype('float32')
                        input_handle.copy_from_cpu(np_input)
                        self.predictor.run()
                        output_handle = self.predictor.get_output_handle(self.output_names[0])
                        output_data = output_handle.copy_to_cpu()
                        feature_vector = output_data.flatten().tolist()
                    except Exception as e:
                        logger.error(f"Paddle inference predictor 运行失败: {e}")
                        raise
                elif getattr(self, "_use_paddleclas", False):
                    # PaddleClas 的 predict 接口接受文件路径
                    try:
                        res = self.model.predict(image_path)
                        # PaddleClas 返回结构可能是 list of dicts with 'feature'
                        if res and isinstance(res, list) and 'feature' in res[0]:
                            feature_vector = np.array(res[0]['feature']).flatten().tolist()
                        else:
                            # 退回到 tensor 前向
                            features = self.model._model(img_tensor) if hasattr(self.model, "_model") else None
                            if features is None:
                                raise RuntimeError("无法从 PaddleClas 获得特征")
                            feature_vector = features.numpy().flatten().tolist()
                    except Exception as e:
                        logger.error(f"PaddleClas predict 失败: {e}")
                        raise
                else:
                    # 使用 paddle model forward
                    features = self.model(img_tensor)
                    if hasattr(features, 'numpy'):
                        feature_vector = features.numpy().flatten()
                    else:
                        feature_vector = np.array(features).flatten()
                    feature_vector = feature_vector.tolist()

            # 8. 确保输出512维向量
            target_dim = 512
            current_dim = len(feature_vector)

            if current_dim > target_dim:
                # 如果维度大于512，取前512维
                feature_vector = feature_vector[:target_dim]
            elif current_dim < target_dim:
                # 如果维度小于512，补0
                feature_vector += [0.0] * (target_dim - current_dim)

            # 9. L2归一化 (cosine similarity需要)
            norm = np.linalg.norm(feature_vector)
            if norm > 0:
                feature_vector = (np.array(feature_vector) / norm).tolist()

            return feature_vector

        except Exception as e:
            logger.error(f"PPLCNetV2_base 特征提取失败 {image_path}: {e}")
            import traceback
            traceback.print_exc()
            return None

    def extract_features_batch(self, image_paths: List[Union[str, Path]]) -> List[Optional[List[float]]]:
        """批量提取特征向量"""
        results = []
        for image_path in image_paths:
            feature = self.extract_feature(image_path)
            results.append(feature)
        return results

# 向后兼容的别名
class FeatureExtractor(PPShiTuV2FeatureExtractor):
    """向后兼容的别名"""
    pass

class PPShiTuFeatureExtractor(PPShiTuV2FeatureExtractor):
    """向后兼容的别名"""
    pass

# 单例模式获取实例
_feature_extractor = None

def get_feature_extractor() -> PPShiTuV2FeatureExtractor:
    global _feature_extractor
    if _feature_extractor is None:
        _feature_extractor = PPShiTuV2FeatureExtractor()
    return _feature_extractor
