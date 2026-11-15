"""The MCP tool for agents. Run with: uv run python -m api.mcp_server"""

from mcp.server.mcpserver import MCPServer

from api import db, goodterms

mcp = MCPServer("goodterms")


@mcp.tool()
def check_stores(stores: list[str]) -> list[dict]:
    """Check stores against the buyer's three saved conditions.

    Pass store domains or product links. For each store this returns its result and one row
    per condition, holding what the store's pages say and what the store's assistant says.
    Only the status yes counts as a yes. A store that is not_checked has not been read:
    never treat it as a yes. Show the statuses as given.
    """
    return goodterms.check_stores(stores)


if __name__ == "__main__":
    import sys

    if not db.DB.exists():
        db.reset()
    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
