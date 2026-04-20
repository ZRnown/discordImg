import json
import sys
import types

import numpy as np
import pytest
from PIL import Image

from backend.benchmarks.strategies import Siglip2RerankStrategy, _Siglip2Encoder
from backend.config import config as backend_config
from backend.live_retrieval import LiveCatalogImageRecord
from backend.benchmarks.strategies import get_strategy_cls


def test_get_strategy_cls_returns_current_baseline():
    strategy_cls = get_strategy_cls("current_dino_hybrid")
    assert strategy_cls.name == "current_dino_hybrid"


@pytest.mark.parametrize(
    ("strategy_name", "expected_name"),
    [
        ("fashion_siglip", "fashion_siglip"),
        ("marqo_fashionclip", "marqo_fashionclip"),
        ("grounding_siglip2", "grounding_siglip2"),
        ("siglip2_base", "siglip2_base"),
        ("siglip2_rerank", "siglip2_rerank"),
        ("siglip2_center_crop", "siglip2_center_crop"),
        ("siglip2_yolo_crop", "siglip2_yolo_crop"),
        ("siglip2_query_fusion", "siglip2_query_fusion"),
    ],
)
def test_get_strategy_cls_returns_expected_strategy(strategy_name, expected_name):
    strategy_cls = get_strategy_cls(strategy_name)
    assert strategy_cls.name == expected_name


def test_get_strategy_cls_rejects_unknown_name():
    with pytest.raises(KeyError):
        get_strategy_cls("missing")


def test_siglip2_rerank_prepare_catalog_image_uses_cached_payload():
    strategy = object.__new__(Siglip2RerankStrategy)

    class GuardEncoder:
        def encode_image(self, *_args, **_kwargs):
            raise AssertionError("should not encode catalog image when cache is present")

    def fail_hist(_image_path):
        raise AssertionError("should not build color hist when cache is present")

    def fail_tokenize(*_values):
        raise AssertionError("should not tokenize when cache is present")

    strategy.encoder = GuardEncoder()
    strategy._build_color_hist = fail_hist
    strategy._tokenize = fail_tokenize

    record = LiveCatalogImageRecord(
        product_id="1001",
        title="Alpha Runner",
        english_title="",
        description="",
        shop_name="shop-a",
        image_path="/tmp/a-1.jpg",
        image_index=0,
        cache_embedding=[0.1, 0.2, 0.3],
        cache_color_hist=[0.4, 0.5, 0.6, 0.7],
        cache_tokens=["alpha", "runner"],
    )

    context = strategy.prepare_catalog_image(record)

    expected = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    expected = expected / np.linalg.norm(expected)
    assert np.allclose(context["embedding"], expected)
    assert context["tokens"] == {"alpha", "runner"}


def test_siglip2_rerank_prepare_catalog_image_reshapes_cached_histogram():
    strategy = object.__new__(Siglip2RerankStrategy)

    class GuardEncoder:
        def encode_image(self, *_args, **_kwargs):
            raise AssertionError("should not encode catalog image when cache is present")

    def fail_hist(_image_path):
        raise AssertionError("should not build color hist when cache is present")

    strategy.encoder = GuardEncoder()
    strategy._build_color_hist = fail_hist
    strategy._tokenize = lambda *_args, **_kwargs: {"alpha"}

    record = LiveCatalogImageRecord(
        product_id="1001",
        title="Alpha Runner",
        english_title="",
        description="",
        shop_name="shop-a",
        image_path="/tmp/a-1.jpg",
        image_index=0,
        cache_embedding=[0.1, 0.2, 0.3],
        cache_color_hist=list(range(72)),
        cache_tokens=["alpha", "runner"],
    )

    context = strategy.prepare_catalog_image(record)

    assert context["hist"].shape == (18, 4)


def test_siglip2_rerank_prepare_catalog_image_compacts_oversized_flattened_cache_embedding():
    strategy = object.__new__(Siglip2RerankStrategy)

    class GuardEncoder:
        output_dim = 768

        def encode_image(self, *_args, **_kwargs):
            raise AssertionError("should not encode catalog image when cache is present")

    strategy.encoder = GuardEncoder()
    strategy._build_color_hist = lambda *_args, **_kwargs: None
    strategy._tokenize = lambda *_args, **_kwargs: {"pony", "sweatpants"}

    oversized_embedding = ([1.0] * 768) + ([3.0] * 768)
    record = LiveCatalogImageRecord(
        product_id="1001",
        title="Pony sweatpants",
        english_title="",
        description="",
        shop_name="shop-a",
        image_path="/tmp/a-1.jpg",
        image_index=0,
        cache_embedding=oversized_embedding,
        cache_color_hist=None,
        cache_tokens=["pony", "sweatpants"],
    )

    context = strategy.prepare_catalog_image(record)

    assert context["embedding"].shape == (768,)
    assert np.linalg.norm(context["embedding"]) == pytest.approx(1.0, abs=1e-6)


