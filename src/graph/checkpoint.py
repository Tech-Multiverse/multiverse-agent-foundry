import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite import SqliteSaver


_ALLOWED_CHECKPOINT_TYPES = [
    ("src.config_schema", "TaskConfig"),
    ("src.builder.schema", "AgentSpec"),
    ("src.graph.runner", "AgentResult"),
]


@contextmanager
def sqlite_checkpointer(path: str | Path) -> Iterator[SqliteSaver]:
    connection = sqlite3.connect(str(path), check_same_thread=False)
    serializer = JsonPlusSerializer(allowed_msgpack_modules=_ALLOWED_CHECKPOINT_TYPES)
    try:
        yield SqliteSaver(connection, serde=serializer)
    finally:
        connection.close()
