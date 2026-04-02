import importlib
import logging
from types import ModuleType
from typing import Callable, Optional


logger = logging.getLogger(__name__)

_heif_support_attempted = False
_heif_support_enabled = False


def enable_optional_pillow_image_plugins(
    import_module: Optional[Callable[[str], ModuleType]] = None,
    log: Optional[logging.Logger] = None,
) -> bool:
    global _heif_support_attempted, _heif_support_enabled

    if _heif_support_attempted:
        return _heif_support_enabled

    _heif_support_attempted = True
    importer = import_module or importlib.import_module
    active_logger = log or logger

    try:
        heif_module = importer("pi_heif")
    except ModuleNotFoundError:
        active_logger.info("未安装 pi-heif，跳过 HEIC/HEIF 图片支持")
        _heif_support_enabled = False
        return False
    except Exception as exc:
        active_logger.warning(f"加载 pi-heif 失败，已跳过 HEIC/HEIF 图片支持: {exc}")
        _heif_support_enabled = False
        return False

    register_heif_opener = getattr(heif_module, "register_heif_opener", None)
    if not callable(register_heif_opener):
        active_logger.warning("pi-heif 缺少 register_heif_opener，已跳过 HEIC/HEIF 图片支持")
        _heif_support_enabled = False
        return False

    try:
        register_heif_opener()
    except Exception as exc:
        active_logger.warning(f"启用 HEIC/HEIF 图片支持失败: {exc}")
        _heif_support_enabled = False
        return False

    active_logger.info("已启用 HEIC/HEIF 图片支持")
    _heif_support_enabled = True
    return True


def reset_optional_image_plugin_state_for_tests() -> None:
    global _heif_support_attempted, _heif_support_enabled
    _heif_support_attempted = False
    _heif_support_enabled = False
