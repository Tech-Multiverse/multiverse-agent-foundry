import io

import pytest
from langchain_core.messages import AIMessage

from src.graph.ollama import fetch_model_names
from src.graph.workflow import invoke_model
from src.settings import FoundrySettings


class FakeModel:
    def invoke(self, prompt: str) -> AIMessage:
        return AIMessage(content=f"Model received: {prompt}")


class FakeResponse(io.BytesIO):
    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        self.close()


def test_single_node_graph_returns_model_response() -> None:
    assert invoke_model("hello", FakeModel()) == "Model received: hello"


def test_model_errors_are_reported_at_the_graph_boundary() -> None:
    class FailingModel:
        def invoke(self, prompt: str) -> AIMessage:
            raise ConnectionError("offline")

    with pytest.raises(RuntimeError, match="Ollama model invocation failed: offline"):
        invoke_model("hello", FailingModel())


def test_settings_load_ollama_environment(monkeypatch) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://ollama.internal:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "test-model")
    monkeypatch.setenv("MAX_CONCURRENCY", "2")

    settings = FoundrySettings(_env_file=None)

    assert str(settings.ollama_host) == "http://ollama.internal:11434/"
    assert settings.ollama_model == "test-model"
    assert settings.max_concurrency == 2


def test_connectivity_check_lists_models(monkeypatch) -> None:
    def fake_urlopen(url: str, timeout: float) -> FakeResponse:
        assert url == "http://ollama.internal:11434/api/tags"
        assert timeout == 2.0
        return FakeResponse(b'{"models":[{"name":"qwen3"},{"name":"llama3.1:8b"}]}')

    monkeypatch.setattr("src.graph.ollama.urlopen", fake_urlopen)
    settings = FoundrySettings(
        ollama_host="http://ollama.internal:11434",
        ollama_model="qwen3",
        _env_file=None,
    )

    assert fetch_model_names(settings, timeout=2.0) == ["qwen3", "llama3.1:8b"]
