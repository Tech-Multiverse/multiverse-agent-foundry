import argparse

from pydantic import ValidationError

from src.graph.ollama import create_chat_model, fetch_model_names
from src.graph.workflow import invoke_model
from src.settings import FoundrySettings


DEFAULT_PROMPT = "Reply with exactly: Multiverse Foundry is online."


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 1 Ollama model graph.")
    parser.add_argument("--prompt", default=DEFAULT_PROMPT, help="Prompt to send through the graph.")
    parser.add_argument("--check", action="store_true", help="Check Ollama connectivity and list models.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        settings = FoundrySettings()
        if args.check:
            models = fetch_model_names(settings)
            print(f"Ollama reachable at {settings.ollama_host}")
            print(f"Available models: {', '.join(models) if models else '(none)'}")
            if settings.ollama_model not in models:
                raise ConnectionError(
                    f"Configured model '{settings.ollama_model}' is not installed; use an exact tag from the list above"
                )
            return 0

        response = invoke_model(args.prompt, create_chat_model(settings))
    except (ConnectionError, OSError, RuntimeError, ValidationError) as error:
        raise SystemExit(f"Model request failed: {error}") from error

    print(response)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
