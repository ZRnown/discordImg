from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import sys
from typing import Mapping, Optional


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class RuntimeMode:
    desktop_single_user: bool
    desktop_skip_ai_warmup: bool
    license_required: bool
    desktop_mode_source: str
    desktop_backend_process: bool
    executable_name: str
    frozen: bool


def _parse_optional_bool(raw_value: Optional[object]) -> Optional[bool]:
    if raw_value is None:
        return None

    normalized = str(raw_value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _resolve_executable_name(sys_module=None) -> str:
    current_sys = sys_module or sys
    executable = getattr(current_sys, "executable", "") or ""
    return Path(str(executable)).name.lower()


def _is_desktop_backend_process(sys_module=None) -> bool:
    current_sys = sys_module or sys
    executable_name = _resolve_executable_name(current_sys)
    frozen = bool(getattr(current_sys, "frozen", False))
    return executable_name.startswith("backend-api") or frozen


def resolve_runtime_mode(
    env: Optional[Mapping[str, object]] = None,
    sys_module=None,
) -> RuntimeMode:
    current_env = env or os.environ
    current_sys = sys_module or sys
    executable_name = _resolve_executable_name(current_sys)
    frozen = bool(getattr(current_sys, "frozen", False))
    desktop_backend_process = _is_desktop_backend_process(current_sys)

    desktop_single_user_env = _parse_optional_bool(current_env.get("DESKTOP_SINGLE_USER"))
    desktop_skip_ai_warmup_env = _parse_optional_bool(current_env.get("DESKTOP_SKIP_AI_WARMUP"))
    license_required_env = _parse_optional_bool(current_env.get("LICENSE_REQUIRED"))

    if desktop_single_user_env is not None:
        desktop_single_user = desktop_single_user_env
        desktop_mode_source = "env"
    elif desktop_backend_process:
        desktop_single_user = True
        desktop_mode_source = "packaged-backend-default"
    else:
        desktop_single_user = False
        desktop_mode_source = "default"

    if desktop_skip_ai_warmup_env is not None:
        desktop_skip_ai_warmup = desktop_skip_ai_warmup_env
    else:
        desktop_skip_ai_warmup = desktop_single_user

    if license_required_env is not None:
        license_required = license_required_env
    else:
        license_required = not desktop_single_user

    return RuntimeMode(
        desktop_single_user=desktop_single_user,
        desktop_skip_ai_warmup=desktop_skip_ai_warmup,
        license_required=license_required,
        desktop_mode_source=desktop_mode_source,
        desktop_backend_process=desktop_backend_process,
        executable_name=executable_name,
        frozen=frozen,
    )
