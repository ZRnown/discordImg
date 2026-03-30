import io
from pathlib import Path

import requests
from PIL import Image

from backend import app as app_module
import live_retrieval


def _make_jpeg_bytes(color=(255, 0, 0)):
    buf = io.BytesIO()
    Image.new("RGB", (96, 96), color=color).save(buf, format="JPEG")
    return buf.getvalue()


class DummyUpload:
    def __init__(self, payload: bytes):
        self.payload = payload

    def save(self, path):
        Path(path).write_bytes(self.payload)


def test_schedule_external_product_support_refresh_runs_background_refresh(monkeypatch):
    calls = []

    monkeypatch.setenv("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_ENABLED", "1")
    monkeypatch.setenv("LIVE_IMAGE_SEARCH_EXTERNAL_PRODUCT_SUPPORT_REFRESH_ON_UPLOAD", "1")
    monkeypatch.setattr(
        app_module,
        "_refresh_external_support_for_product",
        lambda product_id, reason="upload": calls.append((str(product_id), reason)),
        raising=False,
    )

    class ImmediateThread:
        def __init__(self, target, name=None, daemon=None):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(app_module.threading, "Thread", ImmediateThread)

    inflight = getattr(app_module, "_external_support_refresh_inflight", None)
    if inflight is not None:
        inflight.clear()

    scheduled = app_module.schedule_external_product_support_refresh("916", reason="image_upload")

    assert scheduled is True
    assert calls == [("916", "image_upload")]
    assert "916" not in app_module._external_support_refresh_inflight


def test_process_and_save_image_core_triggers_external_support_refresh(monkeypatch, tmp_path):
    refresh_calls = []

    monkeypatch.setattr(app_module.config, "IMAGE_SAVE_DIR", str(tmp_path))
    monkeypatch.setattr(
        app_module.db,
        "_get_product_info_by_id",
        lambda product_id: {"id": str(product_id), "title": "Alpha Runner"},
    )
    monkeypatch.setattr(
        live_retrieval,
        "build_product_image_retrieval_cache_payload",
        lambda strategy_name, product_row, image_path, image_index: {
            "cache_version": "siglip2_rerank_v1",
            "embedding": [1.0, 0.0, 0.0],
            "color_hist": [0.1, 0.2, 0.3],
            "tokens": ["alpha", "runner"],
        },
    )
    monkeypatch.setattr(app_module.db, "insert_image_record", lambda product_id, save_path, index: 123)
    monkeypatch.setattr(app_module.db, "upsert_product_image_retrieval_cache", lambda **kwargs: True)
    monkeypatch.setattr(app_module, "invalidate_product_retrieval_runtime", lambda strategy_name=None: None)
    monkeypatch.setattr(
        app_module,
        "schedule_external_product_support_refresh",
        lambda product_id, reason="upload": refresh_calls.append((str(product_id), reason)) or True,
        raising=False,
    )

    result = app_module.process_and_save_image_core(
        "916",
        DummyUpload(_make_jpeg_bytes()),
        0,
        existing_features=[],
    )

    assert result["success"] is True
    assert refresh_calls == [("916", "image_upload")]


def test_save_product_images_unified_triggers_external_support_refresh(monkeypatch, tmp_path):
    refresh_calls = []

    class DummyResponse:
        status_code = 200
        content = _make_jpeg_bytes(color=(0, 255, 0))

    monkeypatch.setattr(app_module.config, "IMAGE_SAVE_DIR", str(tmp_path))
    monkeypatch.setattr(app_module.config, "DOWNLOAD_THREADS", 1)
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: DummyResponse())
    monkeypatch.setattr(app_module.db, "get_product_images", lambda product_id: [])
    monkeypatch.setattr(
        app_module.db,
        "get_product_image_retrieval_embeddings",
        lambda product_id, strategy_name: [],
    )
    monkeypatch.setattr(
        app_module.db,
        "_get_product_info_by_id",
        lambda product_id: {"id": str(product_id), "title": "Alpha Runner"},
    )
    monkeypatch.setattr(
        live_retrieval,
        "build_product_image_retrieval_cache_payload",
        lambda strategy_name, product_row, image_path, image_index: {
            "cache_version": "siglip2_rerank_v1",
            "embedding": [1.0, 0.0, 0.0],
            "color_hist": [0.1, 0.2, 0.3],
            "tokens": ["alpha", "runner"],
        },
    )
    monkeypatch.setattr(app_module.db, "insert_image_record", lambda product_id, save_path, index: 456)
    monkeypatch.setattr(app_module.db, "upsert_product_image_retrieval_cache", lambda **kwargs: True)
    monkeypatch.setattr(app_module, "invalidate_product_retrieval_runtime", lambda strategy_name=None: None)
    monkeypatch.setattr(
        app_module,
        "schedule_external_product_support_refresh",
        lambda product_id, reason="upload": refresh_calls.append((str(product_id), reason)) or True,
        raising=False,
    )

    processed, stats = app_module.save_product_images_unified(
        "916",
        ["https://example.com/a.jpg"],
    )

    assert processed == 1
    assert stats["stored"] == 1
    assert refresh_calls == [("916", "catalog_sync")]
