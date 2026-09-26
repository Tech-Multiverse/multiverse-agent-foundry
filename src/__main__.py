import argparse
import json
from uuid import uuid4

from langgraph.types import Command
from pydantic import ValidationError

from src.builder import load_task_config
from src.builder.service import BuilderOutputError, invoke_builder
from src.graph.checkpoint import sqlite_checkpointer
from src.graph.ollama import create_builder_model, create_chat_model
from src.graph.runner import build_task_runner_graph
from src.settings import FoundrySettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and run a Multiverse Foundry agent crew.")
    parser.add_argument("--config", required=True, help="Path to a YAML task configuration file.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum builder output attempts.")
    parser.add_argument("--thread-id", help="Persistent LangGraph thread ID; generated when omitted.")
    parser.add_argument(
        "--resume",
        choices=["retry", "continue_without_tool", "cancel"],
        help="Resume a paused resource request for the supplied thread ID.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    thread_id = args.thread_id or str(uuid4())
    if args.resume and not args.thread_id:
        raise SystemExit("Foundry run failed: --resume requires --thread-id")

    try:
        settings = FoundrySettings()
        settings.foundry_data_dir.mkdir(parents=True, exist_ok=True)
        with sqlite_checkpointer(settings.foundry_data_dir / "checkpoints.sqlite") as checkpointer:
            graph = build_task_runner_graph(
                create_chat_model(settings),
                max_concurrency=settings.max_concurrency,
                checkpointer=checkpointer,
            )
            run_config = {"configurable": {"thread_id": thread_id}}
            if args.resume:
                output = graph.invoke(Command(resume=args.resume), config=run_config)
            else:
                task = load_task_config(args.config)
                agents = invoke_builder(task, create_builder_model(settings), args.max_attempts)
                output = graph.invoke(
                    {"task_config": task, "agents": agents, "results": []},
                    config=run_config,
                )
    except (BuilderOutputError, OSError, RuntimeError, ValueError, ValidationError) as error:
        raise SystemExit(f"Foundry run failed: {error}") from error

    if interrupts := output.get("__interrupt__"):
        print(
            json.dumps(
                {
                    "status": "paused",
                    "thread_id": thread_id,
                    "resource_requests": [item.value for item in interrupts],
                },
                indent=2,
            )
        )
        return 0

    print(
        json.dumps(
            {
                "status": "completed",
                "thread_id": thread_id,
                "agents": [agent.model_dump() for agent in output["agents"]],
                "results": [result.model_dump() for result in output["final_results"]],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
