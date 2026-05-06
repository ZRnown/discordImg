from __future__ import annotations

from collections import OrderedDict
import glob
import inspect
import json
import logging
import os
import re
from threading import Lock
from types import SimpleNamespace
from typing import Any, Dict, Optional, Sequence, Type

import cv2
import numpy as np
from PIL import Image, ImageOps

try:
    from .common import (
        _normalize_product_pair,
        _PRODUCT_RANK_SECOND_BEST_WEIGHT,
        _PRODUCT_RANK_TOP3_MEAN_WEIGHT,
        _PRODUCT_RANK_TOP5_MEAN_WEIGHT,
        aggregate_product_rankings,
        extract_directional_hard_negative_pairs,
        extract_hard_negative_pairs,
        extract_query_supervised_cluster_samples,
        extract_query_supervised_pair_samples,
        fit_ridge_classifier,
        merge_scored_product_support_rows,
        rerank_candidate_products_with_cluster_classifier_scores,
        rerank_candidate_products_with_directional_classifier_score_swaps,
        rerank_candidate_products_with_directional_pairwise_classifiers,
        rerank_candidate_products_with_directional_pairwise_score_swaps,
        rerank_candidate_products_with_pairwise_classifiers,
        rerank_candidate_products_with_pairwise_score_swaps,
        rerank_candidate_products_with_classifier,
        score_ridge_classifier,
        select_query_variant_rankings,
    )
except ImportError:
    from common import (
        _normalize_product_pair,
        _PRODUCT_RANK_SECOND_BEST_WEIGHT,
        _PRODUCT_RANK_TOP3_MEAN_WEIGHT,
        _PRODUCT_RANK_TOP5_MEAN_WEIGHT,
        aggregate_product_rankings,
        extract_directional_hard_negative_pairs,
        extract_hard_negative_pairs,
        extract_query_supervised_cluster_samples,
        extract_query_supervised_pair_samples,
        fit_ridge_classifier,
        merge_scored_product_support_rows,
        rerank_candidate_products_with_cluster_classifier_scores,
        rerank_candidate_products_with_directional_classifier_score_swaps,
        rerank_candidate_products_with_directional_pairwise_classifiers,
        rerank_candidate_products_with_directional_pairwise_score_swaps,
        rerank_candidate_products_with_pairwise_classifiers,
        rerank_candidate_products_with_pairwise_score_swaps,
        rerank_candidate_products_with_classifier,
        score_ridge_classifier,
        select_query_variant_rankings,
    )
try:
    from ..product_category import infer_product_category
except ImportError:
    try:
        from product_category import infer_product_category
    except ImportError:
        infer_product_category = None

logger = logging.getLogger(__name__)

_GENERIC_TOKENS = {
    "shoe", "shoes", "sneaker", "sneakers", "jacket", "jackets", "hoodie", "hoodies",
    "sweater", "shirt", "shirts", "short", "shorts", "bag", "bags", "watch", "watches",
    "long", "sleeve", "sleeves", "cardigan", "coat", "pants", "jeans", "denim", "stand",
    "collar", "hot", "step",
}
_RESAMPLING = getattr(Image, "Resampling", Image)


def _normalize_embedding(embedding) -> Optional[np.ndarray]:
    if embedding is None:
        return None
    vector = np.array(embedding, dtype=np.float32).flatten()
    if vector.size == 0:
        return None
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm
    return vector


def _unwrap_siglip_feature_tensor(features):
    if features is None:
        return None

    for attr_name in ("image_embeds", "pooler_output", "last_hidden_state"):
        value = getattr(features, attr_name, None)
        if value is not None:
            return value

    if isinstance(features, (list, tuple)):
        if not features:
            return None
        first = features[0]
        if isinstance(first, (int, float, np.integer, np.floating)):
            return features
        for item in features:
            if item is not None:
                return item
        return None

    return features


def _coerce_serialized_float_array(raw_value) -> Optional[np.ndarray]:
    if raw_value is None:
        return None

    if isinstance(raw_value, np.ndarray):
        vector = raw_value.astype(np.float32, copy=False).flatten()
        return vector if vector.size > 0 else None

    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        if not stripped:
            return None
        if stripped.startswith("[") and stripped.endswith("]"):
            stripped = stripped[1:-1].strip()
        if not stripped:
            return None
        if all(char not in stripped for char in "[]{}"):
            vector = np.fromstring(stripped, sep=",", dtype=np.float32)
            if vector.size > 0:
                return vector
        try:
            parsed = json.loads(raw_value)
        except Exception:
            return None
        vector = np.array(parsed, dtype=np.float32).flatten()
        return vector if vector.size > 0 else None

    vector = np.array(raw_value, dtype=np.float32).flatten()
    return vector if vector.size > 0 else None


def _coerce_siglip_embedding(features, expected_dim: Optional[int] = None) -> Optional[np.ndarray]:
    resolved = _unwrap_siglip_feature_tensor(features)
    if resolved is None:
        return None

    if hasattr(resolved, "detach"):
        resolved = resolved.detach().cpu().numpy()

    if isinstance(resolved, str):
        vector = _coerce_serialized_float_array(resolved)
        if vector is None:
            return None
    else:
        vector = np.array(resolved, dtype=np.float32)
        if vector.size == 0:
            return None

        vector = np.squeeze(vector)
        if vector.ndim >= 2:
            trailing_dim = int(vector.shape[-1]) if vector.shape[-1] else 0
            vector = vector.reshape(-1, trailing_dim).mean(axis=0) if trailing_dim > 0 else vector.flatten()
        else:
            vector = vector.flatten()

    effective_dim = int(expected_dim or 0)
    if effective_dim > 0 and vector.size > effective_dim and vector.size % effective_dim == 0:
        vector = vector.reshape(-1, effective_dim).mean(axis=0)

    return _normalize_embedding(vector)


def _blend_embeddings(
    left,
    right,
    left_weight: float,
    right_weight: float,
) -> Optional[np.ndarray]:
    left_vec = _normalize_embedding(left)
    right_vec = _normalize_embedding(right)
    if left_vec is None and right_vec is None:
        return None
    if left_vec is None:
        return right_vec
    if right_vec is None:
        return left_vec
    if left_vec.shape != right_vec.shape:
        return None
    merged = (left_vec * float(left_weight)) + (right_vec * float(right_weight))
    return _normalize_embedding(merged)


def _fuse_embeddings(vectors: list[Optional[np.ndarray]], weights: list[float]) -> Optional[np.ndarray]:
    if len(vectors) != len(weights):
        return None

    merged = None
    for vector, weight in zip(vectors, weights):
        normalized = _normalize_embedding(vector)
        if normalized is None:
            continue
        w = float(weight)
        if w <= 0:
            continue
        if merged is None:
            merged = normalized * w
        else:
            if merged.shape != normalized.shape:
                return None
            merged = merged + (normalized * w)

    return _normalize_embedding(merged) if merged is not None else None


def _load_non_negative_env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return float(default)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return float(default)
    if value < 0:
        return float(default)
    return value


def _load_env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return bool(default)
    value = str(raw).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return bool(default)


def _load_non_negative_env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return int(default)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return int(default)
    if value < 0:
        return int(default)
    return value


def _load_crop_mode_env(name: str, default: str = "raw") -> str:
    allowed = {"raw", "center", "yolo"}
    raw = str(os.getenv(name, default) or default).strip().lower()
    return raw if raw in allowed else default


_DEFAULT_TARGETED_STAGE2_CLUSTERS: tuple[tuple[str, ...], ...] = (
    ("918", "931", "932"),
    ("923", "925", "927", "930"),
    ("916", "922", "924", "926", "933"),
)


def _load_cluster_spec_env(
    name: str,
    default: Sequence[tuple[str, ...]],
) -> tuple[tuple[str, ...], ...]:
    raw = str(os.getenv(name, "") or "").strip()
    if not raw:
        return tuple(tuple(cluster_key) for cluster_key in default)

    parsed: list[tuple[str, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for cluster_token in raw.split(";"):
        members = tuple(
            sorted(
                {
                    str(member or "").strip()
                    for member in cluster_token.split(",")
                    if str(member or "").strip()
                }
            )
        )
        if len(members) < 2 or members in seen:
            continue
        seen.add(members)
        parsed.append(members)
    return tuple(parsed) if parsed else tuple(tuple(cluster_key) for cluster_key in default)


class CurrentDinoHybridStrategy:
    name = "current_dino_hybrid"

    def __init__(self):
        try:
            from ..feature_extractor import get_feature_extractor
        except ImportError:
            from feature_extractor import get_feature_extractor

        self.extractor = get_feature_extractor()

    def prepare_catalog_image(self, record) -> Dict[str, Any]:
        embedding = self.extractor.extract_feature(record.image_path)
        return {
            "image_path": record.image_path,
            "embedding": embedding,
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        embedding = self.extractor.extract_feature(record.image_path)
        query_signature = self.extractor.prepare_hybrid_query(record.image_path)
        return {
            "image_path": record.image_path,
            "embedding": embedding,
            "query_signature": query_signature,
        }

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0

        dino_score = float(np.dot(query_embedding, catalog_embedding))
        hybrid = self.extractor.calculate_hybrid_similarity(
            query_context["image_path"],
            catalog_context["image_path"],
            dino_score,
            query_signature=query_context.get("query_signature"),
        )
        return float(hybrid.get("score", dino_score))


class _Siglip2Encoder:
    model_id = "google/siglip2-base-patch16-224"
    query_min_side = 32
    query_max_side = 448

    def __init__(self):
        import torch
        from transformers import AutoModel, AutoProcessor

        try:
            from ..config import config
        except ImportError:
            from config import config

        try:
            from ..feature_extractor import get_feature_extractor
        except ImportError:
            from feature_extractor import get_feature_extractor

        self.torch = torch
        self.device = torch.device(getattr(config, "DEVICE", "cpu"))
        self.center_crop_weight = float(getattr(config, "QUERY_CENTER_CROP_WEIGHT", 0.4))
        self.yolo_crop_weight = float(getattr(config, "QUERY_YOLO_CROP_WEIGHT", 0.6))

        self.processor = AutoProcessor.from_pretrained(self.model_id, use_fast=True)
        self.model = self._load_pretrained_model(self.model_id, force_no_safetensors=False)
        if self._model_has_meta(self.model):
            logger.warning("SigLIP2模型检测到 meta tensor，尝试禁用 safetensors 重新加载")
            self.model = self._load_pretrained_model(self.model_id, force_no_safetensors=True)
        if self._model_has_meta(self.model):
            raise RuntimeError("SigLIP2模型仍处于 meta 状态，请检查 transformers/torch 版本或缓存")
        if getattr(self.device, "type", None) != "cpu":
            self.model.to(self.device)
        self.model.eval()
        model_config = getattr(self.model, "config", None)
        self.output_dim = int(
            getattr(model_config, "projection_dim", 0)
            or getattr(model_config, "hidden_size", 0)
            or 768
        )

        try:
            self.cropper = get_feature_extractor()
        except Exception as exc:
            logger.warning("SigLIP2 crop helper unavailable: %s", exc)
            self.cropper = None

    def _load_pretrained_model(self, model_name: str, force_no_safetensors: bool):
        from transformers import AutoModel

        load_kwargs = {
            "low_cpu_mem_usage": False,
            "torch_dtype": self.torch.float32,
            "device_map": None,
        }
        if force_no_safetensors:
            load_kwargs["use_safetensors"] = False

        try:
            sig = inspect.signature(AutoModel.from_pretrained)
            allowed = set(sig.parameters.keys())
            load_kwargs = {key: value for key, value in load_kwargs.items() if key in allowed}
        except Exception:
            pass

        return AutoModel.from_pretrained(model_name, **load_kwargs)

    @staticmethod
    def _model_has_meta(model) -> bool:
        try:
            return any(getattr(param, "is_meta", False) for param in model.parameters())
        except Exception:
            return False

    @staticmethod
    def _normalize_image_for_inference(
        image: Image.Image,
        *,
        min_side: int = 32,
        max_side: int = 448,
    ) -> Image.Image:
        normalized = ImageOps.exif_transpose(image).convert("RGB")
        width, height = normalized.size
        if width <= 0 or height <= 0:
            return normalized

        max_side = max(int(max_side or 0), 1)
        min_side = max(int(min_side or 0), 1)

        longest_side = max(width, height)
        if longest_side > max_side:
            scale = max_side / float(longest_side)
            resized_width = max(int(round(width * scale)), 1)
            resized_height = max(int(round(height * scale)), 1)
            normalized = normalized.resize(
                (resized_width, resized_height),
                _RESAMPLING.LANCZOS,
            )
            width, height = normalized.size

        shortest_side = min(width, height)
        if shortest_side < min_side:
            scale = min_side / float(shortest_side)
            resized_width = max(int(round(width * scale)), 1)
            resized_height = max(int(round(height * scale)), 1)
            normalized = normalized.resize(
                (resized_width, resized_height),
                _RESAMPLING.BICUBIC,
            )

        return normalized

    @staticmethod
    def _fallback_center_crop(image: Image.Image) -> Image.Image:
        width, height = image.size
        left = int(width * 0.1)
        top = int(height * 0.1)
        right = int(width * 0.9)
        bottom = int(height * 0.9)
        return image.crop((left, top, right, bottom))

    def _prepare_image(
        self,
        image_path: str,
        crop_mode: str,
        image: Optional[Image.Image] = None,
    ) -> Image.Image:
        if image is None:
            with Image.open(image_path) as source_image:
                image = source_image.convert("RGB")
        else:
            image = image.convert("RGB")

        image = self._normalize_image_for_inference(
            image,
            min_side=self.query_min_side,
            max_side=self.query_max_side,
        )

        if crop_mode == "raw":
            return image

        if crop_mode == "center":
            if self.cropper is not None and hasattr(self.cropper, "_center_crop"):
                return self._normalize_image_for_inference(
                    self.cropper._center_crop(image),
                    min_side=self.query_min_side,
                    max_side=self.query_max_side,
                )
            return self._normalize_image_for_inference(
                self._fallback_center_crop(image),
                min_side=self.query_min_side,
                max_side=self.query_max_side,
            )

        if crop_mode == "yolo":
            if self.cropper is not None and hasattr(self.cropper, "_crop_main_object"):
                return self._normalize_image_for_inference(
                    self.cropper._crop_main_object(image_path),
                    min_side=self.query_min_side,
                    max_side=self.query_max_side,
                )
            return self._normalize_image_for_inference(
                self._fallback_center_crop(image),
                min_side=self.query_min_side,
                max_side=self.query_max_side,
            )

        raise ValueError(f"unsupported crop_mode: {crop_mode}")

    def encode_image(
        self,
        image_path: str,
        crop_mode: str = "raw",
        image: Optional[Image.Image] = None,
    ) -> Optional[np.ndarray]:
        try:
            image = self._prepare_image(
                image_path,
                crop_mode=crop_mode,
                image=image,
            )
            inputs = self.processor(images=image, return_tensors="pt")
            inputs = {
                key: value.to(self.device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
            with self.torch.no_grad():
                if hasattr(self.model, "get_image_features"):
                    features = self.model.get_image_features(**inputs)
                else:
                    outputs = self.model(**inputs)
                    features = getattr(outputs, "image_embeds", None)
                    if features is None:
                        features = getattr(outputs, "pooler_output", None)
                    if features is None:
                        features = getattr(outputs, "last_hidden_state", None)
            return _coerce_siglip_embedding(features, expected_dim=self.output_dim)
        except Exception as exc:
            logger.warning("SigLIP2 encode failed for %s (%s): %s", image_path, crop_mode, exc)
            return None


class _Siglip2CropStrategyBase:
    name = "siglip2_base"
    catalog_crop_mode = "raw"
    query_crop_mode = "raw"

    def __init__(self):
        self.encoder = _Siglip2Encoder()

    def prepare_catalog_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self.encoder.encode_image(record.image_path, crop_mode=self.catalog_crop_mode),
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self.encoder.encode_image(record.image_path, crop_mode=self.query_crop_mode),
        }

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0
        return float(np.dot(query_embedding, catalog_embedding))


class Siglip2Strategy(_Siglip2CropStrategyBase):
    name = "siglip2_base"
    catalog_crop_mode = "raw"
    query_crop_mode = "raw"


class Siglip2CenterCropStrategy(_Siglip2CropStrategyBase):
    name = "siglip2_center_crop"
    catalog_crop_mode = "center"
    query_crop_mode = "center"


class Siglip2YoloCropStrategy(_Siglip2CropStrategyBase):
    name = "siglip2_yolo_crop"
    catalog_crop_mode = "yolo"
    query_crop_mode = "yolo"


class Siglip2QueryFusionStrategy:
    name = "siglip2_query_fusion"

    def __init__(self):
        self.encoder = _Siglip2Encoder()

    def prepare_catalog_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self.encoder.encode_image(record.image_path, crop_mode="yolo"),
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        center_embedding = self.encoder.encode_image(record.image_path, crop_mode="center")
        yolo_embedding = self.encoder.encode_image(record.image_path, crop_mode="yolo")
        return {
            "image_path": record.image_path,
            "embedding": _blend_embeddings(
                center_embedding,
                yolo_embedding,
                self.encoder.center_crop_weight,
                self.encoder.yolo_crop_weight,
            ),
        }

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0
        return float(np.dot(query_embedding, catalog_embedding))


class FashionSiglipStrategy:
    name = "fashion_siglip"
    model_id = "hf-hub:Marqo/marqo-fashionSigLIP"

    def __init__(self):
        import open_clip
        import torch

        try:
            from ..config import config
        except ImportError:
            from config import config

        self.open_clip = open_clip
        self.torch = torch
        self.device = torch.device(getattr(config, "DEVICE", "cpu"))
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            self.model_id,
            device=str(self.device),
        )
        self.model.eval()

    def _encode_image(self, image_path: str) -> Optional[np.ndarray]:
        try:
            image = Image.open(image_path).convert("RGB")
            image_tensor = self.preprocess(image).unsqueeze(0).to(self.device)
            with self.torch.no_grad():
                features = self.model.encode_image(image_tensor, normalize=True)
            return _normalize_embedding(features[0].detach().cpu().numpy())
        except Exception as exc:
            logger.warning("FashionSigLIP encode failed for %s: %s", image_path, exc)
            return None

    def prepare_catalog_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self._encode_image(record.image_path),
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self._encode_image(record.image_path),
        }

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0
        return float(np.dot(query_embedding, catalog_embedding))


class MarqoFashionClipStrategy:
    name = "marqo_fashionclip"
    model_id = "hf-hub:Marqo/marqo-fashionCLIP"

    def __init__(self):
        import open_clip
        import torch

        try:
            from ..config import config
        except ImportError:
            from config import config

        self.open_clip = open_clip
        self.torch = torch
        self.device = torch.device(getattr(config, "DEVICE", "cpu"))
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            self.model_id,
            device=str(self.device),
        )
        self.model.eval()

    def _encode_image(self, image_path: str) -> Optional[np.ndarray]:
        try:
            image = Image.open(image_path).convert("RGB")
            image_tensor = self.preprocess(image).unsqueeze(0).to(self.device)
            with self.torch.no_grad():
                features = self.model.encode_image(image_tensor, normalize=True)
            return _normalize_embedding(features[0].detach().cpu().numpy())
        except Exception as exc:
            logger.warning("Marqo FashionCLIP encode failed for %s: %s", image_path, exc)
            return None

    def prepare_catalog_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self._encode_image(record.image_path),
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self._encode_image(record.image_path),
        }

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0
        return float(np.dot(query_embedding, catalog_embedding))


