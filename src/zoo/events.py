import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from src.zoo.storage import ZooStore


@lru_cache(maxsize=4)
def _store(database_path: str) -> ZooStore:
    return ZooStore(database_path)


def publish_run_event(
    thread_id: str,
    trace_id: str,
    event_type: str,
    actor: str,
    summary: str,
    target: str | None = None,
    **metadata: Any,
) -> int:
    data_dir = Path(os.environ.get("FOUNDRY_DATA_DIR", "data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    return _store(str(data_dir / "zoo.sqlite")).add_event(
        thread_id,
        trace_id,
        event_type,
        actor,
        summary,
        target,
        metadata,
    )
