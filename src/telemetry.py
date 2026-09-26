import json
import os
import threading
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any, Iterator
from uuid import uuid4


_WRITE_LOCK = threading.Lock()
_SENSITIVE_FRAGMENTS = ("key", "password", "secret", "token")


def new_trace_id() -> str:
    return uuid4().hex


def _safe_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for name, value in metadata.items():
        if any(fragment in name.casefold() for fragment in _SENSITIVE_FRAGMENTS):
            safe[name] = "[redacted]"
        elif isinstance(value, str):
            safe[name] = value[:500]
        elif isinstance(value, (bool, float, int)) or value is None:
            safe[name] = value
        elif isinstance(value, list):
            safe[name] = value[:20]
        else:
            safe[name] = str(value)[:500]
    return safe


def emit_event(event: str, trace_id: str, **metadata: Any) -> None:
    data_dir = Path(os.environ.get("FOUNDRY_DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "timestamp": datetime.now(UTC).isoformat(),
        "event": event,
        "trace_id": trace_id,
        **_safe_metadata(metadata),
    }
    with _WRITE_LOCK:
        with (data_dir / "traces.jsonl").open("a", encoding="utf-8") as trace_file:
            trace_file.write(json.dumps(record, separators=(",", ":")) + "\n")


@contextmanager
def trace_span(event: str, trace_id: str, **metadata: Any) -> Iterator[None]:
    started = perf_counter()
    emit_event(f"{event}.started", trace_id, **metadata)
    try:
        yield
    except Exception as error:
        emit_event(
            f"{event}.failed",
            trace_id,
            duration_ms=round((perf_counter() - started) * 1000, 2),
            error_type=type(error).__name__,
        )
        raise
    emit_event(f"{event}.completed", trace_id, duration_ms=round((perf_counter() - started) * 1000, 2))
