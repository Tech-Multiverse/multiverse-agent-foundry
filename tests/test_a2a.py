import asyncio

from starlette.testclient import TestClient

from src.a2a import builder_server
from src.a2a.builder_server import build_and_dispatch
from src.a2a.runner_server import app as runner_app
from src.builder.schema import AgentSpec
from src.config_schema import TaskConfig


def test_builder_agent_card_is_exposed() -> None:
    response = TestClient(builder_server.app).get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert response.json()["name"] == "Multiverse Foundry Builder"
    assert response.json()["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"


def test_runner_agent_card_is_exposed() -> None:
    response = TestClient(runner_app).get("/.well-known/agent-card.json")

    assert response.status_code == 200
    assert response.json()["name"] == "Multiverse Foundry Runner"
    assert response.json()["skills"][0]["id"] == "run-agent-crew"


def test_builder_dispatches_generated_crew_over_a2a(monkeypatch) -> None:
    task = TaskConfig(task_type="research", max_agents=1)
    agent = AgentSpec(role="Researcher", system_prompt="Research", handoff_order=1)
    captured = {}

    monkeypatch.setattr(builder_server, "create_builder_model", lambda settings: object())
    monkeypatch.setattr(builder_server, "invoke_builder", lambda *args: [agent])

    async def fake_send(url, payload):
        captured["url"] = url
        captured["payload"] = payload
        return {"status": "completed", "thread_id": payload["thread_id"], "results": []}

    monkeypatch.setattr(builder_server, "send_json_message", fake_send)
    result = asyncio.run(
        build_and_dispatch({"task": task.model_dump(mode="json"), "thread_id": "a2a-test"})
    )

    assert result["status"] == "completed"
    assert captured["payload"]["agents"][0]["role"] == "Researcher"
    assert captured["url"].endswith(":8002")
