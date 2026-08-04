"""A credential pair: checked against Delta, then saved where every client reads it.

Two front-ends fill the same store — `login` for someone already at a terminal, and the
in-chat form in `form` for someone who never opens one. Both need the same check before
saving and both write the same three keys, so neither owns that; this does.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from delta_exchange_mcp import store
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.config import BASE_URLS, Config, load
from delta_exchange_mcp.errors import DeltaApiError


@dataclass(frozen=True)
class Check:
    """Outcome of asking Delta whether the credentials work.

    `reachable` is separate from `ok` because they call for opposite responses: a key
    Delta rejected must not be saved, while a key we could not ask about must be, or a
    flaky connection costs someone a credential they typed correctly.
    """

    ok: bool
    reachable: bool
    detail: str
    # Delta's own error code when it rejected the key. Kept beside the rendered message so
    # a caller can act on which failure it was without matching on that message's text.
    code: str = ""


def overridden_by_client() -> list[str]:
    """Which settings in the shared file the process environment is overriding.

    `config` resolves the process environment before the file, so a client that passes its
    own key or environment outranks whatever is saved here — on every launch, which is why
    restarting cannot help. Saying nothing produces the worst version of this: a save
    verifies one account against Delta, reports it by name, and the server goes on signing
    with a different one.

    Compares what `config` actually resolves against what the file holds, rather than
    restating the precedence rules, so this cannot drift from them. Presence alone is the
    wrong test twice over. A client pinning the environment to the value the user chose
    overrides nothing that matters, and the Cursor install link sets DELTA_MCP_ENV for
    everyone — so that test would tell every Cursor user their working key was ignored.
    A file with nothing in it is not being overridden either.
    """
    stored = store.read()
    live = load()
    effective = {
        "DELTA_MCP_ENV": live.env,
        "DELTA_API_KEY": live.api_key,
        "DELTA_API_SECRET": live.api_secret,
    }
    return [
        name
        for name, in_use in effective.items()
        if (saved := (stored.get(name) or "").strip()) and saved != in_use
    ]


async def check(env: str, key: str, secret: str) -> Check:
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
        return Check(ok=False, reachable=True, detail=str(exc), code=exc.code)
    except httpx.HTTPError as exc:
        return Check(ok=False, reachable=False, detail=f"could not reach Delta: {exc}")
    else:
        # The client hands back Delta's envelope rather than unwrapping it, so the account
        # lives under "result". Reading the top level instead silently yields no name at
        # all, which is the one thing that distinguishes this from saving the wrong
        # account's key.
        body = profile.get("result") if isinstance(profile, dict) else None
        who = str(body.get("email") or body.get("id") or "") if isinstance(body, dict) else ""
        return Check(ok=True, reachable=True, detail=who)
    finally:
        await client.aclose()


def save(env: str, key: str, secret: str) -> str | None:
    """Write the pair and its environment, returning a message if anything failed.

    The environment goes in alongside them deliberately. It is not a separate preference
    but part of what makes the key usable at all, and saving a testnet key while the file
    still says india_prod produces InvalidApiKey on every call.
    """
    return store.write(
        {"DELTA_MCP_ENV": env, "DELTA_API_KEY": key, "DELTA_API_SECRET": secret}
    )
