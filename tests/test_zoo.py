import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from src.builder.schema import AgentSpec
from src.config_schema import TaskConfig
from src.graph.runner import build_task_runner_graph
from src.zoo import app as zoo_app
from src.zoo.storage import CollaborationMessage, ZooStore


class ZooModel:
    def invoke(self, messages):
        return AIMessage(content=f"Public response from {messages[0].content}"[:500])


def test_zoo_store_uses_bind_mount_safe_delete_journal(tmp_path: Path) -> None:
    database = tmp_path / "zoo.sqlite"

    ZooStore(database)

    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"


def test_zoo_store_persists_agents_and_messages(tmp_path: Path) -> None:
    store = ZooStore(tmp_path / "zoo.sqlite")
    store.create_run("thread-1", "trace-1", {"task_type": "research", "task_input": {}})
    store.upsert_agent("thread-1", "Researcher", "working", 1, ["web_search"])
    store.add_message(
        CollaborationMessage(
            trace_id="trace-1",
            thread_id="thread-1",
            from_agent="Researcher",
            message_type="evidence",
            content="A public evidence summary.",
            round=0,
        )
    )

    first = store.add_event("thread-1", "trace-1", "agent.started", "Researcher", "Started work")
    second = store.add_event("thread-1", "trace-1", "mcp.tool.started", "web_search", "Search started")

    run = store.get_run("thread-1")
    assert run["agents"][0]["role"] == "Researcher"
    assert run["messages"][0]["message_type"] == "evidence"
    assert [event["sequence"] for event in store.list_events(after=first - 1)] == [first, second]
    assert store.list_events(after=first)[0]["event_type"] == "mcp.tool.started"
    assert store.latest_event_sequence() == second


def test_collaboration_round_is_bounded_and_persisted(tmp_path: Path) -> None:
    store = ZooStore(tmp_path / "zoo.sqlite")
    task = TaskConfig(task_type="research", max_agents=2)
    agents = [
        AgentSpec(role="Researcher", system_prompt="Research", handoff_order=1),
        AgentSpec(role="Reviewer", system_prompt="Review", handoff_order=2),
    ]
    store.create_run("thread-2", "trace-2", task.model_dump(mode="json"))
    graph = build_task_runner_graph(ZooModel(), collaboration_store=store)

    output = graph.invoke(
        {
            "task_config": task,
            "agents": agents,
            "results": [],
            "trace_id": "trace-2",
            "thread_id": "thread-2",
        }
    )

    assert len(output["collaboration_messages"]) == 5
    assert {message["round"] for message in output["collaboration_messages"]} == {0, 1, 2}
    assert len(store.get_run("thread-2")["messages"]) == 7


def test_dashboard_and_run_api(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(zoo_app, "store", ZooStore(tmp_path / "zoo.sqlite"))

    async def no_op_run(thread_id, trace_id, task):
        return None

    monkeypatch.setattr(zoo_app, "execute_run", no_op_run)
    client = TestClient(zoo_app.app)
    page = client.get("/")
    response = client.post(
        "/api/runs",
        json={"task_type": "research", "task_input": {"topic": "Agent collaboration"}, "max_agents": 2},
    )

    assert page.status_code == 200
    assert "Agent Zoo" in page.text
    assert "agent-drawer" in page.text
    assert "Live activity" in page.text
    assert response.status_code == 202
    thread_id = response.json()["thread_id"]
    assert client.get(f"/api/runs/{thread_id}").json()["status"] == "queued"
    assert client.delete("/api/runs?confirm=true").status_code == 409

    zoo_app.store.set_run_status(thread_id, "completed")
    cleared = client.delete("/api/runs?confirm=true")

    assert cleared.status_code == 200
    assert cleared.json()["deleted"]["runs"] == 1
    assert client.get("/api/runs").json() == []
