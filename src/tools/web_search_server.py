import json
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("multiverse-web-search")


def search_wikipedia(query: str, max_results: int = 5) -> list[dict[str, str]]:
    limit = min(max(max_results, 1), 10)
    params = urlencode({"action": "opensearch", "search": query, "limit": limit, "namespace": 0, "format": "json"})
    request = Request(
        f"https://en.wikipedia.org/w/api.php?{params}",
        headers={"User-Agent": "MultiverseFoundry/0.1 educational-project"},
    )
    with urlopen(request, timeout=10) as response:
        payload: Any = json.load(response)
    if not isinstance(payload, list) or len(payload) != 4:
        raise RuntimeError("Search provider returned an invalid response")
    titles, descriptions, urls = payload[1], payload[2], payload[3]
    return [
        {"title": title, "description": description, "url": url}
        for title, description, url in zip(titles, descriptions, urls, strict=True)
    ]


@mcp.tool(name="web_search")
def web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    """Search Wikipedia and return titles, descriptions, and source URLs."""
    return search_wikipedia(query, max_results)


if __name__ == "__main__":
    mcp.run(transport="stdio")
