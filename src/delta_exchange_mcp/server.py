from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.tools import account, market


def build_server(cfg: config_mod.Config | None = None) -> FastMCP:
    cfg = cfg or config_mod.load()
    mcp = FastMCP("delta-exchange")
    client = DeltaClient(cfg)

    market.register(mcp, client)
    if cfg.has_credentials:
        account.register(mcp, client)
    return mcp


def main() -> None:
    cfg = config_mod.load()
    mcp = build_server(cfg)
    surface = "market+account" if cfg.has_credentials else "market"
    print(
        f"[delta-exchange-mcp] stdio env={cfg.env} base_url={cfg.base_url} surface={surface}",
        file=sys.stderr,
    )
    mcp.run()
