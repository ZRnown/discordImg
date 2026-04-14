import hashlib
import json
import logging
import os
import platform
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests


logger = logging.getLogger(__name__)


class LicenseManager:
    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        self.license_file = os.path.join(self.data_dir, "license.json")
        self.default_server = os.getenv("LICENSE_SERVER_URL", "http://107.172.1.7:8888").rstrip("/")
        self.timeout = int(os.getenv("LICENSE_REQUEST_TIMEOUT", "10"))
        self.retry_attempts = max(1, int(os.getenv("LICENSE_RETRY_ATTEMPTS", "4")))
        self.retry_base_delay = float(os.getenv("LICENSE_RETRY_BASE_DELAY", "0.8"))
        self.retry_max_delay = float(os.getenv("LICENSE_RETRY_MAX_DELAY", "6"))
        self._hwid = self.generate_hwid()

        os.makedirs(self.data_dir, exist_ok=True)

    @property
    def hwid(self) -> str:
        return self._hwid

    def generate_hwid(self) -> str:
        try:
            mac = ":".join(["{:02x}".format((uuid.getnode() >> i) & 0xff) for i in range(0, 48, 8)])[:17]
            machine = platform.machine()
            system = platform.system()
            hwid_source = f"{machine}-{system}-{mac}"
            return hashlib.sha256(hwid_source.encode("utf-8")).hexdigest()[:32].upper()
        except Exception:
            return hashlib.sha256(str(uuid.getnode()).encode("utf-8")).hexdigest()[:32].upper()

    def _candidate_servers(self) -> List[str]:
        candidates = [self.default_server]
        if self.default_server == "http://107.172.1.7:8888":
            candidates.append("http://107.172.1.7:8000")
        return candidates

    def _load_local(self) -> Optional[Dict[str, Any]]:
        if not os.path.exists(self.license_file):
            return None
        try:
            with open(self.license_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"读取本地 license 文件失败: {e}")
            return None

    def _save_local(self, payload: Dict[str, Any]) -> None:
        with open(self.license_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def _mask_key(self, key: str) -> str:
        if len(key) <= 8:
            return key
        return f"{key[:4]}...{key[-4:]}"

    def is_activated_local(self) -> bool:
        data = self._load_local()
        if not data:
            return False
        return data.get("hwid") == self.hwid and bool(data.get("license_key"))

    def has_any_local_activation(self) -> bool:
        data = self._load_local()
        return bool(data and data.get("license_key"))

    def _call_activate(self, server: str, key: str, hwid: str) -> requests.Response:
        return requests.post(
            f"{server}/api/activate",
            json={"key": key, "hwid": hwid},
            timeout=self.timeout,
        )

    def _parse_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None

        if isinstance(value, (int, float)):
            ts = float(value)
            # 兼容毫秒时间戳
            if ts > 1e12:
                ts /= 1000.0
            try:
                return datetime.fromtimestamp(ts)
            except Exception:
                return None

        text = str(value).strip()
        if not text:
            return None

        # 兼容 ISO8601（含 Z）
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            pass

        for fmt in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
        ):
            try:
                return datetime.strptime(text, fmt)
            except Exception:
                continue
        return None

    def _resolve_expires_at(self, data: Dict[str, Any], activated_at: datetime) -> Optional[str]:
        for key in (
            "expires_at",
            "expired_at",
            "expire_at",
            "expire_time",
            "expireTime",
            "end_time",
            "endTime",
            "end_at",
            "endAt",
        ):
            if key not in data:
                continue
            parsed = self._parse_datetime(data.get(key))
            if parsed is not None:
                return parsed.isoformat()

            # 若服务端返回的是无法解析的原样字符串，保留原值
            raw = data.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()

        days = data.get("days")
        try:
            days_num = float(days)
        except Exception:
            days_num = None

        # days > 0 时按激活时间推导到期时间；<=0 视为长期授权
        if days_num is not None and days_num > 0:
            return (activated_at + timedelta(days=days_num)).isoformat()
        return None

    def _is_transient_status(self, status_code: int) -> bool:
        return status_code == 408 or status_code == 429 or status_code >= 500

    def _activate_with_retry(self, server: str, key: str, hwid: str) -> Tuple[Optional[requests.Response], str, int]:
        last_error = "无法连接授权服务器"
        last_status = 503

        for attempt in range(1, self.retry_attempts + 1):
            try:
                res = self._call_activate(server, key, hwid)
                if res.status_code == 200:
                    return res, "", 200

                try:
                    detail = res.json().get("detail")
                except Exception:
                    detail = res.text or "激活失败"

                if not self._is_transient_status(res.status_code):
                    return res, detail or "激活失败", res.status_code

                last_error = detail or f"授权服务器临时错误 ({res.status_code})"
                last_status = res.status_code
            except requests.exceptions.Timeout:
                last_error = f"连接授权服务器超时 ({server})"
                last_status = 504
            except Exception as e:
                last_error = f"授权服务器连接失败 ({server}): {e}"
                last_status = 503

            if attempt < self.retry_attempts:
                delay = min(self.retry_base_delay * (2 ** (attempt - 1)), self.retry_max_delay)
                time.sleep(delay)

        return None, last_error, last_status

    def activate(self, key: str) -> Tuple[bool, str, Dict[str, Any], int]:
        key = (key or "").strip()
        if not key:
            return False, "密钥不能为空", {}, 400

        if self.has_any_local_activation():
            return False, "当前设备已激活，不可重复激活", {}, 409

        last_error = "无法连接授权服务器"
        last_status = 503
        for server in self._candidate_servers():
            res, error_msg, status_code = self._activate_with_retry(server, key, self.hwid)
            if res is not None and res.status_code == 200:
                data = res.json()
                activated_at = datetime.now()
                payload = {
                    "license_key": key,
                    "key_masked": self._mask_key(key),
                    "hwid": self.hwid,
                    "server": server,
                    "days": data.get("days"),
                    "activated_at": activated_at.isoformat(),
                    "expires_at": self._resolve_expires_at(data, activated_at),
                    "last_verified_at": datetime.now().isoformat(),
                }
                self._save_local(payload)
                return True, data.get("msg", "激活成功"), data, 200

            if status_code in (403, 404):
                return False, error_msg or "激活失败", {}, status_code

            last_error = error_msg or "授权服务器错误"
            last_status = status_code

        return False, last_error, {}, last_status

    def verify_saved(self) -> Tuple[bool, str]:
        data = self._load_local()
        if not data:
            return False, "未检测到本地激活信息"

        key = (data.get("license_key") or "").strip()
        if not key:
            return False, "本地激活信息无效"

        if data.get("hwid") != self.hwid:
            return False, "本地密钥与当前设备不匹配"

        return True, "本地激活信息有效"

    def status(self) -> Dict[str, Any]:
        data = self._load_local()
        if not data:
            return {
                "activated": False,
                "hwid": self.hwid,
                "server": self.default_server,
            }

        local_ok = data.get("hwid") == self.hwid and bool(data.get("license_key"))
        return {
            "activated": local_ok,
            "hwid": self.hwid,
            "server": data.get("server") or self.default_server,
            "key_masked": data.get("key_masked") or self._mask_key(data.get("license_key", "")),
            "activated_at": data.get("activated_at"),
            "expires_at": data.get("expires_at"),
            "last_verified_at": data.get("last_verified_at"),
            "days": data.get("days"),
        }
