import asyncio
import json
from typing import Any

from a2a.helpers import new_text_message
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue

from src.a2a.client import send_json_message
from src.a2a.common import create_a2a_app, create_agent_card
from src.builder.service import invoke_builder
from src.config_schema import TaskConfig
from src.graph.ollama import create_builder_model
from src.settings import FoundrySettings
from src.telemetry import new_trace_id, trace_span
from src.zoo.events import publish_run_event


async def build_and_dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    settings = FoundrySettings()
    trace_id = payload.get("trace_id") or new_trace_id()
    thread_id = payload.get("thread_id") or trace_id
    task = TaskConfig.model_validate(payload["task"])
    publish_run_event(thread_id, trace_id, "builder.validated", "Builder", "Task configuration validated")
    publish_run_event(thread_id, trace_id, "builder.model.started", "Builder", "Asking Ollama to design the crew", "Ollama")
    with trace_span("builder.generate_crew", trace_id, task_type=task.task_type):
        agents = await asyncio.to_thread(
            invoke_builder,
            task,
            create_builder_model(settings),
            payload.get("max_attempts", 3),
        )
    for agent in agents:
        publish_run_event(
            thread_id,
            trace_id,
            "builder.agent.created",
            "Builder",
            f"Created {agent.role}",
            agent.role,
            handoff_order=agent.handoff_order,
            tools=agent.tool_allowlist,
        )
    runner_payload = {
        "task": task.model_dump(mode="json"),
        "agents": [agent.model_dump(mode="json") for agent in agents],
        "thread_id": payload.get("thread_id"),
        "trace_id": trace_id,
    }
    publish_run_event(thread_id, trace_id, "a2a.runner.dispatch", "Builder", "Dispatching crew to Runner over A2A", "Runner", agent_count=len(agents))
    with trace_span("builder.dispatch_runner", trace_id, agent_count=len(agents)):
        return await send_json_message(str(settings.runner_a2a_url).rstrip("/"), runner_payload)


class BuilderAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        payload = json.loads(context.get_user_input())
        result = await build_and_dispatch(payload)
        await event_queue.enqueue_event(new_text_message(json.dumps(result), media_type="application/json"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        await event_queue.enqueue_event(new_text_message(json.dumps({"status": "cancelled"})))


_settings = FoundrySettings()
_card = create_agent_card(
    "Multiverse Foundry Builder",
    "Designs a validated task-specific crew and dispatches it to the runner over A2A.",
    str(_settings.builder_a2a_public_url).rstrip("/"),
    "build-and-run-crew",
    "Build and run agent crew",
)
app = create_a2a_app(BuilderAgentExecutor(), _card)
