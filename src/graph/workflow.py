from typing import Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph


class ModelState(TypedDict):
    prompt: str
    response: str


def message_content_as_text(content: str | list[str | dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    return "".join(part if isinstance(part, str) else str(part.get("text", "")) for part in content)


def build_model_graph(model: Any) -> CompiledStateGraph:
    def call_model(state: ModelState) -> dict[str, str]:
        try:
            message: BaseMessage = model.invoke(state["prompt"])
        except Exception as error:
            raise RuntimeError(f"Ollama model invocation failed: {error}") from error
        return {"response": message_content_as_text(message.content)}

    graph = StateGraph(ModelState)
    graph.add_node("call_model", call_model)
    graph.add_edge(START, "call_model")
    graph.add_edge("call_model", END)
    return graph.compile()


def invoke_model(prompt: str, model: Any) -> str:
    result = build_model_graph(model).invoke({"prompt": prompt})
    return result["response"]
