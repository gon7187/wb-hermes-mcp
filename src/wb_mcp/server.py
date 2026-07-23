from mcp.server.fastmcp import FastMCP


def create_server(token: str | None = None) -> FastMCP:
    """Create the WB stdio MCP server.

    The token parameter is reserved for the SDK gateway added in the next task.
    """
    return FastMCP("wb_mcp")


def main() -> None:
    """Start the WB MCP server over standard input and output."""
    create_server().run(transport="stdio")
