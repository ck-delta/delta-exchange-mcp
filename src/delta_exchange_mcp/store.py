"""Settings shared by every MCP client on this machine.

An MCP client's own config is an awkward home for an API key. The shape differs per
client, it is JSON or TOML that someone non-technical has to edit without breaking,
the same key has to be pasted again for every client, and the project-scoped variants
(`.cursor/mcp.json`, `.vscode/mcp.json`) are files people commit. This module offers
one plain `KEY=value` file instead, read by whichever client launched the server.

The client's own environment still wins, so the Claude Desktop bundle form and
VS Code's masked prompts keep working exactly as they do today. See `config.setting`
for the precedence rule.

Parsing goes through `python-dotenv` rather than a hand-rolled split, because the
mistakes a non-developer makes in this file are the ones that fail silently:
`KEY="quoted"` keeping its quotes, `export KEY=v`, a trailing `# comment`, or CRLF
line endings all corrupt a credential in ways that surface later as a signing error
indistinguishable from a bad key.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

from dotenv import dotenv_values, set_key

DEFAULT_DIR = Path.home() / ".delta-exchange-mcp"
DEFAULT_NAME = "config.env"

TEMPLATE = """\
# Delta Exchange MCP - settings shared by every MCP client on this machine.
#
# Market data works with this file empty. Fill these in to let an assistant read
# your own account. Create a key under Account -> API Keys at
# https://www.delta.exchange/app/account/manageapikeys with the "Read Data"
# permission, and whitelist your IP on it.
#
# Match the environment to where the key came from: a key from delta.exchange
# works only with india_prod, one from demo.delta.exchange only with
# india_testnet. Mixing them returns InvalidApiKey.
#
# Your MCP client's own settings take precedence over this file.

DELTA_API_KEY=
DELTA_API_SECRET=
DELTA_MCP_ENV=india_prod

# Trading is deliberately NOT read from this file. Enable it in the config of the
# one client you mean to trade from, so switching it on in a single place cannot
# arm every assistant on this machine at once.
# DELTA_MCP_MODE=trade
"""


def path() -> Path:
    """Where the shared settings file lives.

    `DELTA_MCP_CONFIG_FILE` overrides it, and is read from the process environment
    only — a file cannot name itself.
    """
    override = (os.environ.get("DELTA_MCP_CONFIG_FILE") or "").strip()
    return Path(override).expanduser() if override else DEFAULT_DIR / DEFAULT_NAME


def read() -> dict[str, str]:
    """Values from the shared file, dropping any left blank.

    A missing file is the ordinary first-run state, and an unreadable one must not
    stop market data from working, so neither is an error.
    """
    try:
        return {key: value for key, value in dotenv_values(path()).items() if value}
    except OSError:
        return {}


def ensure() -> Path | None:
    """Create the file from a commented template when it is absent.

    Returns the path once the file exists, or None when it could not be created —
    a read-only or sandboxed filesystem must not stop the server from starting.
    The template carries the instructions someone needs at the moment they open it,
    which is the whole reason the file is written before anyone asks for it.
    """
    target = path()
    try:
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    except OSError:
        # Includes FileExistsError when the parent path is an ordinary file. That means
        # the location is unusable, which is the opposite of what the same exception
        # means one step below, so the two cannot share a handler.
        return None
    try:
        # Exclusive create rather than a prior exists() check: two clients launching
        # the server at the same moment is normal, and one must not truncate the
        # other's file in the gap between checking and writing.
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return target
    except OSError:
        return None
    with os.fdopen(fd, "w") as handle:
        handle.write(TEMPLATE)
    return target


def write(values: dict[str, str]) -> str | None:
    """Set each of `values` in the shared file, returning a message if any could not be.

    `set_key` edits one line in place, so the template's comments and any setting the
    caller did not name survive. That is what lets hand-editing, `login` and the in-chat
    form share one file rather than each owning a format of its own.
    """
    target = ensure()
    if target is None:
        return f"cannot write {path()}"
    for name, value in values.items():
        try:
            written, _, _ = set_key(str(target), name, value)
        except OSError as exc:
            # Reported rather than raised because a caller may be a tool answering a form,
            # where an exception becomes a protocol error the person cannot act on.
            return f"could not write {name} to {target}: {exc}"
        if not written:
            return f"could not write {name} to {target}"
    return None


def insecure_permissions() -> str | None:
    """A warning when the file is readable by users other than its owner.

    Reported rather than raised. Refusing to start would take away market data,
    which needs no credentials at all, over a file the user may not even have
    filled in.
    """
    target = path()
    try:
        mode = target.stat().st_mode
    except OSError:
        return None
    if not mode & (stat.S_IRGRP | stat.S_IROTH):
        return None
    return (
        f"{target} can hold API credentials but is readable by other users on this "
        f"machine. Restrict it with: chmod 600 {target}"
    )
