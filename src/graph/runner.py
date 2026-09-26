import asyncio
import json
import operator
from threading import BoundedSemaphore, Lock
from typing import Annotated, Any, TypedDict

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Send, interrupt
from pydantic import BaseModel, ConfigDict, Field

from src.builder.schema import AgentSpec
from src.config_schema import TaskConfig
from src.graph.workflow import message_content_as_text
from src.resource_requests.models import ResourceRequest
from src.telemetry import emit_event, new_trace_id, trace_span
from src.tools.client import load_mcp_tools
from src.zoo.storage import CollaborationMessage, ZooStore


class AgentResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str = Field(min_length=1)
    content: str = Field(min_length=1)
    handoff_order: int = Field(ge=1)


class RunnerState(TypedDict, total=False):
    task_config: TaskConfig
    agents: list[AgentSpec]
    results: Annotated[list[AgentResult], operator.add]
    final_results: list[AgentResult]
    trace_id: str
    thread_id: str
    collaboration_messages: list[dict[str, Any]]


class AgentBranchState(TypedDict):
    task_config: TaskConfig
    agent: AgentSpec
    trace_id: str
    thread_id: str


def build_agent_prompt(task: TaskConfig, agent: AgentSpec) -> list[BaseMessage]:
    requested_schema = json.dumps(task.response_schema, indent=2) if task.response_schema else "No response schema supplied."
    return [
        SystemMessage(content=agent.system_prompt),
        HumanMessage(
            content=(
                f"Complete your part of this task as the {agent.role}.\n"
                "This branch runs independently and receives no output from other agents. "
                "Do not imply that another agent supplied research or artifacts.\n"
                f"Task type: {task.task_type}\n"
                f"Task input:\n{json.dumps(task.task_input, indent=2)}\n"
                f"Allowed tools for this role: {json.dumps(agent.tool_allowlist)}\n"
                f"Requested final response schema:\n{requested_schema}\n"
                "Use the available MCP tools when they are needed. Never fabricate tool results or sources. "
                "If no tool is available, clearly distinguish unsupported claims from verified facts."
            )
        ),
    ]


async def invoke_agent_with_mcp_tools(
    model: Any,
    messages: list[BaseMessage],
    allowed_tool_names: list[str],
    trace_id: str,
    thread_id: str,
    actor: str,
    event_store: ZooStore | None = None,
) -> BaseMessage:
    if not allowed_tool_names:
        return model.invoke(messages)
    loaded_tools = await load_mcp_tools()
    selected_tools = [tool for tool in loaded_tools if tool.name in allowed_tool_names]
    return await invoke_agent_with_tools(
        model, messages, selected_tools, trace_id, thread_id, actor, event_store=event_store
    )


async def invoke_agent_with_tools(
    model: Any,
    messages: list[BaseMessage],
    tools: list[BaseTool],
    trace_id: str,
    thread_id: str,
    actor: str,
    event_store: ZooStore | None = None,
    max_rounds: int = 5,
) -> BaseMessage:
    if not tools:
        return model.invoke(messages)

    tools_by_name = {tool.name: tool for tool in tools}
    model_with_tools = model.bind_tools(tools)
    conversation = list(messages)
    for _ in range(max_rounds):
        response: AIMessage = model_with_tools.invoke(conversation)
        conversation.append(response)
        if not response.tool_calls:
            return response
        for tool_call in response.tool_calls:
            tool = tools_by_name[tool_call["name"]]
            if event_store:
                event_store.add_event(
                    thread_id, trace_id, "mcp.tool.started", tool.name, f"{tool.name} called", "MCP"
                )
            with trace_span("mcp.tool", trace_id, tool_name=tool.name):
                result = await tool.ainvoke(tool_call["args"])
            if event_store:
                event_store.add_event(
                    thread_id, trace_id, "mcp.tool.completed", tool.name, f"{tool.name} completed", "MCP"
                )
                if tool.name == "file_write" and isinstance(tool_call["args"].get("filename"), str):
                    filename = tool_call["args"]["filename"]
                    event_store.add_event(
                        thread_id,
                        trace_id,
                        "artifact.created",
                        actor,
                        f"Created {filename}",
                        filename,
                        {"filename": filename},
                    )
            content = result if isinstance(result, str) else json.dumps(result, default=str)
            conversation.append(ToolMessage(content=content, tool_call_id=tool_call["id"]))
    raise RuntimeError(f"Agent exceeded the {max_rounds}-round tool-call limit")


