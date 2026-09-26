import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from langchain_ollama import ChatOllama

from src.builder.schema import AgentCrew
from src.settings import FoundrySettings


def create_chat_model(settings: FoundrySettings) -> ChatOllama:
    return ChatOllama(
        base_url=str(settings.ollama_host).rstrip("/"),
        model=settings.ollama_model,
        temperature=0,
    )


def create_builder_model(settings: FoundrySettings) -> ChatOllama:
    return ChatOllama(
        base_url=str(settings.ollama_host).rstrip("/"),
        model=settings.ollama_model,
        temperature=0,
        format=AgentCrew.model_json_schema(),
    )


def fetch_model_names(settings: FoundrySettings, timeout: float = 5.0) -> list[str]:
    url = f"{str(settings.ollama_host).rstrip('/')}/api/tags"
    try:
        with urlopen(url, timeout=timeout) as response:
            payload: Any = json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        raise ConnectionError(f"Unable to reach Ollama at {settings.ollama_host}: {error}") from error

    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, list):
        raise ConnectionError(f"Ollama returned an invalid model list from {url}")

    return [model["name"] for model in models if isinstance(model, dict) and isinstance(model.get("name"), str)]
