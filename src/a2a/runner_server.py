import asyncio
import json
from typing import Any
from uuid import uuid4

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from langgraph.types import Command

from src.a2a.common import create_a2a_app, create_agent_card
from src.builder.schema import AgentSpec
from src.config_schema import TaskConfig
from src.graph.checkpoint import sqlite_checkpointer
from src.graph.ollama import create_chat_model
from src.graph.runner import build_task_runner_graph
from src.settings import FoundrySettings
from src.telemetry import emit_event, new_trace_id, trace_span
from src.zoo.storage import ZooStore


def run_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    settings = FoundrySettings()
    settings.foundry_data_dir.mkdir(parents=True, exist_ok=True)
    thread_id = payload.get("thread_id") or str(uuid4())
    trace_id = payload.get("trace_id") or new_trace_id()
    store = ZooStore(settings.foundry_data_dir / "zoo.sqlite")
    emit_event("runner.request", trace_id, thread_id=thread_id)
    store.add_event(thread_id, trace_id, "runner.received", "Runner", "Crew received over A2A")
    with sqlite_checkpointer(settings.foundry_data_dir / "checkpoints.sqlite") as checkpointer:
        graph = build_task_runner_graph(
            create_chat_model(settings),
            max_concurrency=settings.max_concurrency,
            checkpointer=checkpointer,
            collaboration_store=store,
        )
        config = {"configurable": {"thread_id": thread_id}}
        if resume := payload.get("resume"):
            store.set_run_status(thread_id, "running")
            output = graph.invoke(Command(resume=resume), config=config)
        else:
            task = TaskConfig.model_validate(payload["task"])
            agents = [AgentSpec.model_validate(agent) for agent in payload["agents"]]
            store.create_run(thread_id, trace_id, task.model_dump(mode="json"))
            store.set_run_status(thread_id, "running")
            for agent in agents:
                store.upsert_agent(
                    thread_id,
                    agent.role,
                    "waiting",
                    agent.handoff_order,
                    agent.tool_allowlist,
                    agent.system_prompt,
                )
                store.add_event(
                    thread_id,
                    trace_id,
                    "agent.waiting",
                    agent.role,
                    "Waiting for an inference slot",
                    metadata={"handoff_order": agent.handoff_order},
                )
            with trace_span("runner.graph", trace_id, agent_count=len(agents)):
                output = graph.invoke(
                    {
                        "task_config": task,
                        "agents": agents,
                        "results": [],
                        "trace_id": trace_id,
                        "thread_id": thread_id,
                    },
                    config=config,
                )

    if interrupts := output.get("__interrupt__"):
        result = {
            "status": "paused",
            "thread_id": thread_id,
            "resource_requests": [item.value for item in interrupts],
        }
        store.set_run_status(thread_id, "paused", result)
        return result
    result = {
        "status": "completed",
        "thread_id": thread_id,
        "agents": [agent.model_dump() for agent in output["agents"]],
        "results": [item.model_dump() for item in output["final_results"]],
        "messages": output.get("collaboration_messages", []),
    }
    store.set_run_status(thread_id, "completed", result)
    return result


class RunnerAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        payload = json.loads(context.get_user_input())
        result = await asyncio.to_thread(run_task_payload, payload)
        await event_queue.enqueue_event(new_text_message(json.dumps(result), media_type="application/json"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(new_text_message(json.dumps({"status": "cancelled"})))


_settings = FoundrySettings()
_card = create_agent_card(
    "Multiverse Foundry Runner",
    "Executes validated agent crews through the LangGraph task runner.",
    str(_settings.runner_a2a_public_url).rstrip("/"),
    "run-agent-crew",
    "Run agent crew",
)
app = create_a2a_app(RunnerAgentExecutor(), _card)
