from a2a.server.agent_execution import AgentExecutor
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
from starlette.applications import Starlette


def create_agent_card(name: str, description: str, url: str, skill_id: str, skill_name: str) -> AgentCard:
    return AgentCard(
        name=name,
        description=description,
        version="0.1.0",
        default_input_modes=["application/json"],
        default_output_modes=["application/json"],
        capabilities=AgentCapabilities(streaming=False),
        supported_interfaces=[
            AgentInterface(protocol_binding="JSONRPC", url=url, protocol_version="1.0")
        ],
        skills=[
            AgentSkill(
                id=skill_id,
                name=skill_name,
                description=description,
                tags=["multiverse-foundry", "agents"],
                input_modes=["application/json"],
                output_modes=["application/json"],
            )
        ],
    )


def create_a2a_app(executor: AgentExecutor, card: AgentCard) -> Starlette:
    handler = DefaultRequestHandler(executor, InMemoryTaskStore(), card)
    routes = create_agent_card_routes(card)
    routes.extend(create_jsonrpc_routes(handler, "/"))
    return Starlette(routes=routes)
