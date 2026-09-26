import asyncio
import os
import sys
from typing import Any

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient


_CONNECTIONS: dict[str, dict[str, Any]] = {
    "calculator": {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "src.tools.calculator_server"],
    },
    "file_write": {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "src.tools.file_write_server"],
        "env": {"FOUNDRY_ARTIFACT_DIR": os.environ.get("FOUNDRY_ARTIFACT_DIR", "artifacts")}, 
    },
    "web_search": {
        "transport": "stdio",
        "command": sys.executable,
        "args": ["-m", "src.tools.web_search_server"],
    },
}


async def load_mcp_tools() -> list[BaseTool]:
    return await MultiServerMCPClient(_CONNECTIONS).get_tools()


def load_mcp_tools_sync() -> list[BaseTool]:
    return asyncio.run(load_mcp_tools())
