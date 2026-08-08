"""Official MCP SDK echo server used only by transport contract tests."""

from __future__ import annotations

import argparse

from mcp.server import MCPServer


mcp = MCPServer("test-echo")


@mcp.tool()
def echo(message: str) -> dict[str, str]:
    return {"message": message}


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
