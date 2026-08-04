from __future__ import annotations

import argparse
import sys
from dataclasses import replace

import anyio
import mcp.types as types
from mcp.server.fastmcp import FastMCP
from mcp.server.lowlevel import NotificationOptions
from mcp.server.models import InitializationOptions
from mcp.server.session import ServerSession
from mcp.server.stdio import stdio_server

from delta_exchange_mcp import audit_log
from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp import credentials, debug_log
from delta_exchange_mcp import form
from delta_exchange_mcp import store
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.tools import account, market, trading
from delta_exchange_mcp.version import PACKAGE_VERSION

_ENV_HELP = """\
configuration (the settings below, from your MCP client or the shared file):
  DELTA_MCP_ENV         india_prod (default), india_testnet, india_devnet
  DELTA_API_KEY         optional; requires DELTA_API_SECRET for the account tools
  DELTA_API_SECRET      required alongside DELTA_API_KEY
  DELTA_MCP_MODE        read (default) or trade; trade registers the mutating tools
                        when both credentials are set
  DELTA_MCP_DEBUG       1/true/yes/on to trace HTTP requests and responses to a file
  DELTA_MCP_DEBUG_FILE  override the debug log path
  DELTA_MCP_AUDIT       off/false/0/no to disable the trade-mode audit log
  DELTA_MCP_AUDIT_FILE  override the audit log path
  DELTA_MCP_CONFIG_FILE override the shared settings file path

Each is read from the environment your MCP client launched this server with, and
falls back to a shared file at ~/.delta-exchange-mcp/config.env that every client
on this machine reads. That file is created with instructions in it on first run,
so an API key is set once rather than pasted into each client's own config.
DELTA_MCP_MODE is the exception. That name is never read from the shared file, because a
value there would arm order placement in every client on the machine at once. Trading is
stored per client instead, under DELTA_MCP_MODE_<CLIENT> keyed on the name the client
gives in the handshake — which is what the in-chat form writes, and what the first
tools/list of a session applies.

Prod and testnet API keys are separate; DELTA_MCP_ENV must match the dashboard the
key was created on. The server speaks MCP over stdio and is normally launched by a
client rather than by hand.
"""

# Sent to the model once per session, which is the only channel that reaches it in the
# state that matters most: no key configured, so no account tool exists to carry a hint
# on its own description. Without this, "what is my BTC position" on a fresh install gets
# answered with "I have no tool for that" and no offer to fix it.
INSTRUCTIONS = """\
Delta Exchange India. Market data needs no setup and always works. The user's own account
— positions, orders, fills, balances — is readable only when an API key is configured,
and placing orders additionally requires them to set mode to trade in their MCP client.

If the user asks about their own account and no account tool is available, call
setup_credentials: it opens a form they type the key into. Never ask for an API key or
secret in the conversation, and never accept one sent as a message — anything sent that
way is stored in the conversation and visible to you. get_connection_status reports
whether a key is configured, which environment it points at, and whether this client
still needs restarting.
"""


def connected_client_name(mcp: FastMCP) -> str:
    """What the connected client called itself in the handshake, or "" before there is one.

    Only reachable from inside a request: the session hangs off the request context, and
    reading that context outside one raises rather than returning None.
    """
    try:
        session = mcp._mcp_server.request_context.session
    except LookupError:
        return ""
    params = session.client_params
    return params.clientInfo.name if params and params.clientInfo else ""