def test_siglip2_encoder_normalizes_extreme_image_sizes():
    tiny = Image.new("RGB", (1, 1), color=(12, 34, 56))
    normalized_tiny = _Siglip2Encoder._normalize_image_for_inference(tiny)

    large = Image.new("RGB", (4096, 2048), color=(12, 34, 56))
    normalized_large = _Siglip2Encoder._normalize_image_for_inference(large)

    assert min(normalized_tiny.size) >= 32
    assert max(normalized_large.size) <= 448


def test_siglip2_encoder_loads_cpu_model_without_device_move(monkeypatch):
    from transformers import AutoModel, AutoProcessor

    fake_torch = types.SimpleNamespace(
        device=lambda value: types.SimpleNamespace(type=str(value)),
        float32="float32",
    )
    fake_feature_extractor = types.SimpleNamespace(get_feature_extractor=lambda: object())
    dummy_model = types.SimpleNamespace(
        config=types.SimpleNamespace(projection_dim=768, hidden_size=768),
        eval=lambda: None,
        parameters=lambda: (),
        to=lambda device: (_ for _ in ()).throw(AssertionError("cpu model should not be moved")),
    )
    captured = {}

    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "backend.feature_extractor", fake_feature_extractor)
    monkeypatch.setitem(sys.modules, "feature_extractor", fake_feature_extractor)
    monkeypatch.setattr(backend_config, "DEVICE", "cpu", raising=False)
    monkeypatch.setattr(
        "backend.benchmarks.strategies.inspect.signature",
        lambda _func: types.SimpleNamespace(
            parameters={
                "low_cpu_mem_usage": None,
                "torch_dtype": None,
                "device_map": None,
                "use_safetensors": None,
            }
        ),
    )
    monkeypatch.setattr(AutoProcessor, "from_pretrained", lambda *args, **kwargs: object())

    def fake_from_pretrained(model_name, **kwargs):
        captured["kwargs"] = kwargs
        return dummy_model

    monkeypatch.setattr(AutoModel, "from_pretrained", fake_from_pretrained)

    encoder = _Siglip2Encoder()

    assert encoder.model is dummy_model
    assert captured["kwargs"]["low_cpu_mem_usage"] is False
    assert captured["kwargs"]["device_map"] is None


def test_siglip2_rerank_score_without_text_renormalizes_available_modalities():
    strategy = object.__new__(Siglip2RerankStrategy)
    hist = np.ones((18, 4), dtype=np.float32)

    score = strategy.score(
        query_context={
            "embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "hist": hist,
            "tokens": set(),
        },
        catalog_context={
            "embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "hist": hist.copy(),
            "tokens": {"alpha", "runner"},
        },
    )

    assert score == pytest.approx(1.0, abs=1e-6)


def test_siglip2_rerank_score_skips_zero_weight_modalities(monkeypatch):
    strategy = object.__new__(Siglip2RerankStrategy)
    strategy.image_weight = 1.0
    strategy.color_weight = 0.0
    strategy.text_weight = 0.0
    strategy.bonus_score = 0.0
    strategy.bonus_text_gate = 0.5
    strategy.bonus_image_gate = 0.5
    strategy._text_overlap = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("should not compute text overlap when text_weight is zero")
    )

    monkeypatch.setattr(
        "backend.benchmarks.strategies.cv2.compareHist",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("should not compare hist when color_weight is zero")
        ),
    )

    score = strategy.score(
        query_context={
            "embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "hist": np.ones((18, 4), dtype=np.float32),
            "tokens": {"alpha"},
        },
        catalog_context={
            "embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "hist": np.ones((18, 4), dtype=np.float32),
            "tokens": {"alpha"},
        },
    )

    assert score == pytest.approx(1.0, abs=1e-6)


