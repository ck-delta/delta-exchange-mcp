from __future__ import annotations

import sys

from mcp.server.fastmcp import FastMCP

from delta_exchange_mcp import audit_log
from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp import debug_log
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.tools import account, market, trading


def build_server(cfg: config_mod.Config | None = None) -> FastMCP:
    cfg = cfg or config_mod.load()
    mcp = FastMCP("delta-exchange")
    client = DeltaClient(cfg)

    log_path = debug_log.configure(cfg)

    market.register(mcp, client)
    if cfg.has_credentials:
        account.register(mcp, client)

    trade_audit = None
    if cfg.has_credentials and cfg.mode == "trade":
        trade_audit = audit_log.configure(cfg)
        trading.register(mcp, client, trade_audit)

        @mcp.tool()
        def get_trading_status() -> dict[str, object]:
            """Trading mode status and the audit log path (None if auditing is disabled).

            Use this to tell the user that mutations are enabled and where the audit log lives.
            """
            return {
                "mode": cfg.mode,
                "audit_log_path": str(trade_audit.path) if trade_audit else None,
            }

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
    trade_on = cfg.has_credentials and cfg.mode == "trade"
    if trade_on:
        surface += "+trade"
    banner = (
        f"[delta-exchange-mcp] stdio env={cfg.env} base_url={cfg.base_url} "
        f"mode={cfg.mode} surface={surface}"
    )
    if trade_on:
        audit = audit_log.configure(cfg)  # idempotent: appends to the same file path
        banner += f" audit={audit.path if audit else 'off'}"
    if cfg.debug:
        log_path = debug_log.configure(cfg)  # idempotent — returns the same path
        if log_path is not None:  # configure returns None if the log file can't be opened
            banner += f" debug=on log={log_path}"
    print(banner, file=sys.stderr)
    mcp.run()