def build_task_runner_graph(
    model: Any,
    tools: list[BaseTool] | None = None,
    max_concurrency: int = 1,
    checkpointer: Any | None = None,
    collaboration_store: ZooStore | None = None,
) -> CompiledStateGraph:
    if max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")

    semaphore = BoundedSemaphore(max_concurrency)
    concurrency_lock = Lock()
    active_branches = 0
    available_tools = {tool.name: tool for tool in tools or []}
    available_tool_names = set(available_tools) if tools is not None else {"calculator", "file_write", "web_search"}

    def resource_gate(state: RunnerState) -> dict[str, Any]:
        trace_id = state.get("trace_id") or new_trace_id()
        missing = sorted(
            {
                tool_name
                for agent in state["agents"]
                for tool_name in agent.tool_allowlist
                if tool_name not in available_tool_names
            }
        )
        if not missing:
            return {"trace_id": trace_id}

        affected_roles = [
            agent.role for agent in state["agents"] if set(agent.tool_allowlist).intersection(missing)
        ]
        request = ResourceRequest(missing_tools=missing, affected_roles=affected_roles)
        action = interrupt(request.model_dump())
        if action == "cancel":
            raise RuntimeError("Run cancelled at resource request")
        if action == "retry":
            raise RuntimeError("Missing tools are still unavailable; add their MCP servers before retrying")
        if action != "continue_without_tool":
            raise RuntimeError(f"Unknown resource request action: {action}")

        agents = [
            agent.model_copy(update={"tool_allowlist": [tool for tool in agent.tool_allowlist if tool not in missing]})
            for agent in state["agents"]
        ]
        return {"agents": agents, "trace_id": trace_id}

    def dispatch_agents(state: RunnerState) -> list[Send]:
        return [
            Send(
                "execute_agent",
                {
                    "task_config": state["task_config"],
                    "agent": agent,
                    "trace_id": state["trace_id"],
                    "thread_id": state.get("thread_id", state["trace_id"]),
                },
            )
            for agent in sorted(state["agents"], key=lambda item: item.handoff_order)
        ]

    def planning_huddle(state: RunnerState) -> dict[str, list[dict[str, Any]]]:
        if collaboration_store is None:
            return {"collaboration_messages": []}
        plans: list[CollaborationMessage] = []
        collaboration_store.add_event(
            state["thread_id"], state["trace_id"], "zoo.huddle.started", "Message Board", "Planning huddle started"
        )
        for agent in sorted(state["agents"], key=lambda item: item.handoff_order):
            collaboration_store.upsert_agent(
                state["thread_id"], agent.role, "planning", agent.handoff_order, agent.tool_allowlist, agent.system_prompt
            )
            prompt = [
                SystemMessage(
                    content=(
                        f"You are {agent.role}. Publish a public plan for the other agents. "
                        "State your focus, intended tool use, and one question for a peer. "
                        "Do not reveal hidden chain-of-thought. Stay under 700 characters."
                    )
                ),
                HumanMessage(content=json.dumps(state["task_config"].task_input)),
            ]
            with trace_span("zoo.plan", state["trace_id"], role=agent.role):
                response = model.invoke(prompt)
            content = message_content_as_text(response.content).strip()[:2000]
            if content:
                message = CollaborationMessage(
                    trace_id=state["trace_id"],
                    thread_id=state["thread_id"],
                    from_agent=agent.role,
                    message_type="proposal",
                    content=content,
                    round=0,
                )
                collaboration_store.add_message(message)
                collaboration_store.add_event(
                    state["thread_id"], state["trace_id"], "zoo.plan.posted", agent.role, "Posted a work plan", "all"
                )
                plans.append(message)
            collaboration_store.upsert_agent(
                state["thread_id"], agent.role, "waiting", agent.handoff_order, agent.tool_allowlist
            )
        return {"collaboration_messages": [message.model_dump() for message in plans]}

    def execute_agent(state: AgentBranchState) -> dict[str, list[AgentResult]]:
        nonlocal active_branches
        agent = state["agent"]
        if collaboration_store is not None:
            collaboration_store.upsert_agent(
                state["thread_id"],
                agent.role,
                "working",
                agent.handoff_order,
                agent.tool_allowlist,
                agent.system_prompt,
            )
            collaboration_store.add_event(
                state["thread_id"],
                state["trace_id"],
                "agent.started",
                agent.role,
                "Started work",
                metadata={"active": True},
            )
        try:
            with semaphore, trace_span(
                "runner.agent",
                state["trace_id"],
                role=agent.role,
                handoff_order=agent.handoff_order,
                tool_count=len(agent.tool_allowlist),
            ):
                with concurrency_lock:
                    active_branches += 1
                    current_active = active_branches
                emit_event(
                    "runner.concurrency",
                    state["trace_id"],
                    active=current_active,
                    limit=max_concurrency,
                )
                try:
                    messages = build_agent_prompt(state["task_config"], agent)
                    if tools is None:
                        message = asyncio.run(
                            invoke_agent_with_mcp_tools(
                                model,
                                messages,
                                agent.tool_allowlist,
                                state["trace_id"],
                                state["thread_id"],
                                agent.role,
                                event_store=collaboration_store,
                            )
                        )
                    else:
                        selected_tools = [available_tools[name] for name in agent.tool_allowlist]
                        message = asyncio.run(
                            invoke_agent_with_tools(
                                model,
                                messages,
                                selected_tools,
                                state["trace_id"],
                                state["thread_id"],
                                agent.role,
                                event_store=collaboration_store,
                            )
                        )
                finally:
                    with concurrency_lock:
                        active_branches -= 1
        except Exception as error:
            raise RuntimeError(f"Agent '{agent.role}' model invocation failed: {error}") from error

        content = message_content_as_text(message.content).strip()
        if not content:
            raise RuntimeError(f"Agent '{agent.role}' returned an empty response")
        if collaboration_store is not None:
            collaboration_store.upsert_agent(
                state["thread_id"], agent.role, "posting", agent.handoff_order, agent.tool_allowlist
            )
            collaboration_store.add_event(
                state["thread_id"],
                state["trace_id"],
                "agent.output.ready",
                agent.role,
                "Finished work and prepared an observation",
            )
        return {
            "results": [
                AgentResult(role=agent.role, content=content, handoff_order=agent.handoff_order)
            ]
        }

    def finalize(state: RunnerState) -> dict[str, list[AgentResult]]:
        return {"final_results": sorted(state["results"], key=lambda result: result.handoff_order)}

    def collaborate(state: RunnerState) -> dict[str, list[dict[str, Any]]]:
        if collaboration_store is None:
            return {"collaboration_messages": []}
        results = state["final_results"]
        agents_by_role = {agent.role: agent for agent in state["agents"]}
        messages: list[CollaborationMessage] = []
        for result in results:
            message = CollaborationMessage(
                trace_id=state["trace_id"],
                thread_id=state["thread_id"],
                from_agent=result.role,
                message_type="observation",
                content=result.content[:2000],
                round=0,
            )
            collaboration_store.add_message(message)
            collaboration_store.add_event(
                state["thread_id"], state["trace_id"], "zoo.observation.posted", result.role, "Posted an observation", "all"
            )
            collaboration_store.upsert_agent(
                state["thread_id"], result.role, "reviewing", result.handoff_order, agents_by_role[result.role].tool_allowlist
            )
            messages.append(message)

        if len(results) > 1:
            for index, result in enumerate(results):
                target = results[(index + 1) % len(results)]
                prompt = [
                    SystemMessage(
                        content=(
                            f"You are {result.role}. Publish a concise, public critique for {target.role}. "
                            "Do not reveal private chain-of-thought. Identify one claim to verify, one useful point, "
                            "and one concrete revision. Stay under 900 characters."
                        )
                    ),
                    HumanMessage(content=target.content[:3000]),
                ]
                collaboration_store.upsert_agent(
                    state["thread_id"], result.role, "critiquing", result.handoff_order, agents_by_role[result.role].tool_allowlist
                )
                collaboration_store.add_event(
                    state["thread_id"], state["trace_id"], "zoo.critique.started", result.role, f"Reviewing {target.role}", target.role
                )
                with trace_span("zoo.critique", state["trace_id"], role=result.role, target=target.role):
                    response = model.invoke(prompt)
                content = message_content_as_text(response.content).strip()[:2000]
                if content:
                    message = CollaborationMessage(
                        trace_id=state["trace_id"],
                        thread_id=state["thread_id"],
                        from_agent=result.role,
                        to_agent=target.role,
                        message_type="critique",
                        content=content,
                        round=1,
                    )
                    collaboration_store.add_message(message)
                    collaboration_store.add_event(
                        state["thread_id"], state["trace_id"], "zoo.critique.posted", result.role, f"Posted a critique for {target.role}", target.role
                    )
                    emit_event("zoo.message", state["trace_id"], from_agent=result.role, to_agent=target.role, message_type="critique")
                    messages.append(message)

        if messages:
            lead = results[-1]
            collaboration_store.upsert_agent(
                state["thread_id"], lead.role, "deciding", lead.handoff_order, agents_by_role[lead.role].tool_allowlist
            )
            collaboration_store.add_event(
                state["thread_id"], state["trace_id"], "zoo.decision.started", lead.role, "Preparing the public team decision", "all"
            )
            board_excerpt = "\n\n".join(
                f"{message.from_agent} to {message.to_agent}: {message.content[:700]}" for message in messages[-6:]
            )
            decision_prompt = [
                SystemMessage(
                    content=(
                        f"You are {lead.role}, the final spokesperson. Publish a concise team decision based on the public board. "
                        "State consensus, unresolved uncertainty, and the recommended next action. Do not expose chain-of-thought. "
                        "Stay under 1,000 characters."
                    )
                ),
                HumanMessage(content=board_excerpt),
            ]
            with trace_span("zoo.decision", state["trace_id"], role=lead.role):
                response = model.invoke(decision_prompt)
            content = message_content_as_text(response.content).strip()[:2000]
            if content:
                decision = CollaborationMessage(
                    trace_id=state["trace_id"],
                    thread_id=state["thread_id"],
                    from_agent=lead.role,
                    message_type="decision",
                    content=content,
                    round=2,
                )
                collaboration_store.add_message(decision)
                collaboration_store.add_event(
                    state["thread_id"], state["trace_id"], "zoo.decision.posted", lead.role, "Posted the team decision", "all"
                )
                messages.append(decision)

        for result in results:
            collaboration_store.upsert_agent(
                state["thread_id"], result.role, "completed", result.handoff_order, agents_by_role[result.role].tool_allowlist
            )
            collaboration_store.add_event(
                state["thread_id"], state["trace_id"], "agent.completed", result.role, "Agent completed"
            )
        return {"collaboration_messages": [message.model_dump() for message in messages]}

    graph = StateGraph(RunnerState)
    graph.add_node("resource_gate", resource_gate)
    graph.add_node("execute_agent", execute_agent)
    graph.add_node("finalize", finalize)
    graph.add_edge(START, "resource_gate")
    graph.add_edge("execute_agent", "finalize")
    if collaboration_store is not None:
        graph.add_node("planning_huddle", planning_huddle)
        graph.add_node("collaborate", collaborate)
        graph.add_edge("resource_gate", "planning_huddle")
        graph.add_conditional_edges("planning_huddle", dispatch_agents, ["execute_agent"])
        graph.add_edge("finalize", "collaborate")
        graph.add_edge("collaborate", END)
    else:
        graph.add_conditional_edges("resource_gate", dispatch_agents, ["execute_agent"])
        graph.add_edge("finalize", END)
    return graph.compile(checkpointer=checkpointer)


def invoke_task_runner(
    task: TaskConfig,
    agents: list[AgentSpec],
    model: Any,
    max_concurrency: int = 1,
    tools: list[BaseTool] | None = None,
) -> list[AgentResult]:
    if not agents:
        raise ValueError("agents must not be empty")
    result = build_task_runner_graph(
        model,
        tools=tools,
        max_concurrency=max_concurrency,
    ).invoke({"task_config": task, "agents": agents, "results": []})
    return result["final_results"]
