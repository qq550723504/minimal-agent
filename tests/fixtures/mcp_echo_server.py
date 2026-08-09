"""Official MCP SDK echo server used only by transport contract tests."""

from __future__ import annotations

import argparse

from mcp.server import MCPServer


mcp = MCPServer("test-echo")


@mcp.tool()
def echo(message: str) -> dict[str, str]:
    return {"message": message}


@mcp.tool()
def park_energy(park_id: str, window_hours: int = 24) -> dict[str, float | int | str]:
    return {
        "park_id": park_id,
        "window_hours": window_hours,
        "average_kw": 12.5,
        "peak_kw": 18.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=("stdio", "streamable-http"), default="stdio")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.transport == "stdio":
        mcp.run()
    else:
        mcp.run("streamable-http", host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
