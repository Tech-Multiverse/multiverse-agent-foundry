import json
from pathlib import Path

from src.telemetry import emit_event, trace_span


def test_telemetry_writes_jsonl_and_redacts_sensitive_fields(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("FOUNDRY_DATA_DIR", str(tmp_path))

    emit_event("test.event", "trace-1", agent_count=3, api_key="do-not-store")
    with trace_span("test.span", "trace-1", role="researcher"):
        pass

    records = [json.loads(line) for line in (tmp_path / "traces.jsonl").read_text().splitlines()]
    assert records[0]["event"] == "test.event"
    assert records[0]["api_key"] == "[redacted]"
    assert records[1]["event"] == "test.span.started"
    assert records[2]["event"] == "test.span.completed"
    assert records[2]["duration_ms"] >= 0
