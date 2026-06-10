from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp import debug_log
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.tools import account, market


def build_server(cfg: config_mod.Config | None = None) -> FastMCP:
    cfg = cfg or config_mod.load()
    mcp = FastMCP("delta-exchange")
    client = DeltaClient(cfg)

    log_path = debug_log.configure(cfg)

    market.register(mcp, client)
    if cfg.has_credentials:
        account.register(mcp, client)

    if log_path is not None:

        @mcp.tool()
        def get_debug_status() -> dict[str, object]:
            """Whether debug logging is on and the absolute path of the current log file.

            Use this to tell the user where to find / fetch the HTTP debug log.
            """
            return {"enabled": True, "log_path": str(log_path)}

    return mcp


def main() -> None:
    cfg = config_mod.load()
    mcp = build_server(cfg)
    surface = "market+account" if cfg.has_credentials else "market"
    banner = f"[delta-exchange-mcp] stdio env={cfg.env} base_url={cfg.base_url} surface={surface}"
    if cfg.debug:
        log_path = debug_log.configure(cfg)  # idempotent — returns the same path
        banner += f" debug=on log={log_path}"
    print(banner, file=sys.stderr)
    mcp.run()
