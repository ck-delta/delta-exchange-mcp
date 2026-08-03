"""Interactive `login` for people already sitting at a terminal.

One of several front-ends onto the same shared settings file — the in-chat form in
`form` fills exactly the same three keys for people who never open a terminal, and
hand-editing the file fills them too. The checking and writing live in `credentials`
so all of them behave identically.

This refuses to run without a terminal. `getpass` on its own does not: piping into it
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

from delta_exchange_mcp import credentials, store
from delta_exchange_mcp.config import BASE_URLS, DASHBOARDS, DEFAULT_ENV


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
        result = asyncio.run(credentials.check(env, key, secret))
        if not result.reachable:
            # A flaky connection must not cost someone a key they typed correctly.
            print(f"  {result.detail}\n  saving anyway, unverified", file=sys.stderr)
        elif not result.ok:
            print(f"  {result.detail}\n\nNothing was saved.", file=sys.stderr)
            return 1
        else:
            print(f"  ok{' — ' + result.detail if result.detail else ''}")

    problem = credentials.save(env, key, secret)
    if problem is not None:
        print(problem, file=sys.stderr)
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
