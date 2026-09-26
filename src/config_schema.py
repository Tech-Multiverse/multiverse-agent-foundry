from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class TaskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(min_length=1)
    task_input: dict[str, Any] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    max_agents: int = Field(ge=1)
    response_schema: dict[str, Any] | None = None

    @field_validator("task_type")
    @classmethod
    def task_type_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("task_type must not be blank")
        return value

    @field_validator("allowed_tools", "required_tools")
    @classmethod
    def tools_must_be_unique_and_nonblank(cls, value: list[str]) -> list[str]:
        normalized = [tool.strip() for tool in value]
        if any(not tool for tool in normalized):
            raise ValueError("allowed_tools cannot contain blank names")
        if len(normalized) != len(set(normalized)):
            raise ValueError("tool lists must contain unique names")
        return normalized

    @model_validator(mode="after")
    def required_tools_must_be_allowed(self) -> "TaskConfig":
        disallowed = set(self.required_tools) - set(self.allowed_tools)
        if disallowed:
            raise ValueError(f"required_tools must also be allowed: {', '.join(sorted(disallowed))}")
        return self
