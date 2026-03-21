import pytest

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
