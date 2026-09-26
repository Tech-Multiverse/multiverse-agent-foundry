from pathlib import Path

import pytest
from pydantic import ValidationError

from src.builder import load_task_config
from src.config_schema import TaskConfig


EXAMPLE_CONFIG = Path("configs/example-tasks/research.yaml")


def test_example_config_is_valid() -> None:
    config = load_task_config(EXAMPLE_CONFIG)

    assert config.task_type == "research"
    assert config.task_input["topic"] == "How serialized multi-agent systems make local AI practical on an 8GB GPU"
    assert config.allowed_tools == ["web_search", "file_write"]
    assert config.required_tools == ["web_search"]
    assert config.max_agents == 3
    assert config.response_schema == {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "sources": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["summary", "sources"],
        "additionalProperties": False,
    }


def test_unknown_config_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskConfig.model_validate(
            {
                "task_type": "research",
                "allowed_tools": [],
                "max_agents": 1,
                "unexpected": True,
            }
        )


def test_duplicate_tools_are_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskConfig(task_type="research", allowed_tools=["web", "web"], max_agents=1)
