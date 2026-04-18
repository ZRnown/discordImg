from __future__ import annotations

import threading
from copy import deepcopy
from datetime import datetime
from typing import Any, Dict, Optional


_lock = threading.Lock()
_state: Dict[str, Any] = {
    "stage": "starting",
    "title": "正在启动",
    "message": "正在初始化桌面后端",
    "current_task": "准备环境",
    "progress": 0,
    "completed": False,
    "error": None,
    "updated_at": datetime.now().isoformat(),
}


def update_bootstrap_state(
    *,
    stage: Optional[str] = None,
    title: Optional[str] = None,
    message: Optional[str] = None,
    current_task: Optional[str] = None,
    progress: Optional[int] = None,
    completed: Optional[bool] = None,
    error: Optional[str] = None,
) -> Dict[str, Any]:
    with _lock:
        if stage is not None:
            _state["stage"] = stage
        if title is not None:
            _state["title"] = title
        if message is not None:
            _state["message"] = message
        if current_task is not None:
            _state["current_task"] = current_task
        if progress is not None:
            _state["progress"] = max(0, min(100, int(progress)))
        if completed is not None:
            _state["completed"] = bool(completed)
        if error is not None:
            _state["error"] = error
        _state["updated_at"] = datetime.now().isoformat()
        return deepcopy(_state)


def get_bootstrap_state() -> Dict[str, Any]:
    with _lock:
        return deepcopy(_state)
