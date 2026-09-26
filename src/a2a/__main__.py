import argparse
import asyncio
import json
from uuid import uuid4

from src.a2a.client import send_json_message
from src.builder import load_task_config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit a task to the Multiverse Foundry builder over A2A.")
    parser.add_argument("--url", default="http://localhost:8001", help="Builder A2A base URL.")
    parser.add_argument("--config", required=True, help="Path to a YAML task configuration file.")
    parser.add_argument("--thread-id", default=None, help="Optional persistent runner thread ID.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    task = load_task_config(args.config)
    result = asyncio.run(
        send_json_message(
            args.url,
            {
                "task": task.model_dump(mode="json"),
                "thread_id": args.thread_id or str(uuid4()),
            },
        )
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
