import sys
import types
import unittest


cv2_stub = types.ModuleType("cv2")
pil_stub = types.ModuleType("PIL")
pil_image_stub = types.ModuleType("PIL.Image")
pil_imageops_stub = types.ModuleType("PIL.ImageOps")


class _DummyResampling:
    LANCZOS = "lanczos"
    BICUBIC = "bicubic"


class _DummyImage:
    def __init__(self, size):
        self.size = size
        self.last_resize = None

    def convert(self, mode):
        return self

    def resize(self, size, resample):
        self.size = size
        self.last_resize = resample
        return self


pil_image_stub.Resampling = _DummyResampling
pil_image_stub.open = lambda *args, **kwargs: None
pil_imageops_stub.exif_transpose = lambda image: image
pil_stub.Image = pil_image_stub
pil_stub.ImageOps = pil_imageops_stub
pil_stub.UnidentifiedImageError = type("UnidentifiedImageError", (Exception,), {})

sys.modules.setdefault("cv2", cv2_stub)
sys.modules.setdefault("PIL", pil_stub)
sys.modules.setdefault("PIL.Image", pil_image_stub)
sys.modules.setdefault("PIL.ImageOps", pil_imageops_stub)

from backend.benchmarks import strategies


class Siglip2StrategyResamplingTestCase(unittest.TestCase):
    def test_resampling_constant_is_defined(self):
        self.assertTrue(hasattr(strategies, "_RESAMPLING"))

    def test_normalize_image_for_inference_uses_resampling_constant(self):
        image = _DummyImage((100, 20))

        result = strategies._Siglip2Encoder._normalize_image_for_inference(image)

        self.assertEqual(result.size, (160, 32))


if __name__ == "__main__":
    unittest.main()
