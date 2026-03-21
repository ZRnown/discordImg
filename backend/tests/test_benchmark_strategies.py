import numpy as np
import pytest

from backend.benchmarks.strategies import Siglip2RerankStrategy
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