def build_server(cfg: config_mod.Config | None = None) -> FastMCP:
    cfg = cfg or config_mod.load()
    mcp = FastMCP("delta-exchange", instructions=INSTRUCTIONS)
    # FastMCP has no version argument, and the server it wraps reports the mcp SDK's own
    # version when this is left unset — so clients would see the SDK version as ours.
    mcp._mcp_server.version = PACKAGE_VERSION
    client = DeltaClient(cfg)

    log_path = debug_log.configure(cfg)

    market.register(mcp, client)

    # The config the registered surface is actually running on. It stops being the one
    # loaded at startup when a key saved through the form brings the account tools up
    # without a restart.
    live = cfg
    restart_pending = False

    async def activate(session: ServerSession) -> bool:
        """Bring the tool list up to date after a credential was saved.

        Returns True when nothing further is needed, so the caller can say so instead of
        asking someone to restart the client they are in the middle of talking to.

        Registering the tools is only half of it. The client read the tool list once, at
        startup, and re-reads it only when told the list changed — so the notification is
        what actually makes them reachable, and it is sent here because it belongs to the
        same event as the registration.

        A key replacing an existing one changes no tools and reports False, and means it:
        the account tools already registered hold a client built from the key being
        replaced, and nothing here rebuilds them, so a rotation does need the restart.
        """
        nonlocal live, restart_pending
        if live.has_credentials:
            restart_pending = True
            return False
        fresh = config_mod.load()
        if not fresh.has_credentials:
            return False
        account.register(mcp, DeltaClient(fresh))
        live = fresh
        # Trading is deliberately left out. Arming real order placement should follow
        # from the user editing their own client config, and that edit already implies
        # the restart — it must not follow from a form submitted inside a chat.
        restart_pending = fresh.mode == "trade"
        await session.send_tool_list_changed()
        return not restart_pending

    # Registered whether or not credentials are set: someone with none needs to add a
    # first key, and someone with one still rotates it or switches environment.
    form.register(mcp, activate)
    if cfg.has_credentials:
        account.register(mcp, client)

    @mcp.tool()
    def get_connection_status() -> dict[str, object]:
        """Whether an API key is configured, where it points, and if a restart is due.

        Use this to answer "am I connected?", and to check whether a key the user just
        saved has taken effect. Returns no key or secret value.
        """
        # Read the file rather than report startup state: another client on this machine
        # shares it, so a key can appear without this process having been told.
        stored = config_mod.load()
        overridden = credentials.overridden_by_client()
        # What this client is entitled to after its next start, which is not what it is
        # running now if trading was chosen in the form during this session.
        entitled = config_mod.mode_for_client(connected_client_name(mcp))
        trade_pending = entitled == "trade" and live.mode != "trade"
        return {
            "environment": live.env,
            "credentials_configured": stored.has_credentials,
            "account_tools_available": live.has_credentials,
            "mode": live.mode,
            "mode_after_restart": entitled,
            # A restart re-reads the file, so it cannot help when this client passes its
            # own value on every launch. `overridden_by_client` is then what to act on:
            # those names have to come out of the client's own MCP entry.
            "restart_required": not overridden
            and stored.has_credentials
            and (restart_pending or trade_pending or not live.has_credentials),
            "overridden_by_client": overridden,
        }

    trade_audit = None

    def arm_trading(armed: config_mod.Config, armed_client: DeltaClient) -> None:
        """Register the mutating tools, with the audit log that has to accompany them."""
        nonlocal trade_audit, live
        trade_audit = audit_log.configure(armed)
        trading.register(mcp, armed_client, trade_audit)
        live = armed

        @mcp.tool()
        def get_trading_status() -> dict[str, object]:
            """Trading mode status and the audit log path (None if auditing is disabled).

            Use this to tell the user that mutations are enabled and where the audit log lives.
            """
            return {
                "mode": "trade",
                "audit_log_path": str(trade_audit.path) if trade_audit else None,
            }

    if cfg.has_credentials and cfg.mode == "trade":
        arm_trading(cfg, client)

    # A trading mode chosen in the form is stored under the choosing client's own name,
    # and a client only says who it is during the handshake — after this function has
    # finished building the tool list. So the first `tools/list` of a session is where a
    # scoped entitlement gets applied, before the list is produced, which puts the
    # mutating tools in that very first listing rather than behind a later notification.
    #
    # Decided once per session on purpose. Choosing trade mid-conversation writes the key
    # but must not arm order placement in the session that wrote it: that still waits for
    # the restart, which is the deliberate act this whole gate exists to require.
    entitlement_checked = False
    list_tools = mcp._mcp_server.request_handlers[types.ListToolsRequest]

    async def arm_before_listing(req: types.ListToolsRequest) -> types.ServerResult:
        nonlocal entitlement_checked
        if not entitlement_checked:
            entitlement_checked = True
            name = connected_client_name(mcp)
            if (
                name
                and trade_audit is None
                and live.has_credentials
                and config_mod.mode_for_client(name) == "trade"
            ):
                armed = replace(live, mode="trade")
                arm_trading(armed, DeltaClient(armed))
        return await list_tools(req)

    mcp._mcp_server.request_handlers[types.ListToolsRequest] = arm_before_listing

    if log_path is not None:

        @mcp.tool()
        def get_debug_status() -> dict[str, object]:
            """Whether debug logging is on and the absolute path of the current log file.

            Use this to tell the user where to find / fetch the HTTP debug log.
            """
            return {"enabled": True, "log_path": str(log_path)}

    return mcp


