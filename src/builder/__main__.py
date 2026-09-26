import argparse
import json

from pydantic import ValidationError

from src.builder import load_task_config
from src.builder.service import BuilderOutputError, invoke_builder
from src.graph.ollama import create_builder_model
from src.settings import FoundrySettings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build a validated agent crew from a task config.")
    parser.add_argument("--config", required=True, help="Path to a YAML task configuration file.")
    parser.add_argument("--validate-only", action="store_true", help="Validate and print the task config only.")
    parser.add_argument("--max-attempts", type=int, default=3, help="Maximum structured-output attempts.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_task_config(args.config)
        if args.validate_only:
            output = config.model_dump(exclude_none=True)
        else:
            settings = FoundrySettings()
            agents = invoke_builder(config, create_builder_model(settings), args.max_attempts)
            output = [agent.model_dump() for agent in agents]
    except (BuilderOutputError, OSError, RuntimeError, ValueError, ValidationError) as error:
        raise SystemExit(f"Builder failed: {error}") from error

    print(json.dumps(output, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
