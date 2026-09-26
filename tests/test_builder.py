import json

import pytest
from langchain_core.messages import AIMessage

from src.builder.service import BuilderOutputError, invoke_builder, parse_agent_crew
from src.config_schema import TaskConfig


TASK = TaskConfig(task_type="research", allowed_tools=["web_search", "file_write"], max_agents=3)
VALID_CREW = [
    {
        "role": "Researcher",
        "system_prompt": "Find relevant and reliable source material.",
        "tool_allowlist": ["web_search"],
        "handoff_order": 1,
    },
    {
        "role": "Analyst",
        "system_prompt": "Synthesize findings and identify key themes.",
        "tool_allowlist": [],
        "handoff_order": 2,
    },
    {
        "role": "Writer",
        "system_prompt": "Produce the requested structured research response.",
        "tool_allowlist": ["file_write"],
        "handoff_order": 3,
    },
]


class SequenceModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.prompts: list[str] = []

    def invoke(self, prompt: str) -> AIMessage:
        self.prompts.append(prompt)
        return AIMessage(content=next(self.responses))


def test_builder_graph_returns_validated_agent_specs() -> None:
    agents = invoke_builder(TASK, SequenceModel([json.dumps(VALID_CREW)]))

    assert [agent.role for agent in agents] == ["Researcher", "Analyst", "Writer"]
    assert agents[0].tool_allowlist == ["web_search"]


def test_builder_retries_invalid_output_with_validation_feedback() -> None:
    model = SequenceModel(["not json", json.dumps(VALID_CREW)])

    agents = invoke_builder(TASK, model, max_attempts=2)

    assert len(agents) == 3
    assert len(model.prompts) == 2
    assert "previous output was invalid" in model.prompts[1]
    assert "not json" in model.prompts[1]


def test_builder_fails_after_retry_limit() -> None:
    with pytest.raises(BuilderOutputError, match="failed after 2 attempts"):
        invoke_builder(TASK, SequenceModel(["invalid", "still invalid"]), max_attempts=2)


def test_builder_rejects_disallowed_tools() -> None:
    invalid_crew = [dict(agent) for agent in VALID_CREW]
    invalid_crew[0] = {**invalid_crew[0], "tool_allowlist": ["shell"]}

    with pytest.raises(BuilderOutputError, match="disallowed tools: shell"):
        parse_agent_crew(json.dumps(invalid_crew), TASK)


def test_builder_rejects_unassigned_required_tools() -> None:
    task = TaskConfig(
        task_type="research",
        allowed_tools=["web_search"],
        required_tools=["web_search"],
        max_agents=3,
    )
    invalid_crew = [{**agent, "tool_allowlist": []} for agent in VALID_CREW]

    with pytest.raises(BuilderOutputError, match="Required tools were not assigned: web_search"):
        parse_agent_crew(json.dumps(invalid_crew), task)


def test_builder_rejects_nonconsecutive_handoff_order() -> None:
    invalid_crew = [dict(agent) for agent in VALID_CREW]
    invalid_crew[2] = {**invalid_crew[2], "handoff_order": 4}

    with pytest.raises(BuilderOutputError, match="Handoff orders must be consecutive"):
        parse_agent_crew(json.dumps(invalid_crew), TASK)