class GroundingSiglip2Strategy:
    name = "grounding_siglip2"
    siglip_model_id = "google/siglip2-base-patch16-224"
    grounding_model_id = "IDEA-Research/grounding-dino-tiny"
    grounding_prompt = (
        "shoe. sneaker. boot. jacket. hoodie. sweater. cardigan. shirt. t-shirt. "
        "shorts. pants. jeans. bag. handbag. watch. glasses."
    )

    def __init__(self):
        import torch
        from transformers import AutoModel, AutoModelForZeroShotObjectDetection, AutoProcessor

        try:
            from ..config import config
        except ImportError:
            from config import config

        self.torch = torch
        self.device = torch.device(getattr(config, "DEVICE", "cpu"))
        self.siglip_processor = AutoProcessor.from_pretrained(self.siglip_model_id)
        self.siglip_model = AutoModel.from_pretrained(self.siglip_model_id)
        self.siglip_model.to(self.device)
        self.siglip_model.eval()

        self.grounding_processor = AutoProcessor.from_pretrained(self.grounding_model_id)
        self.grounding_model = AutoModelForZeroShotObjectDetection.from_pretrained(self.grounding_model_id)
        self.grounding_model.to(self.device)
        self.grounding_model.eval()

    @staticmethod
    def _center_crop(image: Image.Image) -> Image.Image:
        width, height = image.size
        left = int(width * 0.1)
        top = int(height * 0.1)
        right = int(width * 0.9)
        bottom = int(height * 0.9)
        return image.crop((left, top, right, bottom))

    def _crop_with_grounding(self, image: Image.Image) -> Image.Image:
        try:
            inputs = self.grounding_processor(
                images=image,
                text=self.grounding_prompt,
                return_tensors="pt",
            )
            inputs = {
                key: value.to(self.device) if hasattr(value, "to") else value
                for key, value in inputs.items()
            }
            with self.torch.no_grad():
                outputs = self.grounding_model(**inputs)
            results = self.grounding_processor.post_process_grounded_object_detection(
                outputs,
                inputs["input_ids"],
                threshold=0.25,
                text_threshold=0.2,
                target_sizes=[image.size[::-1]],
            )
            detections = results[0]
            boxes = detections.get("boxes")
            scores = detections.get("scores")
            if boxes is None or scores is None or len(boxes) == 0:
                return self._center_crop(image)

            width, height = image.size
            center_x = width / 2
            center_y = height / 2
            best_index = 0
            best_score = -1.0

            for index, box in enumerate(boxes):
                x1, y1, x2, y2 = box.tolist()
                area_ratio = max(0.0, (x2 - x1) * (y2 - y1)) / float(width * height)
                box_center_x = (x1 + x2) / 2
                box_center_y = (y1 + y2) / 2
                center_bias = 1.0 - (
                    ((box_center_x - center_x) ** 2 + (box_center_y - center_y) ** 2) ** 0.5
                    / ((width ** 2 + height ** 2) ** 0.5)
                )
                candidate_score = float(scores[index]) * 0.6 + area_ratio * 0.3 + center_bias * 0.1
                if candidate_score > best_score:
                    best_score = candidate_score
                    best_index = index

            x1, y1, x2, y2 = boxes[best_index].tolist()
            pad_x = (x2 - x1) * 0.05
            pad_y = (y2 - y1) * 0.05
            crop_box = (
                max(0, int(x1 - pad_x)),
                max(0, int(y1 - pad_y)),
                min(width, int(x2 + pad_x)),
                min(height, int(y2 + pad_y)),
            )
            return image.crop(crop_box)
        except Exception as exc:
            logger.warning("GroundingDINO crop failed: %s", exc)
            return self._center_crop(image)

    def _encode_image(self, image_path: str, use_grounding: bool = False) -> Optional[np.ndarray]:
        try:
            image = Image.open(image_path).convert("RGB")
            if use_grounding:
                image = self._crop_with_grounding(image)
            inputs = self.siglip_processor(images=image, return_tensors="pt")
            inputs = {key: value.to(self.device) for key, value in inputs.items()}
            with self.torch.no_grad():
                features = self.siglip_model.get_image_features(**inputs)
            output_dim = int(
                getattr(getattr(self.siglip_model, "config", None), "projection_dim", 0)
                or getattr(getattr(self.siglip_model, "config", None), "hidden_size", 0)
                or 768
            )
            return _coerce_siglip_embedding(features, expected_dim=output_dim)
        except Exception as exc:
            logger.warning("Grounding+SigLIP2 encode failed for %s: %s", image_path, exc)
            return None

    def prepare_catalog_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self._encode_image(record.image_path, use_grounding=False),
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self._encode_image(record.image_path, use_grounding=True),
        }

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0
        return float(np.dot(query_embedding, catalog_embedding))


