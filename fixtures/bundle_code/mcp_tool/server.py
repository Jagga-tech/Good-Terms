from mcp.server.mcpserver import MCPServer

import core

mcp = MCPServer("terms-check")


@mcp.tool()
def check_stores(stores: list[str]) -> str:
    """Check stores against the deal-breakers this buyer saved in Terms Check.

    Returns, for each store, whether the store confirms each deal-breaker, rejects it or
    doesn't say, with the evidence and a check ID. Call this before preparing a checkout
    at any store. Pass store domains or product links.
    """
    return core.check(stores)


if __name__ == "__main__":
    import sys

    mcp.run(transport="streamable-http" if "--http" in sys.argv else "stdio")
