from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_type: Literal["missing_tools"] = "missing_tools"
    missing_tools: list[str] = Field(min_length=1)
    affected_roles: list[str] = Field(min_length=1)
    instructions: str = (
        "Add the missing MCP server, then resume with 'retry'; resume with "
        "'continue_without_tool' to proceed without it, or 'cancel' to stop."
    )
