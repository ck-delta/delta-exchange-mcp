"""Interactive `login` for people already sitting at a terminal.

Writes the same shared settings file that hand-editing uses, so this is one of several
ways to fill one store rather than a mechanism of its own.

It refuses to run without a terminal. `getpass` on its own does not: piping into it
prints a warning and then reads stdin anyway, so `echo $KEY | delta-exchange-mcp login`
would quietly succeed. That is exactly the shape an agent trying to be helpful would
reach for, and it would put the secret into shell history and into the agent's
transcript — the two places this whole design exists to keep it out of.
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys
from dataclasses import dataclass

import httpx
from dotenv import set_key

from delta_exchange_mcp import store
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.config import BASE_URLS, DEFAULT_ENV, Config
from delta_exchange_mcp.errors import DeltaApiError

DASHBOARDS = {
    "india_prod": "https://www.delta.exchange/app/account/manageapikeys",
    "india_testnet": "https://demo.delta.exchange/app/account/manageapikeys",
}


@dataclass(frozen=True)
class Check:
    """Outcome of asking Delta whether the credentials work."""

    ok: bool
    reachable: bool
    detail: str


async def _check(env: str, key: str, secret: str) -> Check:
    """One authenticated call, so four documented failures surface here and not later.

    A wrong environment for the key, an unwhitelisted IP, a key without Read Data, and
    a truncated paste are all invisible until something signs a request. Doing it while
    the person is still holding the key turns each into a message they can act on.
    """
    cfg = Config(env=env, base_url=BASE_URLS[env], api_key=key, api_secret=secret)  # type: ignore[arg-type]
    client = DeltaClient(cfg)
    try:
        profile = await client.get("/profile", auth=True)
    except DeltaApiError as exc:
        return Check(ok=False, reachable=True, detail=str(exc))
    except httpx.HTTPError as exc:
        return Check(ok=False, reachable=False, detail=f"could not reach Delta: {exc}")
    else:
        who = ""
        if isinstance(profile, dict):
            who = str(profile.get("email") or profile.get("id") or "")
        return Check(ok=True, reachable=True, detail=who)
    finally:
        await client.aclose()


def _ask_env() -> str | None:
    prompt = f"Environment {'/'.join(sorted(BASE_URLS))}\n  [{DEFAULT_ENV}]: "
    answer = input(prompt).strip().lower() or DEFAULT_ENV
    if answer not in BASE_URLS:
        print(f"  not an environment: {answer}", file=sys.stderr)
        return None
    return answer


def run(verify: bool = True) -> int:
    """Prompt for credentials and write them to the shared settings file."""
    if not sys.stdin.isatty():
        print(
            "login needs a terminal. Run it yourself rather than through a pipe or an "
            "assistant — piping would put your API secret in shell history.",
            file=sys.stderr,
        )
        return 2

    path = store.ensure()
    if path is None:
        print(f"cannot write {store.path()}", file=sys.stderr)
        return 1

    print(f"Storing credentials in {path}")
    print("Every MCP client on this machine reads it. Leave blank to keep what is there.\n")

    try:
        env = _ask_env()
        if env is None:
            return 1
        print(f"  create a key at {DASHBOARDS.get(env, DASHBOARDS[DEFAULT_ENV])}")
        print('  the "Read Data" permission is enough unless you intend to trade\n')
        key = getpass.getpass("API key (hidden): ").strip()
        secret = getpass.getpass("API secret (hidden): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\ncancelled, nothing written", file=sys.stderr)
        return 1

    if not key or not secret:
        print(
            "both a key and its secret are needed — one without the other leaves the "
            "server on market data only",
            file=sys.stderr,
        )
        return 1

    if verify:
        print(f"\nChecking against {BASE_URLS[env]} ...")
        result = asyncio.run(_check(env, key, secret))
        if not result.reachable:
            # A flaky connection must not cost someone a key they typed correctly.
            print(f"  {result.detail}\n  saving anyway, unverified", file=sys.stderr)
        elif not result.ok:
            print(f"  {result.detail}\n\nNothing was saved.", file=sys.stderr)
            return 1
        else:
            print(f"  ok{' — ' + result.detail if result.detail else ''}")

    for name, value in (
        ("DELTA_MCP_ENV", env),
        ("DELTA_API_KEY", key),
        ("DELTA_API_SECRET", secret),
    ):
        # set_key edits one line in place, leaving the template's comments and any other
        # settings intact, so hand-editing and this command can share one file.
        written, _, _ = set_key(str(path), name, value)
        if not written:
            print(f"could not write {name} to {path}", file=sys.stderr)
            return 1

    print(f"\nSaved to {path}. Restart your MCP client.")

    shadowing = [
        name
        for name in ("DELTA_API_KEY", "DELTA_API_SECRET", "DELTA_MCP_ENV")
        if (os.environ.get(name) or "").strip()
    ]
    if shadowing:
        # A client launched from this shell inherits these, and a client's own value
        # always wins over the file — so the key just saved would appear to do nothing.
        print(
            f"\nNote: {', '.join(shadowing)} is exported in this shell and takes "
            "precedence over the file for any client launched from here.",
            file=sys.stderr,
        )
    return 0