def initialization_options(mcp: FastMCP) -> InitializationOptions:
    """What this server tells a client about itself, declaring a changeable tool list.

    FastMCP's own `run_stdio_async` builds these with every notification flag off, so the
    server would advertise `tools.listChanged: false`. A client told that has no reason to
    re-read the tool list, which makes the notification sent when a saved credential
    brings the account tools up a no-op — leaving the restart it exists to avoid as the
    only way through.
    """
    return mcp._mcp_server.create_initialization_options(
        NotificationOptions(tools_changed=True)
    )


async def serve(mcp: FastMCP) -> None:
    """Serve over stdio, the only transport."""
    async with stdio_server() as (read_stream, write_stream):
        await mcp._mcp_server.run(
            read_stream, write_stream, initialization_options(mcp)
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="delta-exchange-mcp",
        description=(
            "MCP server for Delta Exchange India: market data and account reads, "
            "served to an MCP client over stdio."
        ),
        epilog=_ENV_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"delta-exchange-mcp {PACKAGE_VERSION}",
    )
    # Optional, so a bare invocation still means "serve" — that is how every MCP client
    # launches this, and it must never become a subcommand.
    sub = parser.add_subparsers(dest="command")
    login_parser = sub.add_parser(
        "login",
        help="store your API key in the shared settings file, once for every client",
    )
    login_parser.add_argument(
        "--no-verify",
        action="store_true",
        help="skip the check against Delta and save whatever is entered",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)

    if args.command == "login":
        from delta_exchange_mcp import login

        raise SystemExit(login.run(verify=not args.no_verify))

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
    if cfg.config_file is not None:
        banner += f" config={cfg.config_file}"
    if trade_on:
        audit = audit_log.configure(cfg)  # idempotent: appends to the same file path
        banner += f" audit={audit.path if audit else 'off'}"
    if cfg.debug:
        log_path = debug_log.configure(cfg)  # idempotent — returns the same path
        if log_path is not None:  # configure returns None if the log file can't be opened
            banner += f" debug=on log={log_path}"
    print(banner, file=sys.stderr)
    insecure = store.insecure_permissions()
    if insecure is not None:
        print(f"[delta-exchange-mcp] {insecure}", file=sys.stderr)
    if cfg.partial_credentials:
        supplied = "DELTA_API_KEY" if cfg.api_key else "DELTA_API_SECRET"
        missing = "DELTA_API_SECRET" if cfg.api_key else "DELTA_API_KEY"
        print(
            f"[delta-exchange-mcp] {supplied} is set but {missing} is not. Both are "
            "required to sign a request, so the account tools are NOT available and only "
            "market data will work.",
            file=sys.stderr,
        )
    anyio.run(serve, mcp)
