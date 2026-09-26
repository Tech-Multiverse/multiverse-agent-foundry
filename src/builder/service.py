import json
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from pydantic import ValidationError

from src.builder.schema import AgentCrew, AgentSpec
from src.config_schema import TaskConfig
from src.graph.workflow import message_content_as_text


class BuilderState(TypedDict, total=False):
    task_config: TaskConfig
    agents: list[AgentSpec]


class BuilderOutputError(ValueError):
    pass


def build_builder_prompt(task: TaskConfig) -> str:
    minimum_agents = min(2, task.max_agents)
    maximum_agents = min(4, task.max_agents)
    return (
        "You are an agent-factory architect. Design a focused crew for the supplied task.\n"
        f"Return a JSON array containing {minimum_agents} to {maximum_agents} agent specifications.\n"
        "Return JSON only, without markdown or commentary.\n"
        "Each role must be unique. Handoff orders must be consecutive integers starting at 1.\n"
        "Agents execute as independent fan-out branches, so no role may depend on another agent's output.\n"
        "Handoff order controls deterministic result aggregation, not sequential dependencies.\n"
        "Each agent may use only tools listed in allowed_tools. Assign every required_tools entry to at least one agent.\n"
        f"Task configuration:\n{task.model_dump_json(indent=2)}\n"
        f"Agent specification JSON Schema:\n{json.dumps(AgentCrew.model_json_schema(), indent=2)}"
    )


def parse_agent_crew(raw_output: str, task: TaskConfig) -> list[AgentSpec]:
    output = raw_output.strip()
    if output.startswith("```") and output.endswith("```"):
        lines = output.splitlines()
        output = "\n".join(lines[1:-1]).strip()

    try:
        crew = AgentCrew.model_validate_json(output).root
    except ValidationError as error:
        raise BuilderOutputError(f"Output did not match the agent schema: {error}") from error

    minimum_agents = min(2, task.max_agents)
    maximum_agents = min(4, task.max_agents)
    if not minimum_agents <= len(crew) <= maximum_agents:
        raise BuilderOutputError(f"Expected {minimum_agents} to {maximum_agents} agents, received {len(crew)}")

    roles = [agent.role.casefold() for agent in crew]
    if len(roles) != len(set(roles)):
        raise BuilderOutputError("Agent roles must be unique")

    orders = sorted(agent.handoff_order for agent in crew)
    if orders != list(range(1, len(crew) + 1)):
        raise BuilderOutputError("Handoff orders must be consecutive integers starting at 1")

    allowed_tools = set(task.allowed_tools)
    assigned_tools: set[str] = set()
    for agent in crew:
        assigned_tools.update(agent.tool_allowlist)
        disallowed = set(agent.tool_allowlist) - allowed_tools
        if disallowed:
            raise BuilderOutputError(
                f"Agent '{agent.role}' requested disallowed tools: {', '.join(sorted(disallowed))}"
            )

    unassigned = set(task.required_tools) - assigned_tools
    if unassigned:
        raise BuilderOutputError(f"Required tools were not assigned: {', '.join(sorted(unassigned))}")

    return crew


def generate_agent_crew(task: TaskConfig, model: Any, max_attempts: int = 3) -> list[AgentSpec]:
    if max_attempts < 1:
        raise ValueError("max_attempts must be at least 1")

    prompt = build_builder_prompt(task)
    last_error: BuilderOutputError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            message: BaseMessage = model.invoke(prompt)
        except Exception as error:
            raise RuntimeError(f"Builder model invocation failed: {error}") from error

        raw_output = message_content_as_text(message.content)
        try:
            return parse_agent_crew(raw_output, task)
        except BuilderOutputError as error:
            last_error = error
            if attempt < max_attempts:
                prompt = (
                    f"{build_builder_prompt(task)}\n\n"
                    f"Your previous output was invalid: {error}\n"
                    f"Previous output:\n{raw_output[:4000]}\n"
                    "Correct every validation error and return a new JSON array only."
                )

    raise BuilderOutputError(f"Builder failed after {max_attempts} attempts: {last_error}")


def build_builder_graph(model: Any, max_attempts: int = 3) -> CompiledStateGraph:
    def design_crew(state: BuilderState) -> dict[str, list[AgentSpec]]:
        return {"agents": generate_agent_crew(state["task_config"], model, max_attempts)}

    graph = StateGraph(BuilderState)
    graph.add_node("design_crew", design_crew)
    graph.add_edge(START, "design_crew")
    graph.add_edge("design_crew", END)
    return graph.compile()


def invoke_builder(task: TaskConfig, model: Any, max_attempts: int = 3) -> list[AgentSpec]:
    result = build_builder_graph(model, max_attempts).invoke({"task_config": task})
    return result["agents"]
