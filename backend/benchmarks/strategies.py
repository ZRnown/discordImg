from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional, Type

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

_GENERIC_TOKENS = {
    "shoe", "shoes", "sneaker", "sneakers", "jacket", "jackets", "hoodie", "hoodies",
    "sweater", "shirt", "shirts", "short", "shorts", "bag", "bags", "watch", "watches",
    "long", "sleeve", "sleeves", "cardigan", "coat", "pants", "jeans", "denim", "stand",
    "collar", "hot", "step",
}


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

        self.processor = AutoProcessor.from_pretrained(self.model_id)
        self.model = AutoModel.from_pretrained(self.model_id)
        self.model.to(self.device)
        self.model.eval()

        try:
            self.cropper = get_feature_extractor()
        except Exception as exc:
            logger.warning("SigLIP2 crop helper unavailable: %s", exc)
            self.cropper = None

    @staticmethod
    def _fallback_center_crop(image: Image.Image) -> Image.Image:
        width, height = image.size
        left = int(width * 0.1)
        top = int(height * 0.1)
        right = int(width * 0.9)
        bottom = int(height * 0.9)
        return image.crop((left, top, right, bottom))

    def _prepare_image(self, image_path: str, crop_mode: str) -> Image.Image:
        image = Image.open(image_path).convert("RGB")

        if crop_mode == "raw":
            return image

        if crop_mode == "center":
            if self.cropper is not None and hasattr(self.cropper, "_center_crop"):
                return self.cropper._center_crop(image)
            return self._fallback_center_crop(image)

        if crop_mode == "yolo":
            if self.cropper is not None and hasattr(self.cropper, "_crop_main_object"):
                return self.cropper._crop_main_object(image_path)
            return self._fallback_center_crop(image)

        raise ValueError(f"unsupported crop_mode: {crop_mode}")

    def encode_image(self, image_path: str, crop_mode: str = "raw") -> Optional[np.ndarray]:
        try:
            image = self._prepare_image(image_path, crop_mode=crop_mode)
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
                    features = getattr(outputs, "pooler_output", None)
                    if features is None:
                        features = outputs.last_hidden_state.mean(dim=1)
            return _normalize_embedding(features[0].detach().cpu().numpy())
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
            return _normalize_embedding(features[0].detach().cpu().numpy())
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
    def _deserialize_cached_hist(raw_hist) -> Optional[np.ndarray]:
        if raw_hist is None:
            return None
        hist = np.array(raw_hist, dtype=np.float32).flatten()
        if hist.size == 0:
            return None
        if hist.size == 72:
            hist = hist.reshape((18, 4))
        return hist

    def build_catalog_cache_payload(self, record) -> Dict[str, Any]:
        embedding = self.encoder.encode_image(record.image_path, crop_mode="raw")
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
        cached_embedding = _normalize_embedding(getattr(record, "cache_embedding", None))
        cached_hist = self._deserialize_cached_hist(getattr(record, "cache_color_hist", None))
        cached_tokens = set(getattr(record, "cache_tokens", []) or [])

        return {
            "image_path": record.image_path,
            "embedding": cached_embedding if cached_embedding is not None else self.encoder.encode_image(record.image_path, crop_mode="raw"),
            "hist": cached_hist if cached_hist is not None else self._build_color_hist(record.image_path),
            "tokens": cached_tokens if cached_tokens else self._tokenize(record.title, " ".join(record.queries)),
        }

    def prepare_query_image(self, record) -> Dict[str, Any]:
        return {
            "image_path": record.image_path,
            "embedding": self.encoder.encode_image(record.image_path, crop_mode="raw"),
            "hist": self._build_color_hist(record.image_path),
            "tokens": self._tokenize(record.query, " ".join(record.product_queries)),
        }

    def score(self, query_context: Dict[str, Any], catalog_context: Dict[str, Any]) -> float:
        query_embedding = query_context.get("embedding")
        catalog_embedding = catalog_context.get("embedding")
        if query_embedding is None or catalog_embedding is None:
            return 0.0

        image_score = float(np.dot(query_embedding, catalog_embedding))
        weighted_scores = [(0.74, image_score)]
        query_hist = query_context.get("hist")
        catalog_hist = catalog_context.get("hist")
        if query_hist is not None and catalog_hist is not None:
            color_score = max(0.0, float(cv2.compareHist(query_hist, catalog_hist, cv2.HISTCMP_CORREL)))
            weighted_scores.append((0.11, color_score))

        text_score = self._text_overlap(query_context.get("tokens"), catalog_context.get("tokens"))
        if query_context.get("tokens") and catalog_context.get("tokens"):
            weighted_scores.append((0.15, text_score))

        total_weight = sum(weight for weight, _score in weighted_scores)
        if total_weight <= 0:
            return 0.0

        final_score = sum(weight * score for weight, score in weighted_scores) / total_weight
        if len(weighted_scores) >= 3 and text_score > 0.5 and image_score > 0.5:
            final_score += 0.05
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
