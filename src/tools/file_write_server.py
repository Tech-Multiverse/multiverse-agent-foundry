import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP


mcp = FastMCP("multiverse-file-write")
_ALLOWED_SUFFIXES = {".json", ".md", ".txt"}


def write_data_file(filename: str, content: str, artifact_dir: str | Path | None = None) -> str:
    root = Path(artifact_dir or os.environ.get("FOUNDRY_ARTIFACT_DIR", "artifacts")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if Path(filename).name != filename:
        raise ValueError("filename must not contain a directory path")
    if Path(filename).suffix.lower() not in _ALLOWED_SUFFIXES:
        raise ValueError("filename must end in .json, .md, or .txt")
    target = (root / filename).resolve()
    if target.parent != root:
        raise ValueError("filename resolves outside the data directory")
    target.write_text(content, encoding="utf-8")
    return str(target)


@mcp.tool(name="file_write")
def file_write(filename: str, content: str) -> str:
    """Write UTF-8 content to a safe file under the Foundry artifact directory."""
    return write_data_file(filename, content)


if __name__ == "__main__":
    mcp.run(transport="stdio")
