import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


MessageType = Literal["observation", "evidence", "proposal", "question", "answer", "critique", "revision", "handoff", "decision", "resource_request"]


class CollaborationMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message_id: str = Field(default_factory=lambda: uuid4().hex)
    trace_id: str
    thread_id: str
    from_agent: str = Field(min_length=1)
    to_agent: str = "all"
    message_type: MessageType
    content: str = Field(min_length=1, max_length=2000)
    round: int = Field(ge=0, le=2)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ZooStore:
    def __init__(self, database_path: str | Path) -> None:
        self.database_path = str(database_path)
        self._setup()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _setup(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    thread_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    task_json TEXT NOT NULL,
                    result_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS agents (
                    thread_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    status TEXT NOT NULL,
                    handoff_order INTEGER NOT NULL,
                    tool_allowlist_json TEXT NOT NULL,
                    PRIMARY KEY (thread_id, role)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    message_id TEXT PRIMARY KEY,
                    trace_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    content TEXT NOT NULL,
                    round INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    thread_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    target TEXT,
                    summary TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            agent_columns = {row["name"] for row in connection.execute("PRAGMA table_info(agents)")}
            if "system_prompt" not in agent_columns:
                connection.execute("ALTER TABLE agents ADD COLUMN system_prompt TEXT NOT NULL DEFAULT ''")
            if "updated_at" not in agent_columns:
                connection.execute("ALTER TABLE agents ADD COLUMN updated_at TEXT NOT NULL DEFAULT ''")

    def create_run(self, thread_id: str, trace_id: str, task: dict[str, Any]) -> None:
        now = datetime.now(UTC).isoformat()
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, NULL, ?, ?)",
                (thread_id, trace_id, "queued", json.dumps(task), now, now),
            )

    def set_run_status(self, thread_id: str, status: str, result: dict[str, Any] | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE runs SET status = ?, result_json = COALESCE(?, result_json), updated_at = ? WHERE thread_id = ?",
                (status, json.dumps(result) if result is not None else None, datetime.now(UTC).isoformat(), thread_id),
            )

    def upsert_agent(
        self,
        thread_id: str,
        role: str,
        status: str,
        handoff_order: int,
        tools: list[str],
        system_prompt: str = "",
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO agents
                    (thread_id, role, status, handoff_order, tool_allowlist_json, system_prompt, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(thread_id, role) DO UPDATE SET
                    status=excluded.status,
                    handoff_order=excluded.handoff_order,
                    tool_allowlist_json=excluded.tool_allowlist_json,
                    system_prompt=CASE WHEN excluded.system_prompt = '' THEN agents.system_prompt ELSE excluded.system_prompt END,
                    updated_at=excluded.updated_at
                """,
                (
                    thread_id,
                    role,
                    status,
                    handoff_order,
                    json.dumps(tools),
                    system_prompt,
                    datetime.now(UTC).isoformat(),
                ),
            )

    def add_event(
        self,
        thread_id: str,
        trace_id: str,
        event_type: str,
        actor: str,
        summary: str,
        target: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO events
                    (thread_id, trace_id, event_type, actor, target, summary, metadata_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    thread_id,
                    trace_id,
                    event_type,
                    actor,
                    target,
                    summary[:500],
                    json.dumps(metadata or {}),
                    datetime.now(UTC).isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def list_events(
        self,
        after: int = 0,
        thread_id: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM events WHERE sequence > ?"
        parameters: list[Any] = [after]
        if thread_id:
            query += " AND thread_id = ?"
            parameters.append(thread_id)
        query += " ORDER BY sequence LIMIT ?"
        parameters.append(min(max(limit, 1), 500))
        with self._connect() as connection:
            rows = connection.execute(query, parameters).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "thread_id": row["thread_id"],
                "trace_id": row["trace_id"],
                "event_type": row["event_type"],
                "actor": row["actor"],
                "target": row["target"],
                "summary": row["summary"],
                "metadata": json.loads(row["metadata_json"]),
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def latest_event_sequence(self) -> int:
        with self._connect() as connection:
            row = connection.execute("SELECT COALESCE(MAX(sequence), 0) AS sequence FROM events").fetchone()
        return int(row["sequence"])

    def add_message(self, message: CollaborationMessage) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                tuple(message.model_dump().values()),
            )

    def list_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT thread_id, trace_id, status, task_json, result_json, created_at, updated_at FROM runs ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                **dict(row),
                "task": json.loads(row["task_json"]),
                "result": json.loads(row["result_json"]) if row["result_json"] else None,
            }
            for row in rows
        ]

    def get_run(self, thread_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            run = connection.execute("SELECT * FROM runs WHERE thread_id = ?", (thread_id,)).fetchone()
            agents = connection.execute(
                "SELECT * FROM agents WHERE thread_id = ? ORDER BY handoff_order", (thread_id,)
            ).fetchall()
            messages = connection.execute(
                "SELECT * FROM messages WHERE thread_id = ? ORDER BY created_at", (thread_id,)
            ).fetchall()
            events = connection.execute(
                "SELECT * FROM events WHERE thread_id = ? ORDER BY sequence", (thread_id,)
            ).fetchall()
        if run is None:
            return None
        return {
            "thread_id": run["thread_id"],
            "trace_id": run["trace_id"],
            "status": run["status"],
            "task": json.loads(run["task_json"]),
            "result": json.loads(run["result_json"]) if run["result_json"] else None,
            "created_at": run["created_at"],
            "updated_at": run["updated_at"],
            "agents": [
                {
                    "role": agent["role"],
                    "status": agent["status"],
                    "handoff_order": agent["handoff_order"],
                    "tool_allowlist": json.loads(agent["tool_allowlist_json"]),
                    "system_prompt": agent["system_prompt"],
                    "updated_at": agent["updated_at"],
                }
                for agent in agents
            ],
            "messages": [dict(message) for message in messages],
            "events": [
                {
                    "sequence": event["sequence"],
                    "thread_id": event["thread_id"],
                    "trace_id": event["trace_id"],
                    "event_type": event["event_type"],
                    "actor": event["actor"],
                    "target": event["target"],
                    "summary": event["summary"],
                    "metadata": json.loads(event["metadata_json"]),
                    "created_at": event["created_at"],
                }
                for event in events
            ],
        }
