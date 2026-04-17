import io
import logging
import threading
from typing import Any

logger = logging.getLogger(__name__)


class LocalOcrService:
    def __init__(self):
        self._reader: Any = None
        self._load_attempted = False
        self._load_lock = threading.Lock()

    def _load_reader(self):
        if self._reader is not None:
            return self._reader
        if self._load_attempted:
            return None

        with self._load_lock:
            if self._reader is not None:
                return self._reader
            if self._load_attempted:
                return None

            self._load_attempted = True
            try:
                import easyocr
            except ImportError:
                logger.warning("本地 OCR 未启用: 缺少 easyocr 依赖")
                return None

            try:
                self._reader = easyocr.Reader(['ch_sim', 'en'], gpu=False, verbose=False)
                logger.info("本地 OCR 模型已加载")
            except Exception as exc:
                logger.error("加载本地 OCR 模型失败: %s", exc)
                self._reader = None

        return self._reader

    def extract_text(self, image_bytes: bytes) -> str:
        if not image_bytes:
            return ''

        reader = self._load_reader()
        if reader is None:
            return ''

        try:
            import numpy as np
            from PIL import Image

            image = Image.open(io.BytesIO(image_bytes)).convert('RGB')
            image_array = np.array(image)
        except Exception as exc:
            logger.error("OCR 读取图片失败: %s", exc)
            return ''

        try:
            results = reader.readtext(image_array, detail=0, paragraph=True)
        except Exception as exc:
            logger.error("OCR 识别失败: %s", exc)
            return ''

        if not isinstance(results, (list, tuple)):
            return ''

        texts = [str(item).strip() for item in results if str(item).strip()]
        return '\n'.join(texts)


ocr_service = LocalOcrService()
