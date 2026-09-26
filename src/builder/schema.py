from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, RootModel, field_validator


class AgentSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    system_prompt: str = Field(min_length=1)
    tool_allowlist: list[str] = Field(default_factory=list)
    handoff_order: int = Field(ge=1)

    @field_validator("role", "system_prompt")
    @classmethod
    def text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("value must not be blank")
        return value

    @field_validator("tool_allowlist")
    @classmethod
    def tools_must_be_unique_and_nonblank(cls, value: list[str]) -> list[str]:
        normalized = [tool.strip() for tool in value]
        if any(not tool for tool in normalized):
            raise ValueError("tool_allowlist cannot contain blank names")
        if len(normalized) != len(set(normalized)):
            raise ValueError("tool_allowlist must contain unique names")
        return normalized


class AgentCrew(RootModel[Annotated[list[AgentSpec], Field(min_length=1, max_length=4)]]):
    pass
