import json
from typing import Any

import httpx
from a2a.client import A2ACardResolver, ClientConfig, ClientFactory
from a2a.helpers import get_message_text, new_text_message
from a2a.types import Role, SendMessageRequest

from src.telemetry import new_trace_id, trace_span


async def send_json_message(base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    trace_id = payload.setdefault("trace_id", new_trace_id())
    with trace_span("a2a.request", trace_id):
        async with httpx.AsyncClient(timeout=300) as http_client:
            card = await A2ACardResolver(http_client, base_url).get_agent_card()
            card.supported_interfaces[0].url = base_url
            client = ClientFactory(ClientConfig(streaming=False, httpx_client=http_client)).create(card)
            request = SendMessageRequest(
                message=new_text_message(json.dumps(payload), media_type="application/json", role=Role.ROLE_USER)
            )
            async for response in client.send_message(request):
                if response.HasField("message"):
                    return json.loads(get_message_text(response.message))
    raise RuntimeError(f"A2A agent at {base_url} returned no message")
