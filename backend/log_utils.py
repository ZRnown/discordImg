from datetime import datetime


def format_record_log_entry(record, formatter=None):
    raw_line = formatter.format(record) if formatter else record.getMessage()
    return {
        "timestamp": datetime.now().isoformat(),
        "level": record.levelname,
        "message": record.getMessage(),
        "module": getattr(record, "module", None) or getattr(record, "name", "system"),
        "func": getattr(record, "funcName", "") or "",
        "raw_line": raw_line,
    }


def normalize_external_log_entry(data):
    payload = data or {}
    message = payload.get("message", "")
    return {
        "timestamp": payload.get("timestamp", datetime.now().isoformat()),
        "level": payload.get("level", "INFO"),
        "message": message,
        "module": payload.get("module", "external"),
        "func": payload.get("func", ""),
        "raw_line": payload.get("raw_line") or message,
    }