class Siglip2RerankStrategy:
    name = "siglip2_rerank"
    cache_version = "siglip2_rerank_v1"

    def __init__(self):
        self.encoder = _Siglip2Encoder()
        self.image_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_IMAGE_WEIGHT",
            0.74,
        )
        self.color_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_COLOR_WEIGHT",
            0.11,
        )
        self.text_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_TEXT_WEIGHT",
            0.15,
        )
        self.category_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_CATEGORY_WEIGHT",
            0.0,
        )
        self.bonus_score = _load_non_negative_env_float(
            "SIGLIP2_RERANK_BONUS_SCORE",
            0.05,
        )
        self.bonus_text_gate = _load_non_negative_env_float(
            "SIGLIP2_RERANK_BONUS_TEXT_GATE",
            0.5,
        )
        self.bonus_image_gate = _load_non_negative_env_float(
            "SIGLIP2_RERANK_BONUS_IMAGE_GATE",
            0.5,
        )
        self.query_fusion_enabled = _load_env_bool(
            "SIGLIP2_RERANK_QUERY_FUSION",
            False,
        )
        self.query_raw_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_QUERY_RAW_WEIGHT",
            1.0,
        )
        self.query_center_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_QUERY_CENTER_WEIGHT",
            0.0,
        )
        self.query_yolo_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_QUERY_YOLO_WEIGHT",
            0.0,
        )
        self.catalog_crop_mode = _load_crop_mode_env(
            "SIGLIP2_RERANK_CATALOG_CROP_MODE",
            "raw",
        )
        self.catalog_fusion_enabled = _load_env_bool(
            "SIGLIP2_RERANK_CATALOG_FUSION",
            False,
        )
        self.catalog_raw_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_CATALOG_RAW_WEIGHT",
            1.0,
        )
        self.catalog_center_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_CATALOG_CENTER_WEIGHT",
            0.0,
        )
        self.catalog_yolo_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_CATALOG_YOLO_WEIGHT",
            0.0,
        )
        self.adaptive_raw_center_enabled = _load_env_bool(
            "SIGLIP2_RERANK_ADAPTIVE_RAW_CENTER",
            False,
        )
        self.adaptive_raw_delta = _load_non_negative_env_float(
            "SIGLIP2_RERANK_ADAPTIVE_RAW_DELTA",
            0.03,
        )
        self.product_support_enabled = _load_env_bool(
            "SIGLIP2_RERANK_PRODUCT_SUPPORT_ENABLED",
            False,
        )
        self.product_support_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_PRODUCT_SUPPORT_WEIGHT",
            1.0,
        )
        self.product_support_limit = _load_non_negative_env_int(
            "SIGLIP2_RERANK_PRODUCT_SUPPORT_LIMIT",
            1,
        )
        self.stage2_ridge_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_RIDGE_ENABLED",
            False,
        )
        self.stage2_candidate_k = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_CANDIDATE_K",
            5,
        )
        self.stage2_ridge_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_RIDGE_ALPHA",
            50.0,
        )
        self.stage2_ridge_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_RIDGE_BLEND",
            0.05,
        )
        self.stage2_hard_negative_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_ENABLED",
            False,
        )
        self.stage2_hard_negative_report_path = str(
            os.getenv("SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_REPORT_PATH", "") or ""
        ).strip()
        self.stage2_hard_negative_min_count = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_MIN_COUNT",
            2,
        )
        self.stage2_hard_negative_pair_limit = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_PAIR_LIMIT",
            12,
        )
        self.stage2_hard_negative_near_miss_k = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_NEAR_MISS_K",
            3,
        )
        self.stage2_hard_negative_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_ALPHA",
            25.0,
        )
        self.stage2_hard_negative_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_BLEND",
            0.04,
        )
        self.stage2_hard_negative_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_HARD_NEGATIVE_SCORE_GAP",
            0.10,
        )
        self.stage2_query_pair_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_ENABLED",
            False,
        )
        self.stage2_query_pair_report_path = str(
            os.getenv(
                "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_REPORT_PATH",
                self.stage2_hard_negative_report_path or "",
            )
            or ""
        ).strip()
        self.stage2_query_pair_min_count = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_MIN_COUNT",
            2,
        )
        self.stage2_query_pair_pair_limit = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_LIMIT",
            10,
        )
        self.stage2_query_pair_near_miss_k = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_NEAR_MISS_K",
            3,
        )
        self.stage2_query_pair_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_ALPHA",
            10.0,
        )
        self.stage2_query_pair_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_BLEND",
            0.02,
        )
        self.stage2_query_pair_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_SCORE_GAP",
            0.05,
        )
        self.stage2_query_pair_swap_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_SWAP_ENABLED",
            False,
        )
        self.stage2_query_pair_pair_margin = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_PAIR_MARGIN",
            0.0,
        )
        self.stage2_query_pair_query_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_QUERY_REPEAT",
            1,
        )
        self.stage2_query_pair_catalog_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_CATALOG_REPEAT",
            0,
        )
        self.stage2_query_pair_catalog_only_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_QUERY_PAIR_CATALOG_ONLY_ENABLED",
            False,
        )
        self.stage2_dynamic_cluster_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_DYNAMIC_CLUSTER_ENABLED",
            False,
        )
        self.stage2_dynamic_cluster_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_DYNAMIC_CLUSTER_ALPHA",
            10.0,
        )
        self.stage2_dynamic_cluster_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_DYNAMIC_CLUSTER_BLEND",
            0.04,
        )
        self.stage2_dynamic_cluster_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_DYNAMIC_CLUSTER_SCORE_GAP",
            0.05,
        )
        self.stage2_dynamic_cluster_catalog_limit = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_DYNAMIC_CLUSTER_CATALOG_LIMIT",
            8,
        )
        self.stage2_query_cluster_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_ENABLED",
            False,
        )
        self.stage2_query_cluster_report_path = str(
            os.getenv(
                "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_REPORT_PATH",
                self.stage2_query_pair_report_path or self.stage2_hard_negative_report_path or "",
            )
            or ""
        ).strip()
        self.stage2_query_cluster_min_count = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_MIN_COUNT",
            2,
        )
        self.stage2_query_cluster_limit = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_LIMIT",
            6,
        )
        self.stage2_query_cluster_near_miss_k = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_NEAR_MISS_K",
            3,
        )
        self.stage2_query_cluster_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_ALPHA",
            10.0,
        )
        self.stage2_query_cluster_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_BLEND",
            0.04,
        )
        self.stage2_query_cluster_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_SCORE_GAP",
            0.05,
        )
        self.stage2_query_cluster_query_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_QUERY_REPEAT",
            1,
        )
        self.stage2_query_cluster_catalog_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_QUERY_CLUSTER_CATALOG_REPEAT",
            0,
        )
        self.stage2_targeted_cluster_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_ENABLED",
            False,
        )
        self.stage2_targeted_cluster_report_path = str(
            os.getenv(
                "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_REPORT_PATH",
                self.stage2_query_cluster_report_path
                or self.stage2_query_pair_report_path
                or self.stage2_hard_negative_report_path
                or "",
            )
            or ""
        ).strip()
        self.stage2_targeted_cluster_keys = _load_cluster_spec_env(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_KEYS",
            _DEFAULT_TARGETED_STAGE2_CLUSTERS,
        )
        self.stage2_targeted_cluster_min_count = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_MIN_COUNT",
            1,
        )
        self.stage2_targeted_cluster_near_miss_k = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_NEAR_MISS_K",
            3,
        )
        self.stage2_targeted_cluster_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_ALPHA",
            8.0,
        )
        self.stage2_targeted_cluster_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_BLEND",
            0.05,
        )
        self.stage2_targeted_cluster_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_SCORE_GAP",
            0.06,
        )
        self.stage2_targeted_cluster_pair_margin = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_PAIR_MARGIN",
            0.01,
        )
        self.stage2_targeted_cluster_query_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_QUERY_REPEAT",
            2,
        )
        self.stage2_targeted_cluster_catalog_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_CLUSTER_CATALOG_REPEAT",
            1,
        )
        self.stage2_targeted_pair_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_ENABLED",
            False,
        )
        self.stage2_targeted_pair_report_path = str(
            os.getenv(
                "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_REPORT_PATH",
                self.stage2_targeted_cluster_report_path
                or self.stage2_query_cluster_report_path
                or self.stage2_query_pair_report_path
                or self.stage2_hard_negative_report_path
                or "",
            )
            or ""
        ).strip()
        self.stage2_targeted_pair_min_count = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_MIN_COUNT",
            1,
        )
        self.stage2_targeted_pair_near_miss_k = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_NEAR_MISS_K",
            3,
        )
        self.stage2_targeted_pair_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_ALPHA",
            8.0,
        )
        self.stage2_targeted_pair_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_SCORE_GAP",
            0.06,
        )
        self.stage2_targeted_pair_pair_margin = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_PAIR_MARGIN",
            0.01,
        )
        self.stage2_targeted_pair_query_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_QUERY_REPEAT",
            2,
        )
        self.stage2_targeted_pair_catalog_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_CATALOG_REPEAT",
            1,
        )
        self.stage2_targeted_pair_oneway_only = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_ONEWAY_ONLY",
            False,
        )
        self.stage2_targeted_pair_oneway_alpha = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_ONEWAY_ALPHA",
            self.stage2_targeted_pair_alpha,
        )
        self.stage2_targeted_pair_oneway_query_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_ONEWAY_QUERY_REPEAT",
            self.stage2_targeted_pair_query_repeat,
        )
        self.stage2_targeted_pair_oneway_catalog_repeat = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_TARGETED_PAIR_ONEWAY_CATALOG_REPEAT",
            self.stage2_targeted_pair_catalog_repeat,
        )
        self.stage2_targeted_support_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_TARGETED_SUPPORT_ENABLED",
            False,
        )
        self.stage2_targeted_support_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_SUPPORT_BLEND",
            0.04,
        )
        self.stage2_targeted_support_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_SUPPORT_SCORE_GAP",
            0.05,
        )
        self.stage2_targeted_support_top2_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_SUPPORT_TOP2_WEIGHT",
            0.25,
        )
        self.stage2_targeted_support_mean_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_TARGETED_SUPPORT_MEAN_WEIGHT",
            0.0,
        )
        self.stage2_support_stats_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_SUPPORT_STATS_ENABLED",
            False,
        )
        self.stage2_support_stats_blend = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_SUPPORT_STATS_BLEND",
            0.04,
        )
        self.stage2_support_stats_score_gap = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_SUPPORT_STATS_SCORE_GAP",
            0.05,
        )
        self.stage2_support_stats_top2_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_SUPPORT_STATS_TOP2_WEIGHT",
            0.25,
        )
        self.stage2_support_stats_mean_weight = _load_non_negative_env_float(
            "SIGLIP2_RERANK_STAGE2_SUPPORT_STATS_MEAN_WEIGHT",
            0.0,
        )
        self.stage2_support_stats_min_support = _load_non_negative_env_int(
            "SIGLIP2_RERANK_STAGE2_SUPPORT_STATS_MIN_SUPPORT",
            1,
        )
        self._stage2_classifier_signature = None
        self._stage2_classifier = None
        self._stage2_hard_negative_rules_signature = None
        self._stage2_hard_negative_rules = ()
        self._stage2_pairwise_classifiers_signature = None
        self._stage2_pairwise_classifiers = None
        self._stage2_query_pair_samples_signature = None
        self._stage2_query_pair_samples = {}
        self._stage2_query_pair_directional_rules_signature = None
        self._stage2_query_pair_directional_rules = ()
        self._stage2_query_pair_embedding_signature = None
        self._stage2_query_pair_embeddings = {}
        self._stage2_query_pair_catalog_only_classifier_signature = None
        self._stage2_query_pair_catalog_only_classifier_cache = {}
        self._stage2_catalog_query_payload_signature = None
        self._stage2_catalog_query_payload_cache = OrderedDict()
        self.fast_rank_cache_scopes = _load_non_negative_env_int(
            "SIGLIP2_RERANK_FAST_RANK_CACHE_SCOPES",
            4,
        )
        self._fast_rank_cache = OrderedDict()
        self._fast_rank_cache_catalog_keys = {}
        self._fast_rank_cache_lock = Lock()
        self._stage2_dynamic_cluster_classifier_signature = None
        self._stage2_dynamic_cluster_classifier_cache = {}
        self._stage2_query_cluster_samples_signature = None
        self._stage2_query_cluster_samples = {}
        self._stage2_query_cluster_embedding_signature = None
        self._stage2_query_cluster_embeddings = {}
        self._stage2_targeted_cluster_samples_signature = None
        self._stage2_targeted_cluster_samples = {}
        self._stage2_targeted_cluster_directional_rules_signature = None
        self._stage2_targeted_cluster_directional_rules = {}
        self._stage2_targeted_pair_samples_signature = None
        self._stage2_targeted_pair_samples = {}
        self._product_support_signature = None
        self._product_support_by_product: Dict[str, list[Dict[str, Any]]] = {}
        self.cache_version = self._build_cache_version()

    def supports_streaming_live_search(self) -> bool:
        return not any(
            (
                bool(getattr(self, "product_support_enabled", False)),
                bool(getattr(self, "adaptive_raw_center_enabled", False)),
                bool(getattr(self, "stage2_ridge_enabled", False)),
                bool(getattr(self, "stage2_hard_negative_enabled", False)),
                bool(getattr(self, "stage2_query_pair_enabled", False)),
                bool(getattr(self, "stage2_dynamic_cluster_enabled", False)),
                bool(getattr(self, "stage2_query_cluster_enabled", False)),
                bool(getattr(self, "stage2_targeted_support_enabled", False)),
                bool(getattr(self, "stage2_targeted_cluster_enabled", False)),
                bool(getattr(self, "stage2_targeted_pair_enabled", False)),
                bool(getattr(self, "stage2_support_stats_enabled", False)),
            )
        )

    @staticmethod
    def _format_weight_token(value: float) -> str:
        return f"{float(value):.2f}".replace(".", "p")

    def _build_cache_version(self) -> str:
        if self.catalog_fusion_enabled:
            return (
                "siglip2_rerank_v2_cf_"
                f"{self._format_weight_token(self.catalog_raw_weight)}_"
                f"{self._format_weight_token(self.catalog_center_weight)}_"
                f"{self._format_weight_token(self.catalog_yolo_weight)}"
            )
        return f"siglip2_rerank_v2_cat_{self.catalog_crop_mode}"

    def _get_compatible_catalog_cache_versions(self) -> set[str]:
        versions = {str(self.cache_version or "").strip()}
        if (
            not getattr(self, "catalog_fusion_enabled", False)
            and str(getattr(self, "catalog_crop_mode", "raw") or "raw").strip().lower() == "raw"
        ):
            # `siglip2_rerank_v1` was written before catalog crop/fusion config
            # was versioned. Its payload matches the current raw catalog path.
            versions.add("siglip2_rerank_v1")
        versions.discard("")
        return versions

    def _build_catalog_embedding(self, image_path: str):
        raw_embedding = None
        center_embedding = None
        yolo_embedding = None
        if getattr(self, "catalog_fusion_enabled", False):
            if float(getattr(self, "catalog_raw_weight", 1.0)) > 0:
                raw_embedding = self.encoder.encode_image(image_path, crop_mode="raw")
            if float(getattr(self, "catalog_center_weight", 0.0)) > 0:
                center_embedding = self.encoder.encode_image(image_path, crop_mode="center")
            if float(getattr(self, "catalog_yolo_weight", 0.0)) > 0:
                yolo_embedding = self.encoder.encode_image(image_path, crop_mode="yolo")
            fused = _fuse_embeddings(
                [raw_embedding, center_embedding, yolo_embedding],
                [
                    float(getattr(self, "catalog_raw_weight", 1.0)),
                    float(getattr(self, "catalog_center_weight", 0.0)),
                    float(getattr(self, "catalog_yolo_weight", 0.0)),
                ],
            )
            if fused is not None:
                return fused
        return self.encoder.encode_image(
            image_path,
            crop_mode=str(getattr(self, "catalog_crop_mode", "raw") or "raw"),
        )

    def _build_color_hist(self, image_path: str):
        try:
            image = np.array(Image.open(image_path).convert("RGB"))
            hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
            hist = cv2.calcHist([hsv], [0, 1], None, [18, 4], [0, 180, 0, 256])
            cv2.normalize(hist, hist, 0, 1, cv2.NORM_MINMAX)
            return hist
        except Exception as exc:
            logger.warning("SigLIP2 rerank hist failed for %s: %s", image_path, exc)
            return None

    def _tokenize(self, *values: str):
        tokens = set()
        for value in values:
            parts = re.findall(r"[a-z0-9]+", str(value or "").lower())
            for token in parts:
                if len(token) <= 1:
                    continue
                if token in _GENERIC_TOKENS:
                    continue
                tokens.add(token)
        return tokens

    @staticmethod
    def _infer_category(*values: str) -> str:
        if not callable(infer_product_category):
            return ""
        try:
            return str(infer_product_category(*values) or "").strip()
        except Exception:
            return ""

    @staticmethod
    def _deserialize_cached_hist(raw_hist) -> Optional[np.ndarray]:
        hist = _coerce_serialized_float_array(raw_hist)
        if hist is None:
            return None
        if hist.size == 72:
            hist = hist.reshape((18, 4))
        return hist

    def build_catalog_cache_payload(self, record) -> Dict[str, Any]:
        embedding = self._build_catalog_embedding(record.image_path)
        hist = self._build_color_hist(record.image_path)
        tokens = sorted(self._tokenize(record.title, " ".join(record.queries)))
        return {
            "embedding": embedding.tolist() if embedding is not None else None,
            "color_hist": hist.flatten().astype(np.float32).tolist() if hist is not None else None,
            "tokens": tokens,
            "cache_version": self.cache_version,
        }

    @staticmethod
    def _text_overlap(query_tokens, catalog_tokens) -> float:
        if not query_tokens or not catalog_tokens:
            return 0.0
        return len(query_tokens & catalog_tokens) / float(len(query_tokens))

    def prepare_catalog_image(self, record) -> Dict[str, Any]:
        cached_version = str(getattr(record, "cache_version", "") or "")
        effective_cached_version = cached_version
        if not effective_cached_version and any(
            getattr(record, field_name, None) is not None
            for field_name in ("cache_embedding", "cache_color_hist", "cache_tokens")
        ):
            effective_cached_version = "siglip2_rerank_v1"
        can_use_cache = bool(
            effective_cached_version
            and effective_cached_version in self._get_compatible_catalog_cache_versions()
        )

        cached_embedding = (
            _coerce_siglip_embedding(
                getattr(record, "cache_embedding", None),
                expected_dim=int(getattr(getattr(self, "encoder", None), "output_dim", 0) or 768),
            )
            if can_use_cache
            else None
        )
        cached_hist = (
            self._deserialize_cached_hist(getattr(record, "cache_color_hist", None))
            if can_use_cache
            else None
        )
        cached_tokens = (
            set(getattr(record, "cache_tokens", []) or [])
            if can_use_cache
            else set()
        )

        return {
            "image_path": record.image_path,
            "embedding": cached_embedding if cached_embedding is not None else self._build_catalog_embedding(record.image_path),
            "hist": cached_hist if cached_hist is not None else self._build_color_hist(record.image_path),
            "tokens": cached_tokens if cached_tokens else self._tokenize(record.title, " ".join(record.queries)),
            "category": self._infer_category(record.title, " ".join(record.queries)),
        }

    def _build_query_embedding_payload(self, image_path: str) -> Dict[str, Any]:
        with Image.open(image_path) as source_image:
            loaded_image = self.encoder._normalize_image_for_inference(
                source_image,
                min_side=self.encoder.query_min_side,
                max_side=self.encoder.query_max_side,
            )

        raw_embedding = self.encoder.encode_image(
            image_path,
            crop_mode="raw",
            image=loaded_image,
        )
        center_embedding = None
        yolo_embedding = None
        if self.query_fusion_enabled:
            if self.query_center_weight > 0:
                center_embedding = self.encoder.encode_image(
                    image_path,
                    crop_mode="center",
                    image=loaded_image,
                )
            if self.query_yolo_weight > 0:
                yolo_embedding = self.encoder.encode_image(image_path, crop_mode="yolo")

        fused_embedding = _fuse_embeddings(
            [raw_embedding, center_embedding, yolo_embedding],
            [self.query_raw_weight, self.query_center_weight, self.query_yolo_weight],
        )
        return {
            "embedding": fused_embedding if fused_embedding is not None else raw_embedding,
            "raw_embedding": raw_embedding,
            "center_embedding": center_embedding,
            "yolo_embedding": yolo_embedding,
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        embedding_payload = self._build_query_embedding_payload(record.image_path)
        return {
            "image_path": record.image_path,
            **embedding_payload,
            "hist": self._build_color_hist(record.image_path),
            "tokens": self._tokenize(record.query, " ".join(record.product_queries)),
            "category": self._infer_category(record.query, " ".join(record.product_queries)),
        }

    def set_query_support_records(self, query_records: list[Any]) -> None:
        self.set_product_support_records(query_records)

    def set_product_support_records(
        self,
        support_records: list[Any],
        prepared_catalog: Optional[list[Dict[str, Any]]] = None,
    ) -> None:
        if not self.product_support_enabled:
            self._product_support_signature = None
            self._product_support_by_product = {}
            return

        signature = tuple(
            sorted(
                (
                    str(
                        getattr(record, "expected_product_id", "")
                        or getattr(record, "product_id", "")
                        or ""
                    ).strip(),
                    str(getattr(record, "image_path", "") or "").strip(),
                )
                for record in support_records
                if str(
                    getattr(record, "expected_product_id", "")
                    or getattr(record, "product_id", "")
                    or ""
                ).strip()
                and str(getattr(record, "image_path", "") or "").strip()
            )
        )
        if signature == self._product_support_signature:
            return

        catalog_context_by_path: Dict[str, Dict[str, Any]] = {}
        for entry in prepared_catalog or []:
            record = entry.get("record")
            context = entry.get("context")
            image_path = str(getattr(record, "image_path", "") or "").strip()
            if image_path and context is not None and image_path not in catalog_context_by_path:
                catalog_context_by_path[image_path] = context

        support_by_product: Dict[str, list[Dict[str, Any]]] = {}
        for record in support_records:
            product_id = str(
                getattr(record, "expected_product_id", "")
                or getattr(record, "product_id", "")
                or ""
            ).strip()
            image_path = str(getattr(record, "image_path", "") or "").strip()
            if not product_id or not image_path:
                continue

            product_queries = list(
                getattr(record, "product_queries", None)
                or getattr(record, "queries", None)
                or []
            )
            pseudo_catalog_record = SimpleNamespace(
                image_path=image_path,
                title=str(getattr(record, "title", "") or ""),
                queries=product_queries,
                cache_version="",
                cache_embedding=None,
                cache_color_hist=None,
                cache_tokens=[],
            )
            support_context = catalog_context_by_path.get(image_path)
            if support_context is None:
                support_context = self.prepare_catalog_image(pseudo_catalog_record)
            support_by_product.setdefault(product_id, []).append(
                {
                    "product_id": product_id,
                    "title": pseudo_catalog_record.title,
                    "image_path": image_path,
                    "query_image_path": image_path,
                    "image_index": -1,
                    "context": support_context,
                    **support_context,
                }
            )

        self._product_support_signature = signature
        self._product_support_by_product = support_by_product

    def _build_scored_product_support_rows(
        self,
        query_context: Dict[str, Any],
    ) -> Dict[str, list[Dict[str, Any]]]:
        support_weight = float(self.product_support_weight or 0.0)
        if (
            not self.product_support_enabled
            or support_weight <= 0
            or not self._product_support_by_product
        ):
            return {}

        scored_rows_by_product: Dict[str, list[Dict[str, Any]]] = {}
        for product_id, rows in self._product_support_by_product.items():
            product_rows: list[Dict[str, Any]] = []
            for row in rows:
                product_rows.append(
                    {
                        "product_id": product_id,
                        "title": row.get("title", ""),
                        "score": float(self.score(query_context, row["context"])) * support_weight,
                        "image_path": row.get("image_path", ""),
                        "image_index": row.get("image_index", -1),
                    }
                )
            if product_rows:
                scored_rows_by_product[product_id] = product_rows
        return scored_rows_by_product

    def _build_image_rankings_for_query_context(
        self,
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> list[Dict[str, Any]]:
        image_rankings: list[Dict[str, Any]] = []
        for entry in prepared_catalog:
            record = entry["record"]
            image_rankings.append(
                {
                    "product_id": record.product_id,
                    "title": record.title,
                    "score": float(self.score(query_context, entry["context"])),
                    "image_path": record.image_path,
                    "image_index": record.image_index,
                }
            )
        allowed_product_ids = {
            str(entry["record"].product_id)
            for entry in prepared_catalog
            if str(getattr(entry.get("record"), "product_id", "") or "").strip()
        }
        support_rows_by_product = self._build_scored_product_support_rows(query_context)
        if support_rows_by_product:
            if not allowed_product_ids:
                support_rows_by_product = {}
            else:
                support_rows_by_product = {
                    product_id: rows
                    for product_id, rows in support_rows_by_product.items()
                    if str(product_id) in allowed_product_ids
                }
        if support_rows_by_product:
            image_rankings = merge_scored_product_support_rows(
                image_rankings,
                support_rows_by_product=support_rows_by_product,
                exclude_image_path=str(query_context.get("image_path") or ""),
                support_limit=self.product_support_limit,
            )
        return image_rankings

    def _can_use_fast_rank_products(self) -> bool:
        return not any(
            (
                bool(getattr(self, "product_support_enabled", False)),
                bool(getattr(self, "stage2_ridge_enabled", False)),
                bool(getattr(self, "stage2_hard_negative_enabled", False)),
                bool(getattr(self, "stage2_query_pair_enabled", False)),
                bool(getattr(self, "stage2_dynamic_cluster_enabled", False)),
                bool(getattr(self, "stage2_query_cluster_enabled", False)),
                bool(getattr(self, "stage2_targeted_support_enabled", False)),
                bool(getattr(self, "stage2_targeted_cluster_enabled", False)),
                bool(getattr(self, "stage2_targeted_pair_enabled", False)),
                bool(getattr(self, "stage2_support_stats_enabled", False)),
            )
        )

    @staticmethod
    def _rank_vectorized_product_scores(
        image_rankings: Sequence[Dict[str, Any]],
        *,
        top_k: int,
    ) -> list[Dict[str, Any]]:
        grouped_by_product: Dict[str, list[Dict[str, Any]]] = {}
        for row in image_rankings:
            product_id = str(row.get("product_id") or "")
            if not product_id:
                continue
            grouped_by_product.setdefault(product_id, []).append(row)

        ranked_with_signal = []
        for product_id, rows in grouped_by_product.items():
            scored_rows = sorted(
                rows,
                key=lambda item: float(item.get("score", 0.0)),
                reverse=True,
            )
            if not scored_rows:
                continue
            best_row = scored_rows[0]
            scores = [float(item.get("score", 0.0)) for item in scored_rows[:5]]
            best_score = float(scores[0])
            second_best_score = float(scores[1]) if len(scores) > 1 else 0.0
            top3_mean_score = float(np.mean(scores[:3])) if scores else 0.0
            top5_mean_score = float(np.mean(scores[:5])) if scores else 0.0
            rank_score = (
                best_score
                + _PRODUCT_RANK_SECOND_BEST_WEIGHT * second_best_score
                + _PRODUCT_RANK_TOP3_MEAN_WEIGHT * top3_mean_score
                + _PRODUCT_RANK_TOP5_MEAN_WEIGHT * top5_mean_score
            )
            ranked_with_signal.append(
                (
                    rank_score,
                    {
                        "product_id": product_id,
                        "score": best_score,
                        "title": best_row.get("title", ""),
                        "image_path": best_row.get("image_path", ""),
                        "image_index": best_row.get("image_index"),
                    },
                )
            )

        return [
            item
            for _rank_score, item in sorted(
                ranked_with_signal,
                key=lambda pair: (
                    -float(pair[0]),
                    -float(pair[1].get("score", 0.0)),
                    str(pair[1].get("product_id") or ""),
                    int(pair[1].get("image_index") or 0),
                    str(pair[1].get("image_path") or ""),
                ),
            )
        ][: max(int(top_k or 1), 1)]

    @staticmethod
    def _build_fast_rank_cache_key(
        prepared_catalog: list[Dict[str, Any]],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                str(getattr(entry.get("record"), "product_id", "") or ""),
                str(getattr(entry.get("record"), "image_path", "") or ""),
            )
            for entry in prepared_catalog
        )

    @staticmethod
    def _catalog_contexts_for_fast_rank(
        prepared_catalog: list[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        entries: list[tuple[Any, Dict[str, Any]]] = []
        embeddings: list[np.ndarray] = []
        hist_vectors: list[np.ndarray] = []
        hist_indices: list[int] = []
        product_ids: list[str] = []
        titles: list[str] = []
        image_paths: list[str] = []
        image_indices: list[int] = []
        token_sets: list[Any] = []
        categories: list[str] = []
        for entry in prepared_catalog:
            context = entry.get("context") or {}
            embedding = context.get("embedding")
            if embedding is None:
                continue
            vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
            if vector.size == 0:
                continue
            record = entry.get("record")
            if record is None:
                continue
            entry_index = len(entries)
            entries.append((record, context))
            embeddings.append(vector)
            product_ids.append(str(getattr(record, "product_id", "") or ""))
            titles.append(str(getattr(record, "title", "") or ""))
            image_paths.append(str(getattr(record, "image_path", "") or ""))
            try:
                image_indices.append(int(getattr(record, "image_index", 0) or 0))
            except (TypeError, ValueError):
                image_indices.append(0)
            token_sets.append(context.get("tokens") or set())
            categories.append(str(context.get("category") or ""))
            raw_hist = context.get("hist")
            if raw_hist is not None:
                hist_vector = np.asarray(raw_hist, dtype=np.float32).reshape(-1)
                if hist_vector.size:
                    hist_indices.append(entry_index)
                    hist_vectors.append(hist_vector)

        if not entries:
            return None

        matrix = np.vstack(embeddings).astype(np.float32, copy=False)
        hist_matrix = None
        hist_index_array = np.asarray(hist_indices, dtype=np.int64)
        if hist_vectors:
            first_hist_size = int(hist_vectors[0].size)
            if first_hist_size > 0 and all(int(vector.size) == first_hist_size for vector in hist_vectors):
                hist_matrix = np.vstack(hist_vectors).astype(np.float32, copy=False)
        return {
            "entries": entries,
            "matrix": matrix,
            "hist_matrix": hist_matrix,
            "hist_indices": hist_index_array,
            "product_ids": product_ids,
            "titles": titles,
            "image_paths": image_paths,
            "image_indices": image_indices,
            "token_sets": token_sets,
            "categories": categories,
        }

    @staticmethod
    def _rank_precomputed_product_scores(
        final_scores: np.ndarray,
        catalog_contexts: Dict[str, Any],
        *,
        top_k: int,
    ) -> list[Dict[str, Any]]:
        product_ids = catalog_contexts.get("product_ids") or []
        if not product_ids:
            return []

        product_state: Dict[str, Dict[str, Any]] = {}
        score_array = np.asarray(final_scores, dtype=np.float32).reshape(-1)
        titles = catalog_contexts.get("titles") or []
        image_paths = catalog_contexts.get("image_paths") or []
        image_indices = catalog_contexts.get("image_indices") or []
        for index, product_id in enumerate(product_ids):
            if not product_id or index >= score_array.size:
                continue
            score = float(score_array[index])
            state = product_state.get(product_id)
            if state is None:
                state = {
                    "scores": [],
                    "best_score": score,
                    "best_index": index,
                }
                product_state[product_id] = state
            else:
                if score > float(state["best_score"]):
                    state["best_score"] = score
                    state["best_index"] = index
            state["scores"].append(score)

        ranked_with_signal = []
        for product_id, state in product_state.items():
            scores = sorted(state["scores"], reverse=True)[:5]
            if not scores:
                continue
            best_score = float(scores[0])
            second_best_score = float(scores[1]) if len(scores) > 1 else 0.0
            top3_mean_score = float(np.mean(scores[:3]))
            top5_mean_score = float(np.mean(scores[:5]))
            rank_score = (
                best_score
                + _PRODUCT_RANK_SECOND_BEST_WEIGHT * second_best_score
                + _PRODUCT_RANK_TOP3_MEAN_WEIGHT * top3_mean_score
                + _PRODUCT_RANK_TOP5_MEAN_WEIGHT * top5_mean_score
            )
            best_index = int(state["best_index"])
            ranked_with_signal.append(
                (
                    rank_score,
                    {
                        "product_id": product_id,
                        "score": best_score,
                        "title": titles[best_index] if best_index < len(titles) else "",
                        "image_path": image_paths[best_index] if best_index < len(image_paths) else "",
                        "image_index": image_indices[best_index] if best_index < len(image_indices) else 0,
                    },
                )
            )

        return [
            item
            for _rank_score, item in sorted(
                ranked_with_signal,
                key=lambda pair: (
                    -float(pair[0]),
                    -float(pair[1].get("score", 0.0)),
                    str(pair[1].get("product_id") or ""),
                    int(pair[1].get("image_index") or 0),
                    str(pair[1].get("image_path") or ""),
                ),
            )
        ][: max(int(top_k or 1), 1)]

    def _get_fast_rank_catalog_contexts(
        self,
        prepared_catalog: list[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        max_scopes = max(int(getattr(self, "fast_rank_cache_scopes", 0) or 0), 0)
        catalog_object_key = id(prepared_catalog)
        cache_key = self._fast_rank_cache_catalog_keys.get(catalog_object_key)
        if cache_key is None:
            cache_key = self._build_fast_rank_cache_key(prepared_catalog)
            self._fast_rank_cache_catalog_keys[catalog_object_key] = cache_key
        if max_scopes > 0:
            with self._fast_rank_cache_lock:
                cached = self._fast_rank_cache.get(cache_key)
                if cached is not None:
                    self._fast_rank_cache.move_to_end(cache_key)
                    return cached

        built = self._catalog_contexts_for_fast_rank(prepared_catalog)
        if built is None or max_scopes <= 0:
            return built

        with self._fast_rank_cache_lock:
            self._fast_rank_cache[cache_key] = built
            self._fast_rank_cache.move_to_end(cache_key)
            while len(self._fast_rank_cache) > max_scopes:
                removed_key, _removed_value = self._fast_rank_cache.popitem(last=False)
                for catalog_id, mapped_key in list(self._fast_rank_cache_catalog_keys.items()):
                    if mapped_key == removed_key:
                        self._fast_rank_cache_catalog_keys.pop(catalog_id, None)
        return built

    def _rank_products_fast_for_context(
        self,
        query_context: Dict[str, Any],
        catalog_contexts: Dict[str, Any],
        top_k: int,
    ) -> Optional[list[Dict[str, Any]]]:
        query_embedding = query_context.get("embedding")
        if query_embedding is None:
            return []

        query_vector = np.asarray(query_embedding, dtype=np.float32).reshape(-1)
        matrix = catalog_contexts["matrix"]
        if matrix.ndim != 2 or matrix.shape[1] != query_vector.size:
            return None

        image_weight = float(getattr(self, "image_weight", 0.74))
        color_weight = float(getattr(self, "color_weight", 0.11))
        text_weight = float(getattr(self, "text_weight", 0.15))
        category_weight = float(getattr(self, "category_weight", 0.0))
        bonus_score = float(getattr(self, "bonus_score", 0.05))
        bonus_text_gate = float(getattr(self, "bonus_text_gate", 0.5))
        bonus_image_gate = float(getattr(self, "bonus_image_gate", 0.5))

        image_scores = matrix @ query_vector
        final_scores = image_scores.astype(np.float32, copy=True) * image_weight
        total_weights = np.full(final_scores.shape, image_weight, dtype=np.float32)

        query_hist = query_context.get("hist")
        query_hist_vector = (
            np.asarray(query_hist, dtype=np.float32).reshape(-1)
            if query_hist is not None
            else None
        )
        if query_hist_vector is not None and query_hist_vector.size and color_weight > 0:
            hist_matrix = catalog_contexts.get("hist_matrix")
            hist_indices = catalog_contexts.get("hist_indices")
            if (
                hist_matrix is not None
                and hist_indices is not None
                and getattr(hist_matrix, "ndim", 0) == 2
                and hist_matrix.shape[1] == query_hist_vector.size
                and len(hist_indices) == hist_matrix.shape[0]
            ):
                query_centered = query_hist_vector - float(query_hist_vector.mean())
                hist_centered = hist_matrix - hist_matrix.mean(axis=1, keepdims=True)
                denom = np.linalg.norm(hist_centered, axis=1) * float(np.linalg.norm(query_centered))
                color_scores = np.zeros(len(hist_indices), dtype=np.float32)
                valid = denom > 0
                if np.any(valid):
                    color_scores[valid] = (
                        hist_centered[valid] @ query_centered
                    ) / denom[valid]
                color_scores = np.maximum(color_scores, 0.0)
                final_scores[hist_indices] += color_weight * color_scores
                total_weights[hist_indices] += color_weight

        query_tokens = query_context.get("tokens")
        has_query_tokens = bool(query_tokens)
        text_scores = np.zeros(final_scores.shape, dtype=np.float32)
        if has_query_tokens and text_weight > 0:
            query_token_set = set(query_tokens)
            query_token_count = float(len(query_token_set))
            if query_token_count > 0:
                for index, catalog_tokens in enumerate(catalog_contexts.get("token_sets") or []):
                    if not catalog_tokens:
                        continue
                    text_score = len(query_token_set & set(catalog_tokens)) / query_token_count
                    text_scores[index] = float(text_score)
                    final_scores[index] += text_weight * float(text_score)
                    total_weights[index] += text_weight

        query_category = str(query_context.get("category") or "").strip()
        if query_category and category_weight > 0:
            for index, raw_category in enumerate(catalog_contexts.get("categories") or []):
                catalog_category = str(raw_category or "").strip()
                if not catalog_category:
                    continue
                category_score = 1.0 if query_category == catalog_category else 0.0
                final_scores[index] += category_weight * category_score
                total_weights[index] += category_weight

        with np.errstate(divide="ignore", invalid="ignore"):
            final_scores = np.divide(
                final_scores,
                total_weights,
                out=np.zeros_like(final_scores, dtype=np.float32),
                where=total_weights > 0,
            )
        if has_query_tokens and bonus_score > 0:
            bonus_mask = (text_scores > bonus_text_gate) & (image_scores > bonus_image_gate)
            final_scores[bonus_mask] += bonus_score
        final_scores = np.minimum(final_scores, 1.0)

        return self._rank_precomputed_product_scores(
            final_scores,
            catalog_contexts,
            top_k=max(int(top_k or 1), 1),
        )

    def rank_products_fast(
        self,
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
        top_k: int = 10,
    ) -> Optional[Dict[str, Any]]:
        if not self._can_use_fast_rank_products():
            return None

        query_embedding = query_context.get("embedding")
        if query_embedding is None or not prepared_catalog:
            return {"ranked_products": []}

        catalog_contexts = self._get_fast_rank_catalog_contexts(prepared_catalog)
        if not catalog_contexts:
            return {"ranked_products": []}

        ranked_products = self._rank_products_fast_for_context(
            query_context,
            catalog_contexts,
            top_k=max(int(top_k or 1), 1),
        )
        if ranked_products is None:
            return None

        if self.query_fusion_enabled:
            raw_embedding = query_context.get("raw_embedding")
            default_embedding = query_context.get("embedding")
            if (
                raw_embedding is not None
                and default_embedding is not None
                and self.query_raw_weight > 0
                and (self.query_center_weight > 0 or self.query_yolo_weight > 0)
            ):
                raw_query_context = dict(query_context)
                raw_query_context["embedding"] = raw_embedding
                raw_ranked_products = self._rank_products_fast_for_context(
                    raw_query_context,
                    catalog_contexts,
                    top_k=max(int(top_k or 1), 1),
                )
                if raw_ranked_products is None:
                    return None
                _selected_variant, ranked_products = select_query_variant_rankings(
                    {
                        "main": ranked_products,
                        "raw": raw_ranked_products,
                    },
                    default_variant="main",
                    challenger_variant="raw",
                    challenger_min_delta=self.adaptive_raw_delta,
                )

        return {
            "ranked_products": ranked_products,
            "fast_rank": True,
        }

    @staticmethod
    def _build_catalog_signature(
        prepared_catalog: list[Dict[str, Any]],
    ) -> tuple[tuple[str, str], ...]:
        return tuple(
            (
                str(entry["record"].product_id),
                str(entry["record"].image_path),
            )
            for entry in prepared_catalog
        )

    def _get_stage2_classifier(
        self,
        prepared_catalog: list[Dict[str, Any]],
    ):
        if not self.stage2_ridge_enabled:
            return None

        signature = self._build_catalog_signature(prepared_catalog)
        if signature == self._stage2_classifier_signature and self._stage2_classifier is not None:
            return self._stage2_classifier

        features = []
        labels = []
        for entry in prepared_catalog:
            embedding = entry["context"].get("embedding")
            if embedding is None:
                continue
            features.append(embedding)
            labels.append(str(entry["record"].product_id))

        if len(features) < 2 or len(set(labels)) < 2:
            self._stage2_classifier_signature = signature
            self._stage2_classifier = None
            return None

        try:
            classifier = fit_ridge_classifier(
                features,
                labels,
                alpha=self.stage2_ridge_alpha,
            )
        except Exception as exc:
            logger.warning("SigLIP2 stage2 ridge fit failed: %s", exc)
            classifier = None

        self._stage2_classifier_signature = signature
        self._stage2_classifier = classifier
        return classifier

    def _load_stage2_hard_negative_rules(self) -> tuple[tuple[str, str], ...]:
        if not self.stage2_hard_negative_enabled:
            return ()

        resolved_report_path = self._resolve_stage2_hard_negative_report_path(
            self.stage2_hard_negative_report_path
        )
        if not resolved_report_path:
            return ()

        try:
            stat_result = os.stat(resolved_report_path)
            signature = (
                resolved_report_path,
                int(stat_result.st_mtime_ns),
                int(self.stage2_hard_negative_min_count),
                int(self.stage2_hard_negative_pair_limit),
                int(self.stage2_hard_negative_near_miss_k),
            )
        except OSError as exc:
            logger.warning("SigLIP2 hard-negative report unavailable: %s", exc)
            return ()

        if signature == self._stage2_hard_negative_rules_signature:
            return self._stage2_hard_negative_rules

        try:
            with open(resolved_report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            directional_rules = tuple(
                extract_hard_negative_pairs(
                    report.get("results", []),
                    min_count=self.stage2_hard_negative_min_count,
                    limit=self.stage2_hard_negative_pair_limit,
                )
            )
        except Exception as exc:
            logger.warning("SigLIP2 hard-negative pair load failed: %s", exc)
            directional_rules = ()

        self._stage2_hard_negative_rules_signature = signature
        self._stage2_hard_negative_rules = directional_rules
        return directional_rules

    @staticmethod
    def _load_stage2_report_quality(candidate_path: str) -> Optional[float]:
        try:
            with open(candidate_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:
            return None

        if not isinstance(payload, dict):
            return None
        rows = payload.get("results")
        if not isinstance(rows, list) or not rows:
            return None
        first_row = rows[0] if isinstance(rows[0], dict) else {}
        ranked_products = first_row.get("ranked_products")
        expected_product_id = str(first_row.get("expected_product_id") or "").strip()
        if not (expected_product_id and isinstance(ranked_products, list)):
            return None

        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        metric_hit_at_1 = metrics.get("hit_at_1") if isinstance(metrics, dict) else None
        if metric_hit_at_1 is not None:
            try:
                return float(metric_hit_at_1)
            except (TypeError, ValueError):
                pass

        hit_at_1_count = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            expected_id = str(row.get("expected_product_id") or "").strip()
            ranked = row.get("ranked_products")
            if not expected_id or not isinstance(ranked, list) or not ranked:
                continue
            top1_id = str((ranked[0] or {}).get("product_id") or "").strip()
            if top1_id == expected_id:
                hit_at_1_count += 1
        return float(hit_at_1_count) / float(len(rows))

    @classmethod
    def _discover_latest_stage2_report_path(
        cls,
        auto_glob: str = "",
    ) -> str:
        benchmark_dir = os.path.dirname(__file__)
        candidate_paths: list[str] = []
        resolved_auto_glob = str(auto_glob or "").strip()
        if resolved_auto_glob:
            glob_candidates = [resolved_auto_glob]
            if not os.path.isabs(resolved_auto_glob):
                glob_candidates.extend(
                    [
                        os.path.join(benchmark_dir, resolved_auto_glob),
                        os.path.join(os.path.dirname(benchmark_dir), resolved_auto_glob),
                        os.path.join(os.path.dirname(os.path.dirname(benchmark_dir)), resolved_auto_glob),
                    ]
                )
            for pattern in glob_candidates:
                candidate_paths.extend(glob.glob(pattern))

        if not candidate_paths:
            return ""

        scored_candidates: list[tuple[float, float, str]] = []
        sorted_paths = sorted(
            {
                os.path.abspath(path)
                for path in candidate_paths
                if path.endswith(".json") and os.path.isfile(path)
            },
        )
        for candidate_path in sorted_paths:
            quality_score = cls._load_stage2_report_quality(candidate_path)
            if quality_score is None:
                continue
            scored_candidates.append(
                (
                    float(quality_score),
                    float(os.path.getmtime(candidate_path)),
                    candidate_path,
                )
            )

        if not scored_candidates:
            return ""

        scored_candidates.sort(key=lambda row: (row[0], row[1]), reverse=True)
        return scored_candidates[0][2]

    @classmethod
    def _resolve_stage2_hard_negative_report_path(
        cls,
        raw_path: str,
        auto_enabled: bool = False,
        auto_glob: str = "",
    ) -> str:
        report_path = str(raw_path or "").strip()
        env_auto_enabled = _load_env_bool(
            "SIGLIP2_RERANK_STAGE2_AUTO_REPORT_ENABLED",
            False,
        )
        resolved_auto_enabled = bool(auto_enabled) or bool(env_auto_enabled)
        resolved_auto_glob = str(
            auto_glob or os.getenv("SIGLIP2_RERANK_STAGE2_AUTO_REPORT_GLOB", "") or ""
        ).strip()
        if not report_path:
            if resolved_auto_enabled:
                return cls._discover_latest_stage2_report_path(resolved_auto_glob)
            return ""

        if os.path.isabs(report_path):
            return report_path

        benchmark_dir = os.path.dirname(__file__)
        candidates = [
            report_path,
            os.path.join(benchmark_dir, report_path),
            os.path.join(os.path.dirname(benchmark_dir), report_path),
            os.path.join(os.path.dirname(os.path.dirname(benchmark_dir)), report_path),
        ]
        for candidate in candidates:
            absolute_candidate = os.path.abspath(candidate)
            if os.path.exists(absolute_candidate):
                return absolute_candidate
        if resolved_auto_enabled:
            discovered_path = cls._discover_latest_stage2_report_path(resolved_auto_glob)
            if discovered_path:
                return discovered_path
        return os.path.abspath(candidates[0])

    def _get_stage2_pairwise_classifiers(
        self,
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[tuple[str, str], Dict[str, Any]]:
        hard_negative_rules = self._load_stage2_hard_negative_rules()
        if not hard_negative_rules:
            return {}

        unique_pair_keys = tuple(
            sorted(
                {
                    pair_key
                    for pair_key in (
                        _normalize_product_pair(preferred_product_id, mistaken_product_id)
                        for preferred_product_id, mistaken_product_id in hard_negative_rules
                    )
                    if pair_key is not None
                }
            )
        )
        signature = (
            self._build_catalog_signature(prepared_catalog),
            unique_pair_keys,
            float(self.stage2_hard_negative_alpha),
        )
        if (
            signature == self._stage2_pairwise_classifiers_signature
            and self._stage2_pairwise_classifiers is not None
        ):
            return self._stage2_pairwise_classifiers

        features_by_product: Dict[str, list[Any]] = {}
        for entry in prepared_catalog:
            embedding = entry["context"].get("embedding")
            if embedding is None:
                continue
            product_id = str(entry["record"].product_id)
            features_by_product.setdefault(product_id, []).append(embedding)

        pairwise_classifiers: Dict[tuple[str, str], Dict[str, Any]] = {}
        for left_product_id, right_product_id in unique_pair_keys:
            left_features = list(features_by_product.get(left_product_id) or [])
            right_features = list(features_by_product.get(right_product_id) or [])
            if not left_features or not right_features:
                continue

            try:
                pairwise_classifiers[(left_product_id, right_product_id)] = fit_ridge_classifier(
                    left_features + right_features,
                    ([left_product_id] * len(left_features)) + ([right_product_id] * len(right_features)),
                    alpha=self.stage2_hard_negative_alpha,
                )
            except Exception as exc:
                logger.warning(
                    "SigLIP2 hard-negative pair fit failed for %s/%s: %s",
                    left_product_id,
                    right_product_id,
                    exc,
                )

        self._stage2_pairwise_classifiers_signature = signature
        self._stage2_pairwise_classifiers = pairwise_classifiers
        return pairwise_classifiers

    def _load_stage2_query_pair_samples(
        self,
        prepared_catalog: Optional[list[Dict[str, Any]]] = None,
    ) -> Dict[tuple[str, str], list[Dict[str, str]]]:
        if not self.stage2_query_pair_enabled:
            return {}

        resolved_report_path = self._resolve_stage2_hard_negative_report_path(
            self.stage2_query_pair_report_path or self.stage2_hard_negative_report_path
        )
        if not resolved_report_path:
            return {}

        try:
            stat_result = os.stat(resolved_report_path)
            signature = (
                resolved_report_path,
                int(stat_result.st_mtime_ns),
                int(self.stage2_query_pair_min_count),
                int(self.stage2_query_pair_pair_limit),
                int(self.stage2_query_pair_near_miss_k),
            )
        except OSError as exc:
            logger.warning("SigLIP2 query-pair report unavailable: %s", exc)
            return {}

        if signature == self._stage2_query_pair_samples_signature:
            return self._stage2_query_pair_samples

        try:
            with open(resolved_report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            samples = extract_query_supervised_pair_samples(
                report.get("results", []),
                min_count=self.stage2_query_pair_min_count,
                limit=self.stage2_query_pair_pair_limit,
                near_miss_k=self.stage2_query_pair_near_miss_k,
            )
        except Exception as exc:
            logger.warning("SigLIP2 query-pair sample load failed: %s", exc)
            samples = {}

        self._stage2_query_pair_samples_signature = signature
        self._stage2_query_pair_samples = samples
        return samples

    def _load_stage2_query_pair_directional_rules(self) -> tuple[tuple[str, str], ...]:
        if not self.stage2_query_pair_enabled:
            return ()

        resolved_report_path = self._resolve_stage2_hard_negative_report_path(
            self.stage2_query_pair_report_path or self.stage2_hard_negative_report_path
        )
        if not resolved_report_path:
            return ()

        try:
            stat_result = os.stat(resolved_report_path)
            signature = (
                resolved_report_path,
                int(stat_result.st_mtime_ns),
                int(self.stage2_query_pair_min_count),
                int(self.stage2_query_pair_pair_limit),
                int(self.stage2_query_pair_near_miss_k),
            )
        except OSError as exc:
            logger.warning("SigLIP2 query-pair directional report unavailable: %s", exc)
            return ()

        if signature == self._stage2_query_pair_directional_rules_signature:
            return self._stage2_query_pair_directional_rules

        try:
            with open(resolved_report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            directional_rules = tuple(
                extract_directional_hard_negative_pairs(
                    report.get("results", []),
                    min_count=self.stage2_query_pair_min_count,
                    limit=self.stage2_query_pair_pair_limit,
                    near_miss_k=self.stage2_query_pair_near_miss_k,
                )
            )
        except Exception as exc:
            logger.warning("SigLIP2 query-pair directional rule load failed: %s", exc)
            directional_rules = ()

        self._stage2_query_pair_directional_rules_signature = signature
        self._stage2_query_pair_directional_rules = directional_rules
        return directional_rules

    def _get_stage2_query_pair_embeddings(
        self,
        sample_map: Dict[tuple[str, str], list[Dict[str, str]]],
    ) -> Dict[str, Dict[str, Any]]:
        query_image_paths = tuple(
            sorted(
                {
                    str(sample.get("query_image_path") or "").strip()
                    for samples in sample_map.values()
                    for sample in samples
                    if str(sample.get("query_image_path") or "").strip()
                }
            )
        )
        signature = (
            query_image_paths,
            int(bool(self.query_fusion_enabled)),
            float(self.query_raw_weight),
            float(self.query_center_weight),
            float(self.query_yolo_weight),
        )
        if signature == self._stage2_query_pair_embedding_signature:
            return self._stage2_query_pair_embeddings

        embeddings: Dict[str, Dict[str, Any]] = {}
        for query_image_path in query_image_paths:
            payload = self._build_query_embedding_payload(query_image_path)
            if payload.get("embedding") is not None:
                embeddings[query_image_path] = payload

        self._stage2_query_pair_embedding_signature = signature
        self._stage2_query_pair_embeddings = embeddings
        return embeddings

    def _resolve_stage2_query_pair_catalog_only_classifier_cache(
        self,
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[tuple[str, str], Any]:
        signature = (
            self._build_catalog_signature(prepared_catalog),
            float(getattr(self, "stage2_query_pair_alpha", 0.0) or 0.0),
            int(getattr(self, "stage2_query_pair_catalog_repeat", 0) or 0),
            int(bool(getattr(self, "stage2_query_pair_catalog_only_enabled", False))),
        )
        if signature != getattr(
            self,
            "_stage2_query_pair_catalog_only_classifier_signature",
            None,
        ):
            self._stage2_query_pair_catalog_only_classifier_signature = signature
            self._stage2_query_pair_catalog_only_classifier_cache = {}
        return getattr(self, "_stage2_query_pair_catalog_only_classifier_cache", {})

    def _resolve_stage2_dynamic_cluster_classifier_cache(
        self,
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[tuple[str, ...], Any]:
        signature = (
            self._build_catalog_signature(prepared_catalog),
            float(getattr(self, "stage2_dynamic_cluster_alpha", 0.0) or 0.0),
            int(getattr(self, "stage2_dynamic_cluster_catalog_limit", 0) or 0),
            int(bool(getattr(self, "stage2_dynamic_cluster_enabled", False))),
        )
        if signature != getattr(
            self,
            "_stage2_dynamic_cluster_classifier_signature",
            None,
        ):
            self._stage2_dynamic_cluster_classifier_signature = signature
            self._stage2_dynamic_cluster_classifier_cache = {}
        return getattr(self, "_stage2_dynamic_cluster_classifier_cache", {})

    def _resolve_stage2_catalog_query_payload_cache(
        self,
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Dict[str, Any]]:
        signature = (
            self._build_catalog_signature(prepared_catalog),
            int(bool(getattr(self, "query_fusion_enabled", False))),
            float(getattr(self, "query_raw_weight", 1.0) or 0.0),
            float(getattr(self, "query_center_weight", 0.0) or 0.0),
            float(getattr(self, "query_yolo_weight", 0.0) or 0.0),
        )
        if signature != getattr(self, "_stage2_catalog_query_payload_signature", None):
            self._stage2_catalog_query_payload_signature = signature
            self._stage2_catalog_query_payload_cache = OrderedDict()
        cache = getattr(self, "_stage2_catalog_query_payload_cache", None)
        if not isinstance(cache, OrderedDict):
            cache = OrderedDict(cache or {})
            self._stage2_catalog_query_payload_cache = cache
        return cache

    def _get_stage2_catalog_query_payload_cache_limit(self) -> int:
        try:
            limit = int(getattr(self, "stage2_catalog_query_payload_cache_limit", 128) or 0)
        except (TypeError, ValueError):
            return 128
        return max(limit, 0)

    def _get_stage2_catalog_query_payload(
        self,
        image_path: str,
        prepared_catalog: list[Dict[str, Any]],
        fallback_embedding=None,
    ) -> Optional[Dict[str, Any]]:
        normalized_image_path = str(image_path or "").strip()
        if not normalized_image_path:
            return None

        payload_cache = self._resolve_stage2_catalog_query_payload_cache(prepared_catalog)
        cached_payload = payload_cache.get(normalized_image_path)
        if cached_payload is not None:
            payload_cache.move_to_end(normalized_image_path)
            return cached_payload or None

        cache_limit = self._get_stage2_catalog_query_payload_cache_limit()

        try:
            payload = self._build_query_embedding_payload(normalized_image_path)
        except Exception:
            fallback_vector = _normalize_embedding(fallback_embedding)
            if fallback_vector is None:
                if cache_limit > 0:
                    payload_cache[normalized_image_path] = {}
                    payload_cache.move_to_end(normalized_image_path)
                    while len(payload_cache) > cache_limit:
                        payload_cache.popitem(last=False)
                return None
            payload = {
                "embedding": fallback_vector,
                "raw_embedding": fallback_vector,
                "center_embedding": None,
                "yolo_embedding": None,
            }
        if payload.get("embedding") is None:
            if cache_limit > 0:
                payload_cache[normalized_image_path] = {}
                payload_cache.move_to_end(normalized_image_path)
                while len(payload_cache) > cache_limit:
                    payload_cache.popitem(last=False)
            return None

        if cache_limit > 0:
            payload_cache[normalized_image_path] = payload
            payload_cache.move_to_end(normalized_image_path)
            while len(payload_cache) > cache_limit:
                payload_cache.popitem(last=False)
        return payload

    @staticmethod
    def _limit_stage2_dynamic_cluster_embeddings(
        embeddings: list[Any],
        limit: int,
    ) -> list[Any]:
        capped_limit = max(int(limit or 0), 0)
        if capped_limit <= 0 or len(embeddings) <= capped_limit:
            return list(embeddings)
        if capped_limit == 1:
            return [embeddings[0]]

        last_index = len(embeddings) - 1
        selected_indices = []
        seen_indices = set()
        for step in range(capped_limit):
            raw_index = int(round((last_index * step) / float(capped_limit - 1)))
            raw_index = min(max(raw_index, 0), last_index)
            if raw_index in seen_indices:
                continue
            seen_indices.add(raw_index)
            selected_indices.append(raw_index)

        if len(selected_indices) < capped_limit:
            for raw_index in range(len(embeddings)):
                if raw_index in seen_indices:
                    continue
                seen_indices.add(raw_index)
                selected_indices.append(raw_index)
                if len(selected_indices) >= capped_limit:
                    break

        return [embeddings[index] for index in selected_indices[:capped_limit]]

    def _build_stage2_dynamic_cluster_classifier(
        self,
        cluster_key: tuple[str, ...],
        prepared_catalog: list[Dict[str, Any]],
    ):
        normalized_cluster_key = tuple(
            sorted(
                {
                    str(product_id or "").strip()
                    for product_id in cluster_key
                    if str(product_id or "").strip()
                }
            )
        )
        if len(normalized_cluster_key) < 2:
            return None

        classifier_cache = self._resolve_stage2_dynamic_cluster_classifier_cache(
            prepared_catalog
        )
        cached_classifier = classifier_cache.get(normalized_cluster_key)
        if cached_classifier is not None:
            return cached_classifier

        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        catalog_limit = max(int(getattr(self, "stage2_dynamic_cluster_catalog_limit", 0) or 0), 0)

        features = []
        labels = []
        selected_entries_by_product: Dict[str, list[Dict[str, Any]]] = {}
        for product_id in normalized_cluster_key:
            product_entries = [
                entry
                for entry in prepared_catalog
                if str(entry["record"].product_id or "").strip() == product_id
            ]
            selected_entries_by_product[product_id] = self._limit_stage2_dynamic_cluster_embeddings(
                product_entries,
                catalog_limit,
            )

        for product_id in normalized_cluster_key:
            for entry in selected_entries_by_product.get(product_id) or []:
                pseudo_query_context = self._get_stage2_catalog_query_payload(
                    str(entry["record"].image_path or "").strip(),
                    prepared_catalog,
                    fallback_embedding=entry["context"].get("embedding"),
                )
                if pseudo_query_context is None:
                    continue
                feature = self._build_stage2_query_cluster_feature(
                    pseudo_query_context,
                    normalized_cluster_key,
                    catalog_embeddings_by_product,
                )
                features.append(feature)
                labels.append(product_id)

        if len(features) < 2 or len(set(labels)) < 2:
            return None

        try:
            classifier = fit_ridge_classifier(
                features,
                labels,
                alpha=self.stage2_dynamic_cluster_alpha,
            )
            classifier_cache[normalized_cluster_key] = classifier
            return classifier
        except Exception as exc:
            logger.warning(
                "SigLIP2 dynamic-cluster fit failed for %s: %s",
                ",".join(normalized_cluster_key),
                exc,
            )
            return None

    def _load_stage2_query_cluster_samples(self) -> Dict[tuple[str, ...], list[Dict[str, str]]]:
        if not self.stage2_query_cluster_enabled:
            return {}

        resolved_report_path = self._resolve_stage2_hard_negative_report_path(
            self.stage2_query_cluster_report_path
            or self.stage2_query_pair_report_path
            or self.stage2_hard_negative_report_path
        )
        if not resolved_report_path:
            return {}

        try:
            stat_result = os.stat(resolved_report_path)
            signature = (
                resolved_report_path,
                int(stat_result.st_mtime_ns),
                int(self.stage2_query_cluster_min_count),
                int(self.stage2_query_cluster_limit),
                int(self.stage2_query_cluster_near_miss_k),
            )
        except OSError as exc:
            logger.warning("SigLIP2 query-cluster report unavailable: %s", exc)
            return {}

        if signature == self._stage2_query_cluster_samples_signature:
            return self._stage2_query_cluster_samples

        try:
            with open(resolved_report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            samples = extract_query_supervised_cluster_samples(
                report.get("results", []),
                min_count=self.stage2_query_cluster_min_count,
                limit=self.stage2_query_cluster_limit,
                near_miss_k=self.stage2_query_cluster_near_miss_k,
            )
        except Exception as exc:
            logger.warning("SigLIP2 query-cluster sample load failed: %s", exc)
            samples = {}

        self._stage2_query_cluster_samples_signature = signature
        self._stage2_query_cluster_samples = samples
        return samples

    def _get_stage2_query_cluster_embeddings(
        self,
        sample_map: Dict[tuple[str, ...], list[Dict[str, str]]],
    ) -> Dict[str, Dict[str, Any]]:
        query_image_paths = tuple(
            sorted(
                {
                    str(sample.get("query_image_path") or "").strip()
                    for samples in sample_map.values()
                    for sample in samples
                    if str(sample.get("query_image_path") or "").strip()
                }
            )
        )
        signature = (
            query_image_paths,
            int(bool(self.query_fusion_enabled)),
            float(self.query_raw_weight),
            float(self.query_center_weight),
            float(self.query_yolo_weight),
        )
        if signature == self._stage2_query_cluster_embedding_signature:
            return self._stage2_query_cluster_embeddings

        embeddings: Dict[str, Dict[str, Any]] = {}
        for query_image_path in query_image_paths:
            payload = self._build_query_embedding_payload(query_image_path)
            if payload.get("embedding") is not None:
                embeddings[query_image_path] = payload

        self._stage2_query_cluster_embedding_signature = signature
        self._stage2_query_cluster_embeddings = embeddings
        return embeddings

    def _load_stage2_targeted_cluster_samples(
        self,
    ) -> Dict[tuple[str, ...], list[Dict[str, str]]]:
        if not (
            getattr(self, "stage2_targeted_cluster_enabled", False)
            or getattr(self, "stage2_targeted_support_enabled", False)
        ):
            return {}

        resolved_report_path = self._resolve_stage2_hard_negative_report_path(
            self.stage2_targeted_cluster_report_path
            or self.stage2_query_cluster_report_path
            or self.stage2_query_pair_report_path
            or self.stage2_hard_negative_report_path
        )
        if not resolved_report_path:
            return {}

        target_cluster_keys = tuple(
            tuple(sorted({str(product_id or "").strip() for product_id in cluster_key if str(product_id or "").strip()}))
            for cluster_key in getattr(self, "stage2_targeted_cluster_keys", _DEFAULT_TARGETED_STAGE2_CLUSTERS)
            if len({str(product_id or "").strip() for product_id in cluster_key if str(product_id or "").strip()}) >= 2
        )
        if not target_cluster_keys:
            return {}

        try:
            stat_result = os.stat(resolved_report_path)
            signature = (
                resolved_report_path,
                int(stat_result.st_mtime_ns),
                target_cluster_keys,
                int(self.stage2_targeted_cluster_min_count),
                int(self.stage2_targeted_cluster_near_miss_k),
            )
        except OSError as exc:
            logger.warning("SigLIP2 targeted-cluster report unavailable: %s", exc)
            return {}

        if signature == self._stage2_targeted_cluster_samples_signature:
            return self._stage2_targeted_cluster_samples

        try:
            with open(resolved_report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            extracted_samples = extract_query_supervised_cluster_samples(
                report.get("results", []),
                min_count=self.stage2_targeted_cluster_min_count,
                limit=0,
                near_miss_k=self.stage2_targeted_cluster_near_miss_k,
            )
            samples: Dict[tuple[str, ...], list[Dict[str, str]]] = {}
            for target_cluster_key in target_cluster_keys:
                target_members = set(target_cluster_key)
                for source_cluster_key, source_samples in extracted_samples.items():
                    if not target_members.issubset(set(source_cluster_key)):
                        continue
                    filtered_samples = [
                        dict(sample)
                        for sample in source_samples
                        if str(sample.get("label") or "").strip() in target_members
                    ]
                    if len(filtered_samples) >= max(int(self.stage2_targeted_cluster_min_count or 0), 1):
                        samples[target_cluster_key] = filtered_samples
                    break
        except Exception as exc:
            logger.warning("SigLIP2 targeted-cluster sample load failed: %s", exc)
            samples = {}

        self._stage2_targeted_cluster_samples_signature = signature
        self._stage2_targeted_cluster_samples = samples
        return samples

    def _load_stage2_targeted_cluster_directional_rules(
        self,
    ) -> Dict[tuple[str, ...], tuple[tuple[str, str], ...]]:
        if not getattr(self, "stage2_targeted_cluster_enabled", False):
            return {}

        sample_map = self._load_stage2_targeted_cluster_samples()
        if not sample_map:
            return {}

        resolved_report_path = self._resolve_stage2_hard_negative_report_path(
            self.stage2_targeted_cluster_report_path
            or self.stage2_query_cluster_report_path
            or self.stage2_query_pair_report_path
            or self.stage2_hard_negative_report_path
        )
        if not resolved_report_path:
            return {}

        try:
            stat_result = os.stat(resolved_report_path)
            signature = (
                resolved_report_path,
                int(stat_result.st_mtime_ns),
                tuple(sorted(sample_map)),
                int(self.stage2_targeted_cluster_min_count),
                int(self.stage2_targeted_cluster_near_miss_k),
            )
        except OSError as exc:
            logger.warning("SigLIP2 targeted-cluster directional report unavailable: %s", exc)
            return {}

        if signature == self._stage2_targeted_cluster_directional_rules_signature:
            return self._stage2_targeted_cluster_directional_rules

        try:
            with open(resolved_report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            extracted_rules = tuple(
                extract_directional_hard_negative_pairs(
                    report.get("results", []),
                    min_count=self.stage2_targeted_cluster_min_count,
                    limit=0,
                    near_miss_k=self.stage2_targeted_cluster_near_miss_k,
                )
            )
            directional_rule_map: Dict[tuple[str, ...], tuple[tuple[str, str], ...]] = {}
            for cluster_key in sample_map:
                cluster_members = set(cluster_key)
                cluster_rules = tuple(
                    rule
                    for rule in extracted_rules
                    if str(rule[0] or "").strip() in cluster_members
                )
                if cluster_rules:
                    directional_rule_map[cluster_key] = cluster_rules
        except Exception as exc:
            logger.warning("SigLIP2 targeted-cluster directional rule load failed: %s", exc)
            directional_rule_map = {}

        self._stage2_targeted_cluster_directional_rules_signature = signature
        self._stage2_targeted_cluster_directional_rules = directional_rule_map
        return directional_rule_map

    def _load_stage2_targeted_pair_samples(
        self,
    ) -> Dict[tuple[str, str], list[Dict[str, str]]]:
        if not getattr(self, "stage2_targeted_pair_enabled", False):
            return {}

        resolved_report_path = self._resolve_stage2_hard_negative_report_path(
            getattr(self, "stage2_targeted_pair_report_path", "")
            or getattr(self, "stage2_targeted_cluster_report_path", "")
            or getattr(self, "stage2_query_cluster_report_path", "")
            or getattr(self, "stage2_query_pair_report_path", "")
            or getattr(self, "stage2_hard_negative_report_path", "")
        )
        if not resolved_report_path:
            return {}

        target_cluster_keys = tuple(
            tuple(sorted({str(product_id or "").strip() for product_id in cluster_key if str(product_id or "").strip()}))
            for cluster_key in getattr(self, "stage2_targeted_cluster_keys", _DEFAULT_TARGETED_STAGE2_CLUSTERS)
            if len({str(product_id or "").strip() for product_id in cluster_key if str(product_id or "").strip()}) >= 2
        )
        if not target_cluster_keys:
            return {}

        try:
            stat_result = os.stat(resolved_report_path)
            signature = (
                resolved_report_path,
                int(stat_result.st_mtime_ns),
                target_cluster_keys,
                int(getattr(self, "stage2_targeted_pair_min_count", 1)),
                int(getattr(self, "stage2_targeted_pair_near_miss_k", 3)),
            )
        except OSError as exc:
            logger.warning("SigLIP2 targeted-pair report unavailable: %s", exc)
            return {}

        if signature == self._stage2_targeted_pair_samples_signature:
            return self._stage2_targeted_pair_samples

        try:
            with open(resolved_report_path, "r", encoding="utf-8") as handle:
                report = json.load(handle)
            extracted_samples = extract_query_supervised_pair_samples(
                report.get("results", []),
                min_count=getattr(self, "stage2_targeted_pair_min_count", 1),
                limit=0,
                near_miss_k=getattr(self, "stage2_targeted_pair_near_miss_k", 3),
            )
            target_clusters = [set(cluster_key) for cluster_key in target_cluster_keys]
            samples: Dict[tuple[str, str], list[Dict[str, str]]] = {}
            for pair_key, pair_samples in extracted_samples.items():
                pair_members = set(pair_key)
                if not any(pair_members.issubset(cluster_members) for cluster_members in target_clusters):
                    continue
                filtered_samples = [
                    dict(sample)
                    for sample in pair_samples
                    if str(sample.get("label") or "").strip() in pair_members
                ]
                if filtered_samples:
                    samples[pair_key] = filtered_samples
        except Exception as exc:
            logger.warning("SigLIP2 targeted-pair sample load failed: %s", exc)
            samples = {}

        self._stage2_targeted_pair_samples_signature = signature
        self._stage2_targeted_pair_samples = samples
        return samples

    @staticmethod
    def _build_catalog_embeddings_by_product(
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, list[Any]]:
        embeddings_by_product: Dict[str, list[Any]] = {}
        for entry in prepared_catalog:
            embedding = entry["context"].get("embedding")
            if embedding is None:
                continue
            product_id = str(entry["record"].product_id)
            embeddings_by_product.setdefault(product_id, []).append(embedding)
        return embeddings_by_product

    @staticmethod
    def _compute_stage2_query_pair_similarity_stats(
        query_embedding,
        product_embeddings: list[Any],
    ) -> list[float]:
        if query_embedding is None or not product_embeddings:
            return [0.0, 0.0, 0.0, 0.0]

        similarities = sorted(
            (
                float(np.dot(query_embedding, product_embedding))
                for product_embedding in product_embeddings
            ),
            reverse=True,
        )
        best_score = similarities[0]
        second_best_score = similarities[1] if len(similarities) > 1 else similarities[0]
        top2_mean_score = sum(similarities[:2]) / float(min(2, len(similarities)))
        mean_score = sum(similarities) / float(len(similarities))
        return [best_score, second_best_score, top2_mean_score, mean_score]

    def _build_stage2_query_pair_feature(
        self,
        query_context: Dict[str, Any],
        pair_key: tuple[str, str],
        catalog_embeddings_by_product: Dict[str, list[Any]],
        score_by_product: Optional[Dict[str, float]] = None,
    ) -> list[float]:
        left_product_id, right_product_id = pair_key
        left_embeddings = list(catalog_embeddings_by_product.get(left_product_id) or [])
        right_embeddings = list(catalog_embeddings_by_product.get(right_product_id) or [])

        feature: list[float] = []
        for query_embedding in (
            query_context.get("embedding"),
            query_context.get("raw_embedding"),
            query_context.get("center_embedding"),
            query_context.get("yolo_embedding"),
        ):
            left_stats = self._compute_stage2_query_pair_similarity_stats(
                query_embedding,
                left_embeddings,
            )
            right_stats = self._compute_stage2_query_pair_similarity_stats(
                query_embedding,
                right_embeddings,
            )
            feature.extend(left_stats)
            feature.extend(right_stats)
            feature.extend(
                left_value - right_value
                for left_value, right_value in zip(left_stats, right_stats)
            )

        left_score = float((score_by_product or {}).get(left_product_id, 0.0))
        right_score = float((score_by_product or {}).get(right_product_id, 0.0))
        feature.extend([left_score, right_score, left_score - right_score])
        return feature

    def _build_stage2_query_cluster_feature(
        self,
        query_context: Dict[str, Any],
        cluster_key: tuple[str, ...],
        catalog_embeddings_by_product: Dict[str, list[Any]],
        score_by_product: Optional[Dict[str, float]] = None,
    ) -> list[float]:
        feature: list[float] = []

        for query_embedding in (
            query_context.get("embedding"),
            query_context.get("raw_embedding"),
            query_context.get("center_embedding"),
            query_context.get("yolo_embedding"),
        ):
            best_scores: list[float] = []
            modal_stats_by_product: list[list[float]] = []
            for product_id in cluster_key:
                stats = self._compute_stage2_query_pair_similarity_stats(
                    query_embedding,
                    list(catalog_embeddings_by_product.get(product_id) or []),
                )
                modal_stats_by_product.append(stats)
                best_scores.append(float(stats[0]))

            modal_mean_score = (
                sum(best_scores) / float(len(best_scores))
                if best_scores
                else 0.0
            )
            for stats in modal_stats_by_product:
                feature.extend(stats)
                feature.append(float(stats[0]) - modal_mean_score)

        stage1_scores = [
            float((score_by_product or {}).get(product_id, 0.0))
            for product_id in cluster_key
        ]
        stage1_mean_score = (
            sum(stage1_scores) / float(len(stage1_scores))
            if stage1_scores
            else 0.0
        )
        for stage1_score in stage1_scores:
            feature.extend([stage1_score, stage1_score - stage1_mean_score])
        return feature

    @staticmethod
    def _resolve_support_embeddings_by_product(
        support_embedding_map: Dict[Any, Any],
        cluster_key: tuple[str, ...],
    ) -> Dict[str, list[Dict[str, Any]]]:
        if not support_embedding_map:
            return {}
        if cluster_key in support_embedding_map:
            return dict(support_embedding_map.get(cluster_key) or {})
        if all(isinstance(key, str) for key in support_embedding_map):
            return {
                str(product_id): list(rows or [])
                for product_id, rows in support_embedding_map.items()
            }
        return {}

    @staticmethod
    def _collect_support_vectors(
        support_rows: Sequence[Dict[str, Any]],
        embedding_field: str,
        exclude_query_image_path: str = "",
    ) -> list[Any]:
        excluded_path = str(exclude_query_image_path or "").strip()
        vectors: list[Any] = []
        for row in support_rows:
            query_image_path = str(row.get("query_image_path") or "").strip()
            if excluded_path and query_image_path == excluded_path:
                continue
            vector = row.get(embedding_field)
            if vector is None and embedding_field != "embedding":
                vector = row.get("embedding")
            if vector is not None:
                vectors.append(vector)
        return vectors

    def _build_stage2_targeted_cluster_support_embeddings(
        self,
        sample_map: Dict[tuple[str, ...], list[Dict[str, str]]],
    ) -> Dict[tuple[str, ...], Dict[str, list[Dict[str, Any]]]]:
        query_embeddings = self._get_stage2_query_cluster_embeddings(sample_map)
        support_embedding_map: Dict[tuple[str, ...], Dict[str, list[Dict[str, Any]]]] = {}
        for cluster_key, samples in sample_map.items():
            by_product: Dict[str, list[Dict[str, Any]]] = {}
            cluster_members = set(cluster_key)
            for sample in samples:
                query_image_path = str(sample.get("query_image_path") or "").strip()
                label = str(sample.get("label") or "").strip()
                embedding_payload = query_embeddings.get(query_image_path)
                if not query_image_path or label not in cluster_members or embedding_payload is None:
                    continue
                by_product.setdefault(label, []).append(
                    {
                        "query_image_path": query_image_path,
                        **embedding_payload,
                    }
                )
            support_embedding_map[cluster_key] = by_product
        return support_embedding_map

    def _build_stage2_targeted_pair_support_embeddings(
        self,
        sample_map: Dict[tuple[str, str], list[Dict[str, str]]],
    ) -> Dict[tuple[str, str], Dict[str, list[Dict[str, Any]]]]:
        query_embeddings = self._get_stage2_query_pair_embeddings(sample_map)
        support_embedding_map: Dict[tuple[str, str], Dict[str, list[Dict[str, Any]]]] = {}
        for pair_key, samples in sample_map.items():
            by_product: Dict[str, list[Dict[str, Any]]] = {}
            pair_members = set(pair_key)
            for sample in samples:
                query_image_path = str(sample.get("query_image_path") or "").strip()
                label = str(sample.get("label") or "").strip()
                embedding_payload = query_embeddings.get(query_image_path)
                if not query_image_path or label not in pair_members or embedding_payload is None:
                    continue
                by_product.setdefault(label, []).append(
                    {
                        "query_image_path": query_image_path,
                        **embedding_payload,
                    }
                )
            support_embedding_map[pair_key] = by_product
        return support_embedding_map

    @staticmethod
    def _build_stage2_targeted_pair_support_count_map(
        pair_key: tuple[str, str],
        pair_support_embeddings_by_product: Dict[str, list[Dict[str, Any]]],
    ) -> Dict[str, int]:
        return {
            str(product_id): len(list(pair_support_embeddings_by_product.get(product_id) or []))
            for product_id in pair_key
        }

    @classmethod
    def _is_stage2_targeted_pair_oneway(
        cls,
        pair_key: tuple[str, str],
        pair_support_embeddings_by_product: Dict[str, list[Dict[str, Any]]],
    ) -> bool:
        support_count_map = cls._build_stage2_targeted_pair_support_count_map(
            pair_key,
            pair_support_embeddings_by_product,
        )
        active_support_labels = [
            product_id
            for product_id, count in support_count_map.items()
            if int(count or 0) > 0
        ]
        return len(active_support_labels) == 1

    def _resolve_stage2_targeted_pair_train_config(
        self,
        pair_key: tuple[str, str],
        pair_support_embeddings_by_product: Dict[str, list[Dict[str, Any]]],
    ) -> tuple[bool, float, int, int]:
        is_oneway_pair = self._is_stage2_targeted_pair_oneway(
            pair_key,
            pair_support_embeddings_by_product,
        )
        if getattr(self, "stage2_targeted_pair_oneway_only", False) and not is_oneway_pair:
            return (False, 0.0, 0, 0)

        if is_oneway_pair:
            return (
                True,
                float(getattr(self, "stage2_targeted_pair_oneway_alpha", 0.0) or 0.0),
                max(int(getattr(self, "stage2_targeted_pair_oneway_query_repeat", 0) or 0), 1),
                max(int(getattr(self, "stage2_targeted_pair_oneway_catalog_repeat", 0) or 0), 0),
            )

        return (
            True,
            float(getattr(self, "stage2_targeted_pair_alpha", 0.0) or 0.0),
            max(int(getattr(self, "stage2_targeted_pair_query_repeat", 0) or 0), 1),
            max(int(getattr(self, "stage2_targeted_pair_catalog_repeat", 0) or 0), 0),
        )

    def _build_stage2_targeted_cluster_feature(
        self,
        query_context: Dict[str, Any],
        cluster_key: tuple[str, ...],
        catalog_embeddings_by_product: Dict[str, list[Any]],
        support_embeddings_by_product: Dict[str, list[Dict[str, Any]]],
        score_by_product: Optional[Dict[str, float]] = None,
        exclude_support_query_image_path: str = "",
    ) -> list[float]:
        feature: list[float] = []
        query_fields = ("embedding", "raw_embedding", "center_embedding", "yolo_embedding")

        for embedding_field in query_fields:
            query_embedding = query_context.get(embedding_field)
            if query_embedding is None and embedding_field != "embedding":
                query_embedding = query_context.get("embedding")

            modal_best_scores: list[float] = []
            modal_feature_rows: list[tuple[list[float], list[float]]] = []
            for product_id in cluster_key:
                catalog_stats = self._compute_stage2_query_pair_similarity_stats(
                    query_embedding,
                    list(catalog_embeddings_by_product.get(product_id) or []),
                )
                support_stats = self._compute_stage2_query_pair_similarity_stats(
                    query_embedding,
                    self._collect_support_vectors(
                        support_embeddings_by_product.get(product_id) or [],
                        embedding_field=embedding_field,
                        exclude_query_image_path=exclude_support_query_image_path,
                    ),
                )
                modal_feature_rows.append((catalog_stats, support_stats))
                modal_best_scores.append(max(float(catalog_stats[0]), float(support_stats[0])))

            modal_mean_best = (
                sum(modal_best_scores) / float(len(modal_best_scores))
                if modal_best_scores
                else 0.0
            )
            modal_peak = max(modal_best_scores) if modal_best_scores else 0.0

            for catalog_stats, support_stats in modal_feature_rows:
                combined_best = max(float(catalog_stats[0]), float(support_stats[0]))
                feature.extend(catalog_stats)
                feature.extend(support_stats)
                feature.extend(
                    catalog_value - support_value
                    for catalog_value, support_value in zip(catalog_stats, support_stats)
                )
                feature.extend(
                    [
                        combined_best,
                        combined_best - modal_mean_best,
                        combined_best - modal_peak,
                    ]
                )

        stage1_scores = [
            float((score_by_product or {}).get(product_id, 0.0))
            for product_id in cluster_key
        ]
        stage1_mean_score = (
            sum(stage1_scores) / float(len(stage1_scores))
            if stage1_scores
            else 0.0
        )
        stage1_peak_score = max(stage1_scores) if stage1_scores else 0.0
        for stage1_score in stage1_scores:
            feature.extend(
                [
                    stage1_score,
                    stage1_score - stage1_mean_score,
                    stage1_score - stage1_peak_score,
                ]
            )
        return feature

    def _score_stage2_targeted_support_product(
        self,
        query_context: Dict[str, Any],
        support_rows: Sequence[Dict[str, Any]],
        exclude_support_query_image_path: str = "",
        top2_weight: Optional[float] = None,
        mean_weight: Optional[float] = None,
    ) -> Optional[float]:
        if not support_rows:
            return None

        resolved_top2_weight = max(
            float(
                getattr(self, "stage2_targeted_support_top2_weight", 0.0)
                if top2_weight is None
                else top2_weight
            )
            or 0.0,
            0.0,
        )
        resolved_mean_weight = max(
            float(
                getattr(self, "stage2_targeted_support_mean_weight", 0.0)
                if mean_weight is None
                else mean_weight
            )
            or 0.0,
            0.0,
        )
        modal_scores: list[float] = []
        for embedding_field in ("embedding", "raw_embedding", "center_embedding", "yolo_embedding"):
            query_embedding = query_context.get(embedding_field)
            if query_embedding is None:
                continue
            support_vectors = self._collect_support_vectors(
                support_rows,
                embedding_field=embedding_field,
                exclude_query_image_path=exclude_support_query_image_path,
            )
            if not support_vectors:
                continue
            stats = self._compute_stage2_query_pair_similarity_stats(
                query_embedding,
                support_vectors,
            )
            modal_scores.append(
                float(stats[0])
                + (resolved_top2_weight * float(stats[2]))
                + (resolved_mean_weight * float(stats[3]))
            )

        if not modal_scores:
            return None
        return sum(modal_scores) / float(len(modal_scores))

    def _build_stage2_targeted_support_scores(
        self,
        query_context: Dict[str, Any],
        cluster_key: tuple[str, ...],
        support_embeddings_by_product: Dict[str, list[Dict[str, Any]]],
        exclude_support_query_image_path: str = "",
    ) -> Dict[str, float]:
        support_scores: Dict[str, float] = {}
        for product_id in cluster_key:
            product_score = self._score_stage2_targeted_support_product(
                query_context,
                list(support_embeddings_by_product.get(product_id) or []),
                exclude_support_query_image_path=exclude_support_query_image_path,
            )
            if product_score is None:
                continue
            support_scores[product_id] = float(product_score)
        return support_scores

    def _build_stage2_support_stats_scores(
        self,
        query_context: Dict[str, Any],
        candidate_product_ids: Sequence[str],
        exclude_support_query_image_path: str = "",
    ) -> Dict[str, float]:
        min_support = max(int(getattr(self, "stage2_support_stats_min_support", 0) or 0), 1)
        support_scores: Dict[str, float] = {}
        for product_id in candidate_product_ids:
            normalized_product_id = str(product_id or "").strip()
            if not normalized_product_id:
                continue
            support_rows = list(self._product_support_by_product.get(normalized_product_id) or [])
            if len(support_rows) < min_support:
                continue

            product_score = self._score_stage2_targeted_support_product(
                query_context,
                support_rows,
                exclude_support_query_image_path=exclude_support_query_image_path,
                top2_weight=getattr(self, "stage2_support_stats_top2_weight", 0.0),
                mean_weight=getattr(self, "stage2_support_stats_mean_weight", 0.0),
            )
            if product_score is None:
                continue
            support_scores[normalized_product_id] = float(product_score)
        return support_scores

    def _build_stage2_query_pair_classifier(
        self,
        pair_key: tuple[str, str],
        prepared_catalog: list[Dict[str, Any]],
        exclude_query_image_path: str = "",
    ):
        sample_map = self._load_stage2_query_pair_samples(prepared_catalog=prepared_catalog)
        samples = list(sample_map.get(pair_key) or [])
        use_catalog_only = bool(
            getattr(self, "stage2_query_pair_catalog_only_enabled", False)
        ) and not samples
        if not samples and not use_catalog_only:
            return None

        if use_catalog_only:
            classifier_cache = self._resolve_stage2_query_pair_catalog_only_classifier_cache(
                prepared_catalog
            )
            cached_classifier = classifier_cache.get(pair_key)
            if cached_classifier is not None:
                return cached_classifier

        query_embeddings = self._get_stage2_query_pair_embeddings(sample_map) if samples else {}
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        query_repeat = max(int(self.stage2_query_pair_query_repeat or 0), 1)
        catalog_repeat = max(int(self.stage2_query_pair_catalog_repeat or 0), 0)
        if use_catalog_only and catalog_repeat <= 0:
            catalog_repeat = 1

        features = []
        labels = []
        excluded_path = str(exclude_query_image_path or "").strip()

        for sample in samples:
            query_image_path = str(sample.get("query_image_path") or "").strip()
            if excluded_path and query_image_path == excluded_path:
                continue
            embedding_payload = query_embeddings.get(query_image_path)
            label = str(sample.get("label") or "").strip()
            if embedding_payload is None or label not in pair_key:
                continue
            feature = self._build_stage2_query_pair_feature(
                embedding_payload,
                pair_key,
                catalog_embeddings_by_product,
            )
            for _ in range(query_repeat):
                features.append(feature)
                labels.append(label)

        if catalog_repeat > 0:
            for product_id in pair_key:
                for entry in prepared_catalog:
                    if str(entry["record"].product_id or "").strip() != product_id:
                        continue
                    pseudo_query_context = self._get_stage2_catalog_query_payload(
                        str(entry["record"].image_path or "").strip(),
                        prepared_catalog,
                        fallback_embedding=entry["context"].get("embedding"),
                    )
                    if pseudo_query_context is None:
                        continue
                    feature = self._build_stage2_query_pair_feature(
                        pseudo_query_context,
                        pair_key,
                        catalog_embeddings_by_product,
                    )
                    for _ in range(catalog_repeat):
                        features.append(feature)
                        labels.append(product_id)

        if len(features) < 2 or len(set(labels)) < 2:
            return None

        try:
            classifier = fit_ridge_classifier(
                features,
                labels,
                alpha=self.stage2_query_pair_alpha,
            )
            if use_catalog_only:
                classifier_cache[pair_key] = classifier
            return classifier
        except Exception as exc:
            logger.warning("SigLIP2 query-pair fit failed for %s/%s: %s", pair_key[0], pair_key[1], exc)
            return None

    def _build_stage2_query_cluster_classifier(
        self,
        cluster_key: tuple[str, ...],
        prepared_catalog: list[Dict[str, Any]],
        exclude_query_image_path: str = "",
    ):
        sample_map = self._load_stage2_query_cluster_samples()
        samples = list(sample_map.get(cluster_key) or [])
        if not samples:
            return None

        query_embeddings = self._get_stage2_query_cluster_embeddings(sample_map)
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        query_repeat = max(int(self.stage2_query_cluster_query_repeat or 0), 1)
        catalog_repeat = max(int(self.stage2_query_cluster_catalog_repeat or 0), 0)

        features = []
        labels = []
        cluster_members = set(cluster_key)
        excluded_path = str(exclude_query_image_path or "").strip()

        for sample in samples:
            query_image_path = str(sample.get("query_image_path") or "").strip()
            if excluded_path and query_image_path == excluded_path:
                continue
            embedding_payload = query_embeddings.get(query_image_path)
            label = str(sample.get("label") or "").strip()
            if embedding_payload is None or label not in cluster_members:
                continue
            feature = self._build_stage2_query_cluster_feature(
                embedding_payload,
                cluster_key,
                catalog_embeddings_by_product,
            )
            for _ in range(query_repeat):
                features.append(feature)
                labels.append(label)

        if catalog_repeat > 0:
            for product_id in cluster_key:
                for embedding in catalog_embeddings_by_product.get(product_id, []):
                    pseudo_query_context = {
                        "embedding": embedding,
                        "raw_embedding": embedding,
                        "center_embedding": None,
                        "yolo_embedding": None,
                    }
                    feature = self._build_stage2_query_cluster_feature(
                        pseudo_query_context,
                        cluster_key,
                        catalog_embeddings_by_product,
                    )
                    for _ in range(catalog_repeat):
                        features.append(feature)
                        labels.append(product_id)

        if len(features) < 2 or len(set(labels)) < 2:
            return None

        try:
            return fit_ridge_classifier(
                features,
                labels,
                alpha=self.stage2_query_cluster_alpha,
            )
        except Exception as exc:
            logger.warning("SigLIP2 query-cluster fit failed for %s: %s", ",".join(cluster_key), exc)
            return None

    def _build_stage2_targeted_cluster_classifier(
        self,
        cluster_key: tuple[str, ...],
        prepared_catalog: list[Dict[str, Any]],
        exclude_query_image_path: str = "",
    ):
        sample_map = self._load_stage2_targeted_cluster_samples()
        samples = list(sample_map.get(cluster_key) or [])
        if not samples:
            return None

        query_embeddings = self._get_stage2_query_cluster_embeddings(sample_map)
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        support_embedding_map = self._build_stage2_targeted_cluster_support_embeddings(sample_map)
        support_embeddings_by_product = self._resolve_support_embeddings_by_product(
            support_embedding_map,
            cluster_key,
        )
        query_repeat = max(int(self.stage2_targeted_cluster_query_repeat or 0), 1)
        catalog_repeat = max(int(self.stage2_targeted_cluster_catalog_repeat or 0), 0)

        features = []
        labels = []
        cluster_members = set(cluster_key)
        excluded_path = str(exclude_query_image_path or "").strip()

        for sample in samples:
            query_image_path = str(sample.get("query_image_path") or "").strip()
            if excluded_path and query_image_path == excluded_path:
                continue
            embedding_payload = query_embeddings.get(query_image_path)
            label = str(sample.get("label") or "").strip()
            if embedding_payload is None or label not in cluster_members:
                continue
            feature = self._build_stage2_targeted_cluster_feature(
                embedding_payload,
                cluster_key,
                catalog_embeddings_by_product,
                support_embeddings_by_product,
                exclude_support_query_image_path=query_image_path,
            )
            for _ in range(query_repeat):
                features.append(feature)
                labels.append(label)

        if catalog_repeat > 0:
            for product_id in cluster_key:
                for embedding in catalog_embeddings_by_product.get(product_id, []):
                    pseudo_query_context = {
                        "embedding": embedding,
                        "raw_embedding": embedding,
                        "center_embedding": None,
                        "yolo_embedding": None,
                    }
                    feature = self._build_stage2_targeted_cluster_feature(
                        pseudo_query_context,
                        cluster_key,
                        catalog_embeddings_by_product,
                        support_embeddings_by_product,
                    )
                    for _ in range(catalog_repeat):
                        features.append(feature)
                        labels.append(product_id)

        if len(features) < 2 or len(set(labels)) < 2:
            return None

        try:
            return fit_ridge_classifier(
                features,
                labels,
                alpha=self.stage2_targeted_cluster_alpha,
            )
        except Exception as exc:
            logger.warning("SigLIP2 targeted-cluster fit failed for %s: %s", ",".join(cluster_key), exc)
            return None

    def _build_stage2_targeted_pair_classifier(
        self,
        pair_key: tuple[str, str],
        prepared_catalog: list[Dict[str, Any]],
        pair_support_embeddings_by_product: Dict[str, list[Dict[str, Any]]],
        exclude_query_image_path: str = "",
    ):
        sample_map = self._load_stage2_targeted_pair_samples()
        samples = list(sample_map.get(pair_key) or [])
        if not samples:
            return None

        query_embeddings = self._get_stage2_query_pair_embeddings(sample_map)
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        should_train, alpha, query_repeat, catalog_repeat = (
            self._resolve_stage2_targeted_pair_train_config(
                pair_key,
                pair_support_embeddings_by_product,
            )
        )
        if not should_train:
            return None

        features = []
        labels = []
        excluded_path = str(exclude_query_image_path or "").strip()

        for sample in samples:
            query_image_path = str(sample.get("query_image_path") or "").strip()
            if excluded_path and query_image_path == excluded_path:
                continue
            embedding_payload = query_embeddings.get(query_image_path)
            label = str(sample.get("label") or "").strip()
            if embedding_payload is None or label not in pair_key:
                continue
            feature = self._build_stage2_targeted_cluster_feature(
                embedding_payload,
                pair_key,
                catalog_embeddings_by_product,
                pair_support_embeddings_by_product,
                exclude_support_query_image_path=query_image_path,
            )
            for _ in range(query_repeat):
                features.append(feature)
                labels.append(label)

        if catalog_repeat > 0:
            for product_id in pair_key:
                for embedding in catalog_embeddings_by_product.get(product_id, []):
                    pseudo_query_context = {
                        "embedding": embedding,
                        "raw_embedding": embedding,
                        "center_embedding": None,
                        "yolo_embedding": None,
                    }
                    feature = self._build_stage2_targeted_cluster_feature(
                        pseudo_query_context,
                        pair_key,
                        catalog_embeddings_by_product,
                        pair_support_embeddings_by_product,
                    )
                    for _ in range(catalog_repeat):
                        features.append(feature)
                        labels.append(product_id)

        if len(features) < 2 or len(set(labels)) < 2:
            return None

        try:
            return fit_ridge_classifier(
                features,
                labels,
                alpha=alpha,
            )
        except Exception as exc:
            logger.warning("SigLIP2 targeted-pair fit failed for %s/%s: %s", pair_key[0], pair_key[1], exc)
            return None

    def _apply_stage2_query_pair_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.stage2_query_pair_enabled or query_context.get("embedding") is None:
            return final_payload

        candidate_prefix = list(final_payload.get("ranked_products", []))[: max(int(self.stage2_candidate_k or 0), 0)]
        if len(candidate_prefix) < 2:
            return final_payload

        candidate_product_ids = [
            str(item.get("product_id") or "").strip()
            for item in candidate_prefix
            if str(item.get("product_id") or "").strip()
        ]
        score_by_product = {
            str(item.get("product_id") or "").strip(): float(item.get("score", 0.0))
            for item in final_payload.get("ranked_products", [])
            if str(item.get("product_id") or "").strip()
        }
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        classifier_map: Dict[tuple[str, str], Dict[str, float]] = {}
        exclude_query_image_path = str(query_context.get("image_path") or "").strip()
        for left_index in range(len(candidate_product_ids)):
            for right_index in range(left_index + 1, len(candidate_product_ids)):
                pair_key = _normalize_product_pair(
                    candidate_product_ids[left_index],
                    candidate_product_ids[right_index],
                )
                if pair_key is None or pair_key in classifier_map:
                    continue
                classifier = self._build_stage2_query_pair_classifier(
                    pair_key,
                    prepared_catalog,
                    exclude_query_image_path=exclude_query_image_path,
                )
                if classifier is None:
                    continue
                feature = self._build_stage2_query_pair_feature(
                    query_context,
                    pair_key,
                    catalog_embeddings_by_product,
                    score_by_product=score_by_product,
                )
                pair_scores = score_ridge_classifier(classifier, feature)
                if pair_key[0] in pair_scores and pair_key[1] in pair_scores:
                    classifier_map[pair_key] = pair_scores

        if not classifier_map:
            return final_payload

        reranked_products = final_payload["ranked_products"]
        if self.stage2_query_pair_swap_enabled:
            directional_rules = self._load_stage2_query_pair_directional_rules()
            if directional_rules:
                reranked_products = rerank_candidate_products_with_directional_pairwise_score_swaps(
                    final_payload["ranked_products"],
                    directional_rules=directional_rules,
                    pairwise_scores=classifier_map,
                    candidate_k=self.stage2_candidate_k,
                    max_score_gap=self.stage2_query_pair_score_gap,
                    pair_margin=self.stage2_query_pair_pair_margin,
                )
            else:
                reranked_products = rerank_candidate_products_with_pairwise_score_swaps(
                    final_payload["ranked_products"],
                    pairwise_scores=classifier_map,
                    candidate_k=self.stage2_candidate_k,
                    max_score_gap=self.stage2_query_pair_score_gap,
                    pair_margin=self.stage2_query_pair_pair_margin,
                )
        if reranked_products != final_payload["ranked_products"]:
            final_payload["ranked_products"] = reranked_products
            final_payload["stage2_query_pair_applied"] = True
        return final_payload

    def _apply_stage2_dynamic_cluster_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if (
            not getattr(self, "stage2_dynamic_cluster_enabled", False)
            or query_context.get("embedding") is None
        ):
            return final_payload

        candidate_prefix = list(final_payload.get("ranked_products", []))[
            : max(int(self.stage2_candidate_k or 0), 0)
        ]
        candidate_product_ids = tuple(
            sorted(
                {
                    str(item.get("product_id") or "").strip()
                    for item in candidate_prefix
                    if str(item.get("product_id") or "").strip()
                }
            )
        )
        if len(candidate_product_ids) < 2:
            return final_payload

        classifier = self._build_stage2_dynamic_cluster_classifier(
            candidate_product_ids,
            prepared_catalog,
        )
        if classifier is None:
            return final_payload

        score_by_product = {
            str(item.get("product_id") or "").strip(): float(item.get("score", 0.0))
            for item in final_payload.get("ranked_products", [])
            if str(item.get("product_id") or "").strip()
        }
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        feature = self._build_stage2_query_cluster_feature(
            query_context,
            candidate_product_ids,
            catalog_embeddings_by_product,
            score_by_product=score_by_product,
        )
        classifier_scores = score_ridge_classifier(classifier, feature)
        if len(set(candidate_product_ids) & set(classifier_scores)) < 2:
            return final_payload

        reranked_products = rerank_candidate_products_with_cluster_classifier_scores(
            final_payload["ranked_products"],
            cluster_product_ids=candidate_product_ids,
            classifier_scores=classifier_scores,
            blend=self.stage2_dynamic_cluster_blend,
            candidate_k=self.stage2_candidate_k,
            max_score_gap=self.stage2_dynamic_cluster_score_gap,
        )
        if reranked_products != final_payload["ranked_products"]:
            final_payload["ranked_products"] = reranked_products
            final_payload["stage2_dynamic_cluster_applied"] = True
        return final_payload

    def _apply_stage2_query_cluster_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.stage2_query_cluster_enabled or query_context.get("embedding") is None:
            return final_payload

        candidate_prefix = list(final_payload.get("ranked_products", []))[
            : max(int(self.stage2_candidate_k or 0), 0)
        ]
        if len(candidate_prefix) < 2:
            return final_payload

        active_product_ids = {
            str(item.get("product_id") or "").strip()
            for item in candidate_prefix
            if str(item.get("product_id") or "").strip()
        }
        if len(active_product_ids) < 2:
            return final_payload

        sample_map = self._load_stage2_query_cluster_samples()
        if not sample_map:
            return final_payload

        score_by_product = {
            str(item.get("product_id") or "").strip(): float(item.get("score", 0.0))
            for item in final_payload.get("ranked_products", [])
            if str(item.get("product_id") or "").strip()
        }
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        exclude_query_image_path = str(query_context.get("image_path") or "").strip()

        reranked_products = final_payload["ranked_products"]
        applied = False
        directional_rule_map = self._load_stage2_targeted_cluster_directional_rules()
        targeted_pair_sample_map = self._load_stage2_targeted_pair_samples()
        targeted_pair_support_embedding_map = self._build_stage2_targeted_pair_support_embeddings(
            targeted_pair_sample_map
        ) if getattr(self, "stage2_targeted_pair_enabled", False) and targeted_pair_sample_map else {}
        for cluster_key in sorted(sample_map, key=lambda key: (-len(key), key)):
            cluster_members = set(cluster_key)
            active_cluster_members = active_product_ids & cluster_members
            if len(active_cluster_members) < 2:
                continue

            classifier = self._build_stage2_query_cluster_classifier(
                cluster_key,
                prepared_catalog,
                exclude_query_image_path=exclude_query_image_path,
            )
            if classifier is None:
                continue

            feature = self._build_stage2_query_cluster_feature(
                query_context,
                cluster_key,
                catalog_embeddings_by_product,
                score_by_product=score_by_product,
            )
            classifier_scores = score_ridge_classifier(classifier, feature)
            if len(active_cluster_members & set(classifier_scores)) < 2:
                continue

            next_ranked_products = rerank_candidate_products_with_cluster_classifier_scores(
                reranked_products,
                cluster_product_ids=cluster_key,
                classifier_scores=classifier_scores,
                blend=self.stage2_query_cluster_blend,
                candidate_k=self.stage2_candidate_k,
                max_score_gap=self.stage2_query_cluster_score_gap,
            )
            if next_ranked_products != reranked_products:
                reranked_products = next_ranked_products
                applied = True

        if applied:
            final_payload["ranked_products"] = reranked_products
            final_payload["stage2_query_cluster_applied"] = True
        return final_payload

    def _apply_stage2_targeted_cluster_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        if not self.stage2_targeted_cluster_enabled or query_context.get("embedding") is None:
            return final_payload

        candidate_prefix = list(final_payload.get("ranked_products", []))[
            : max(int(self.stage2_candidate_k or 0), 0)
        ]
        if len(candidate_prefix) < 2:
            return final_payload

        active_product_ids = {
            str(item.get("product_id") or "").strip()
            for item in candidate_prefix
            if str(item.get("product_id") or "").strip()
        }
        if len(active_product_ids) < 2:
            return final_payload

        sample_map = self._load_stage2_targeted_cluster_samples()
        if not sample_map:
            return final_payload

        score_by_product = {
            str(item.get("product_id") or "").strip(): float(item.get("score", 0.0))
            for item in final_payload.get("ranked_products", [])
            if str(item.get("product_id") or "").strip()
        }
        catalog_embeddings_by_product = self._build_catalog_embeddings_by_product(prepared_catalog)
        support_embedding_map = self._build_stage2_targeted_cluster_support_embeddings(sample_map)
        exclude_query_image_path = str(query_context.get("image_path") or "").strip()

        reranked_products = final_payload["ranked_products"]
        applied = False
        directional_rule_map = self._load_stage2_targeted_cluster_directional_rules()
        targeted_pair_sample_map = self._load_stage2_targeted_pair_samples()
        targeted_pair_support_embedding_map = (
            self._build_stage2_targeted_pair_support_embeddings(targeted_pair_sample_map)
            if getattr(self, "stage2_targeted_pair_enabled", False) and targeted_pair_sample_map
            else {}
        )
        for cluster_key in sorted(sample_map, key=lambda key: (-len(key), key)):
            cluster_members = set(cluster_key)
            active_cluster_members = active_product_ids & cluster_members
            if len(active_cluster_members) < 2:
                continue

            classifier = self._build_stage2_targeted_cluster_classifier(
                cluster_key,
                prepared_catalog,
                exclude_query_image_path=exclude_query_image_path,
            )
            if classifier is None:
                continue

            support_embeddings_by_product = self._resolve_support_embeddings_by_product(
                support_embedding_map,
                cluster_key,
            )
            feature = self._build_stage2_targeted_cluster_feature(
                query_context,
                cluster_key,
                catalog_embeddings_by_product,
                support_embeddings_by_product,
                score_by_product=score_by_product,
                exclude_support_query_image_path=exclude_query_image_path,
            )
            classifier_scores = score_ridge_classifier(classifier, feature)
            if len(active_cluster_members & set(classifier_scores)) < 2:
                continue

            directional_rules = tuple(directional_rule_map.get(cluster_key) or ())
            if getattr(self, "stage2_targeted_pair_enabled", False) and directional_rules:
                pairwise_scores: Dict[tuple[str, str], Dict[str, float]] = {}
                for preferred_product_id, mistaken_product_id in directional_rules:
                    pair_key = _normalize_product_pair(preferred_product_id, mistaken_product_id)
                    if pair_key is None or pair_key not in targeted_pair_sample_map:
                        continue
                    pair_support_embeddings_by_product = self._resolve_support_embeddings_by_product(
                        targeted_pair_support_embedding_map,
                        pair_key,
                    )
                    pair_classifier = self._build_stage2_targeted_pair_classifier(
                        pair_key,
                        prepared_catalog,
                        pair_support_embeddings_by_product,
                        exclude_query_image_path=exclude_query_image_path,
                    )
                    if pair_classifier is None:
                        continue
                    pair_feature = self._build_stage2_targeted_cluster_feature(
                        query_context,
                        pair_key,
                        catalog_embeddings_by_product,
                        pair_support_embeddings_by_product,
                        score_by_product=score_by_product,
                        exclude_support_query_image_path=exclude_query_image_path,
                    )
                    pair_scores = score_ridge_classifier(pair_classifier, pair_feature)
                    if pair_key[0] in pair_scores and pair_key[1] in pair_scores:
                        pairwise_scores[pair_key] = pair_scores

                if pairwise_scores:
                    next_ranked_products = rerank_candidate_products_with_directional_pairwise_score_swaps(
                        reranked_products,
                        directional_rules=directional_rules,
                        pairwise_scores=pairwise_scores,
                        candidate_k=self.stage2_candidate_k,
                        max_score_gap=getattr(self, "stage2_targeted_pair_score_gap", 0.06),
                        pair_margin=getattr(self, "stage2_targeted_pair_pair_margin", 0.01),
                    )
                    if next_ranked_products != reranked_products:
                        reranked_products = next_ranked_products
                        applied = True
                        final_payload["stage2_targeted_pair_applied"] = True
                    continue

            if directional_rules:
                next_ranked_products = rerank_candidate_products_with_directional_classifier_score_swaps(
                    reranked_products,
                    directional_rules=directional_rules,
                    classifier_scores=classifier_scores,
                    candidate_k=self.stage2_candidate_k,
                    max_score_gap=self.stage2_targeted_cluster_score_gap,
                    classifier_margin=getattr(self, "stage2_targeted_cluster_pair_margin", 0.01),
                )
            else:
                next_ranked_products = rerank_candidate_products_with_cluster_classifier_scores(
                    reranked_products,
                    cluster_product_ids=cluster_key,
                    classifier_scores=classifier_scores,
                    blend=self.stage2_targeted_cluster_blend,
                    candidate_k=self.stage2_candidate_k,
                    max_score_gap=self.stage2_targeted_cluster_score_gap,
                )
            if next_ranked_products != reranked_products:
                reranked_products = next_ranked_products
                applied = True

        if applied:
            final_payload["ranked_products"] = reranked_products
            final_payload["stage2_targeted_cluster_applied"] = True
        return final_payload

    def _apply_stage2_targeted_support_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        del prepared_catalog
        if (
            not getattr(self, "stage2_targeted_support_enabled", False)
            or query_context.get("embedding") is None
        ):
            return final_payload

        candidate_prefix = list(final_payload.get("ranked_products", []))[
            : max(int(self.stage2_candidate_k or 0), 0)
        ]
        if len(candidate_prefix) < 2:
            return final_payload

        active_product_ids = {
            str(item.get("product_id") or "").strip()
            for item in candidate_prefix
            if str(item.get("product_id") or "").strip()
        }
        if len(active_product_ids) < 2:
            return final_payload

        sample_map = self._load_stage2_targeted_cluster_samples()
        if not sample_map:
            return final_payload

        support_embedding_map = self._build_stage2_targeted_cluster_support_embeddings(sample_map)
        exclude_query_image_path = str(query_context.get("image_path") or "").strip()

        reranked_products = final_payload["ranked_products"]
        applied = False
        for cluster_key in sorted(sample_map, key=lambda key: (-len(key), key)):
            cluster_members = set(cluster_key)
            active_cluster_members = active_product_ids & cluster_members
            if len(active_cluster_members) < 2:
                continue

            support_embeddings_by_product = self._resolve_support_embeddings_by_product(
                support_embedding_map,
                cluster_key,
            )
            support_scores = self._build_stage2_targeted_support_scores(
                query_context,
                cluster_key,
                support_embeddings_by_product,
                exclude_support_query_image_path=exclude_query_image_path,
            )
            if len(active_cluster_members & set(support_scores)) < 2:
                continue

            next_ranked_products = rerank_candidate_products_with_cluster_classifier_scores(
                reranked_products,
                cluster_product_ids=cluster_key,
                classifier_scores=support_scores,
                blend=self.stage2_targeted_support_blend,
                candidate_k=self.stage2_candidate_k,
                max_score_gap=self.stage2_targeted_support_score_gap,
            )
            if next_ranked_products != reranked_products:
                reranked_products = next_ranked_products
                applied = True

        if applied:
            final_payload["ranked_products"] = reranked_products
            final_payload["stage2_targeted_support_applied"] = True
        return final_payload

    def _apply_stage2_support_stats_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
    ) -> Dict[str, Any]:
        if (
            not getattr(self, "stage2_support_stats_enabled", False)
            or not self._product_support_by_product
        ):
            return final_payload

        ranked_products = list(final_payload.get("ranked_products", []))
        if len(ranked_products) < 2:
            return final_payload

        candidate_product_ids = [
            str(item.get("product_id") or "").strip()
            for item in ranked_products[: max(int(self.stage2_candidate_k or 0), 0)]
            if str(item.get("product_id") or "").strip()
        ]
        if len(candidate_product_ids) < 2:
            return final_payload

        support_scores = self._build_stage2_support_stats_scores(
            query_context,
            candidate_product_ids,
            exclude_support_query_image_path=str(query_context.get("image_path") or "").strip(),
        )
        if len(support_scores) < 2:
            return final_payload

        reranked_products = rerank_candidate_products_with_cluster_classifier_scores(
            ranked_products,
            cluster_product_ids=candidate_product_ids,
            classifier_scores=support_scores,
            blend=self.stage2_support_stats_blend,
            candidate_k=self.stage2_candidate_k,
            max_score_gap=self.stage2_support_stats_score_gap,
        )
        if reranked_products != ranked_products:
            final_payload["ranked_products"] = reranked_products
            final_payload["stage2_support_stats_applied"] = True
        return final_payload

    def _apply_stage2_ridge_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        classifier = self._get_stage2_classifier(prepared_catalog)
        if classifier is None or query_context.get("embedding") is None:
            return final_payload

        final_payload["ranked_products"] = rerank_candidate_products_with_classifier(
            final_payload["ranked_products"],
            classifier_scores=score_ridge_classifier(
                classifier,
                query_context["embedding"],
            ),
            blend=self.stage2_ridge_blend,
            candidate_k=self.stage2_candidate_k,
        )
        final_payload["stage2_ridge_applied"] = True
        return final_payload

    def _apply_stage2_hard_negative_rerank(
        self,
        final_payload: Dict[str, Any],
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
    ) -> Dict[str, Any]:
        directional_rules = self._load_stage2_hard_negative_rules()
        pairwise_classifiers = self._get_stage2_pairwise_classifiers(prepared_catalog)
        if (
            not directional_rules
            or not pairwise_classifiers
            or query_context.get("embedding") is None
        ):
            return final_payload

        reranked_products = rerank_candidate_products_with_pairwise_classifiers(
            final_payload["ranked_products"],
            pairwise_classifiers=pairwise_classifiers,
            query_feature=query_context["embedding"],
            blend=self.stage2_hard_negative_blend,
            candidate_k=self.stage2_candidate_k,
            max_score_gap=self.stage2_hard_negative_score_gap,
        )
        if reranked_products != final_payload["ranked_products"]:
            final_payload["ranked_products"] = reranked_products
            final_payload["stage2_hard_negative_applied"] = True
        return final_payload

    def rank_products(
        self,
        query_context: Dict[str, Any],
        prepared_catalog: list[Dict[str, Any]],
        top_k: int = 10,
    ) -> Dict[str, Any]:
        max_top_k = max(int(top_k or 1), 1)
        default_ranked_products = aggregate_product_rankings(
            self._build_image_rankings_for_query_context(query_context, prepared_catalog),
            top_k=max_top_k,
        )
        final_payload: Dict[str, Any] = {
            "ranked_products": default_ranked_products,
        }

        if not self.adaptive_raw_center_enabled:
            final_payload = self._apply_stage2_ridge_rerank(
                final_payload,
                query_context,
                prepared_catalog,
            )
            final_payload = self._apply_stage2_hard_negative_rerank(
                final_payload,
                query_context,
                prepared_catalog,
            )
            final_payload = self._apply_stage2_support_stats_rerank(
                final_payload,
                query_context,
            )
            final_payload = self._apply_stage2_query_pair_rerank(
                final_payload,
                query_context,
                prepared_catalog,
            )
            final_payload = self._apply_stage2_dynamic_cluster_rerank(
                final_payload,
                query_context,
                prepared_catalog,
            )
            final_payload = self._apply_stage2_query_cluster_rerank(
                final_payload,
                query_context,
                prepared_catalog,
            )
            final_payload = self._apply_stage2_targeted_support_rerank(
                final_payload,
                query_context,
                prepared_catalog,
            )
            final_payload = self._apply_stage2_targeted_cluster_rerank(
                final_payload,
                query_context,
                prepared_catalog,
            )
            return final_payload

        if self.query_fusion_enabled:
            raw_embedding = query_context.get("raw_embedding")
            default_embedding = query_context.get("embedding")
            if (
                raw_embedding is not None
                and default_embedding is not None
                and self.query_raw_weight > 0
                and (self.query_center_weight > 0 or self.query_yolo_weight > 0)
            ):
                raw_query_context = dict(query_context)
                raw_query_context["embedding"] = raw_embedding
                raw_ranked_products = aggregate_product_rankings(
                    self._build_image_rankings_for_query_context(raw_query_context, prepared_catalog),
                    top_k=max_top_k,
                )
                selected_variant, selected_ranked_products = select_query_variant_rankings(
                    {
                        "main": final_payload["ranked_products"],
                        "raw": raw_ranked_products,
                    },
                    default_variant="main",
                    challenger_variant="raw",
                    challenger_min_delta=self.adaptive_raw_delta,
                )
                final_payload["ranked_products"] = selected_ranked_products
                final_payload["selected_query_variant"] = selected_variant

        final_payload = self._apply_stage2_ridge_rerank(
            final_payload,
            query_context,
            prepared_catalog,
        )
        final_payload = self._apply_stage2_hard_negative_rerank(
            final_payload,
            query_context,
            prepared_catalog,
        )
        final_payload = self._apply_stage2_query_pair_rerank(
            final_payload,
            query_context,
            prepared_catalog,
        )
        final_payload = self._apply_stage2_dynamic_cluster_rerank(
            final_payload,
            query_context,
            prepared_catalog,
        )
        final_payload = self._apply_stage2_query_cluster_rerank(
            final_payload,
            query_context,
            prepared_catalog,
        )
        final_payload = self._apply_stage2_targeted_support_rerank(
            final_payload,
            query_context,
            prepared_catalog,
        )
        final_payload = self._apply_stage2_targeted_cluster_rerank(
            final_payload,
            query_context,
            prepared_catalog,
        )
        return final_payload

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0

        image_weight = float(getattr(self, "image_weight", 0.74))
        color_weight = float(getattr(self, "color_weight", 0.11))
        text_weight = float(getattr(self, "text_weight", 0.15))
        category_weight = float(getattr(self, "category_weight", 0.0))
        bonus_score = float(getattr(self, "bonus_score", 0.05))
        bonus_text_gate = float(getattr(self, "bonus_text_gate", 0.5))
        bonus_image_gate = float(getattr(self, "bonus_image_gate", 0.5))

        image_score = float(np.dot(query_embedding, catalog_embedding))
        weighted_scores = [(image_weight, image_score)]
        query_hist = query_context.get("hist")
        catalog_hist = catalog_context.get("hist")
        if query_hist is not None and catalog_hist is not None and color_weight > 0:
            color_score = max(0.0, float(cv2.compareHist(query_hist, catalog_hist, cv2.HISTCMP_CORREL)))
            weighted_scores.append((color_weight, color_score))

        text_score = 0.0
        query_tokens = query_context.get("tokens")
        catalog_tokens = catalog_context.get("tokens")
        if query_tokens and catalog_tokens and text_weight > 0:
            text_score = self._text_overlap(query_tokens, catalog_tokens)
            weighted_scores.append((text_weight, text_score))

        query_category = str(query_context.get("category") or "").strip()
        catalog_category = str(catalog_context.get("category") or "").strip()
        if query_category and catalog_category and category_weight > 0:
            category_score = 1.0 if query_category == catalog_category else 0.0
            weighted_scores.append((category_weight, category_score))

        total_weight = sum(weight for weight, _score in weighted_scores)
        if total_weight <= 0:
            return 0.0

        final_score = sum(weight * score for weight, score in weighted_scores) / total_weight
        if (
            len(weighted_scores) >= 3
            and text_score > bonus_text_gate
            and image_score > bonus_image_gate
        ):
            final_score += bonus_score
        return float(min(final_score, 1.0))


STRATEGY_REGISTRY: Dict[str, Type] = {
    CurrentDinoHybridStrategy.name: CurrentDinoHybridStrategy,
    FashionSiglipStrategy.name: FashionSiglipStrategy,
    MarqoFashionClipStrategy.name: MarqoFashionClipStrategy,
    GroundingSiglip2Strategy.name: GroundingSiglip2Strategy,
    Siglip2Strategy.name: Siglip2Strategy,
    Siglip2RerankStrategy.name: Siglip2RerankStrategy,
    Siglip2CenterCropStrategy.name: Siglip2CenterCropStrategy,
    Siglip2YoloCropStrategy.name: Siglip2YoloCropStrategy,
    Siglip2QueryFusionStrategy.name: Siglip2QueryFusionStrategy,
}


def get_strategy_cls(name: str):
    if name not in STRATEGY_REGISTRY:
        available = ", ".join(sorted(STRATEGY_REGISTRY))
        raise KeyError(f"unknown strategy '{name}', available: {available}")
    return STRATEGY_REGISTRY[name]


def create_strategy(name: str):
    return get_strategy_cls(name)()