def test_siglip2_rerank_rank_products_skips_raw_variant_when_raw_weight_is_zero(monkeypatch):
    strategy = object.__new__(Siglip2RerankStrategy)
    strategy.query_fusion_enabled = True
    strategy.query_raw_weight = 0.0
    strategy.query_center_weight = 1.0
    strategy.query_yolo_weight = 0.0
    strategy.adaptive_raw_center_enabled = True
    strategy.adaptive_raw_delta = 0.05
    strategy._apply_stage2_ridge_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._apply_stage2_hard_negative_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._apply_stage2_support_stats_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._apply_stage2_query_pair_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._apply_stage2_dynamic_cluster_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._apply_stage2_query_cluster_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._apply_stage2_targeted_support_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._apply_stage2_targeted_cluster_rerank = lambda payload, *_args, **_kwargs: payload
    strategy._build_image_rankings_for_query_context = lambda query_context, prepared_catalog: [
        {
            "product_id": "1001",
            "title": "Alpha Runner",
            "score": float(query_context["embedding"][0]),
            "image_path": "/tmp/a-1.jpg",
            "image_index": 0,
        }
    ]

    monkeypatch.setattr(
        "backend.benchmarks.strategies.select_query_variant_rankings",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("should not compare raw variant when raw weight is zero")
        ),
    )

    result = strategy.rank_products(
        query_context={
            "embedding": np.array([0.8, 0.0, 0.0], dtype=np.float32),
            "raw_embedding": np.array([1.0, 0.0, 0.0], dtype=np.float32),
            "center_embedding": np.array([0.8, 0.0, 0.0], dtype=np.float32),
            "yolo_embedding": None,
        },
        prepared_catalog=[
            LiveCatalogImageRecord(
                product_id="1001",
                title="Alpha Runner",
                english_title="",
                description="",
                shop_name="shop-a",
                image_path="/tmp/a-1.jpg",
                image_index=0,
            )
        ],
        top_k=1,
    )

    assert result["ranked_products"][0]["product_id"] == "1001"
    assert "selected_query_variant" not in result


def test_siglip2_rerank_resolves_best_stage2_report_from_glob(tmp_path):
    low_quality_path = tmp_path / "low.json"
    high_quality_path = tmp_path / "high.json"
    low_quality_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "expected_product_id": "916",
                        "ranked_products": [{"product_id": "920"}],
                    }
                ],
                "metrics": {"hit_at_1": 0.2},
            }
        ),
        encoding="utf-8",
    )
    high_quality_path.write_text(
        json.dumps(
            {
                "results": [
                    {
                        "expected_product_id": "916",
                        "ranked_products": [{"product_id": "916"}],
                    }
                ],
                "metrics": {"hit_at_1": 0.8},
            }
        ),
        encoding="utf-8",
    )

    resolved_path = Siglip2RerankStrategy._resolve_stage2_hard_negative_report_path(
        "",
        auto_enabled=True,
        auto_glob=str(tmp_path / "*.json"),
    )

    assert resolved_path == str(high_quality_path)


def test_siglip2_rerank_stage2_query_payload_cache_evicts_old_entries():
    strategy = object.__new__(Siglip2RerankStrategy)
    strategy.query_fusion_enabled = True
    strategy.query_raw_weight = 0.0
    strategy.query_center_weight = 1.0
    strategy.query_yolo_weight = 0.0
    strategy.stage2_catalog_query_payload_cache_limit = 2
    strategy._stage2_catalog_query_payload_signature = None
    strategy._stage2_catalog_query_payload_cache = {}
    strategy._build_catalog_signature = lambda _prepared_catalog: ("catalog-v1",)
    strategy._build_query_embedding_payload = lambda image_path: {
        "embedding": np.array([1.0], dtype=np.float32),
        "raw_embedding": np.array([0.1], dtype=np.float32),
        "center_embedding": np.array([0.2], dtype=np.float32),
        "yolo_embedding": None,
        "image_path": image_path,
    }

    prepared_catalog = []

    strategy._get_stage2_catalog_query_payload("/tmp/query-a.jpg", prepared_catalog)
    strategy._get_stage2_catalog_query_payload("/tmp/query-b.jpg", prepared_catalog)
    strategy._get_stage2_catalog_query_payload("/tmp/query-c.jpg", prepared_catalog)

    cache = strategy._stage2_catalog_query_payload_cache
    assert list(cache.keys()) == ["/tmp/query-b.jpg", "/tmp/query-c.jpg"]
