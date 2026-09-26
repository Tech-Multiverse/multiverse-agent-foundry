import threading
import time
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage, BaseMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from src.builder.schema import AgentSpec
from src.config_schema import TaskConfig
from src.graph.checkpoint import sqlite_checkpointer
from src.graph.runner import build_task_runner_graph, invoke_task_runner


TASK = TaskConfig(task_type="research", allowed_tools=[], max_agents=3)
AGENTS = [
    AgentSpec(role="Researcher", system_prompt="Researcher", handoff_order=1),
    AgentSpec(role="Analyst", system_prompt="Analyst", handoff_order=2),
    AgentSpec(role="Writer", system_prompt="Writer", handoff_order=3),
]


class TrackingModel:
    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def invoke(self, messages: list[BaseMessage]) -> AIMessage:
        role = str(messages[0].content)
        with self.lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        time.sleep(self.delay)
        with self.lock:
            self.active -= 1
        return AIMessage(content=f"{role} result")


def test_runner_serializes_branches_at_concurrency_one() -> None:
    model = TrackingModel()

    results = invoke_task_runner(TASK, AGENTS, model, max_concurrency=1)

    assert model.max_active == 1
    assert [result.role for result in results] == ["Researcher", "Analyst", "Writer"]


def test_runner_executes_branches_concurrently_when_dial_increases() -> None:
    model = TrackingModel()

    results = invoke_task_runner(TASK, AGENTS, model, max_concurrency=2)

    assert model.max_active == 2
    assert [result.handoff_order for result in results] == [1, 2, 3]


def test_runner_rejects_empty_agent_list() -> None:
    with pytest.raises(ValueError, match="agents must not be empty"):
        invoke_task_runner(TASK, [], TrackingModel())


def test_missing_mcp_tool_interrupts_and_can_resume_without_tool() -> None:
    agent = AgentSpec(
        role="Specialist",
        system_prompt="Specialist",
        tool_allowlist=["missing_tool"],
        handoff_order=1,
    )
    graph = build_task_runner_graph(TrackingModel(), checkpointer=InMemorySaver())
    config = {"configurable": {"thread_id": "resource-test"}}

    paused = graph.invoke({"task_config": TASK, "agents": [agent], "results": []}, config=config)

    assert paused["__interrupt__"][0].value["missing_tools"] == ["missing_tool"]
    completed = graph.invoke(Command(resume="continue_without_tool"), config=config)
    assert completed["final_results"][0].role == "Specialist"


def test_sqlite_checkpoint_resumes_after_checkpointer_reopens(tmp_path: Path) -> None:
    agent = AgentSpec(
        role="Specialist",
        system_prompt="Specialist",
        tool_allowlist=["missing_tool"],
        handoff_order=1,
    )
    database = str(tmp_path / "checkpoints.sqlite")
    config = {"configurable": {"thread_id": "durable-resource-test"}}

    with sqlite_checkpointer(database) as checkpointer:
        graph = build_task_runner_graph(TrackingModel(), checkpointer=checkpointer)
        paused = graph.invoke({"task_config": TASK, "agents": [agent], "results": []}, config=config)
        assert "__interrupt__" in paused

    with sqlite_checkpointer(database) as checkpointer:
        graph = build_task_runner_graph(TrackingModel(), checkpointer=checkpointer)
        completed = graph.invoke(Command(resume="continue_without_tool"), config=config)

    assert completed["final_results"][0].role == "Specialist"
