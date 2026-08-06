from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from delta_exchange_mcp import store

Env = Literal["india_prod", "india_testnet", "india_devnet"]
Mode = Literal["read", "trade"]

INDIA_PROD_REST = "https://api.india.delta.exchange/v2"
INDIA_TESTNET_REST = "https://cdn-ind.testnet.deltaex.org/v2"
INDIA_DEVNET_REST = "https://cdn-ind.devnet.deltaex.org/v2"

BASE_URLS: dict[str, str] = {
    "india_prod": INDIA_PROD_REST,
    "india_testnet": INDIA_TESTNET_REST,
    "india_devnet": INDIA_DEVNET_REST,
}

DEFAULT_ENV = "india_prod"
DEFAULT_MODE = "read"
MODES: set[str] = {"read", "trade"}


TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    env: Env
    base_url: str
    api_key: str | None = None
    api_secret: str | None = None
    debug: bool = False
    mode: Mode = "read"
    config_file: Path | None = None

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret)

    @property
    def partial_credentials(self) -> bool:
        """One half of the pair supplied without the other — always a misconfiguration.

        Both are needed to sign a request, so this silently yields public-data mode. It is
        reported rather than raised: a stray DELTA_API_KEY in someone's shell should not
        kill an otherwise working market-data server.
        """
        return bool(self.api_key) != bool(self.api_secret)


def setting(name: str, shared: dict[str, str] | None = None) -> str | None:
    """Resolve one setting: the process environment first, then the shared file.

    Empty means unanswered rather than answered-with-nothing. A bundle substitutes
    every variable it declares whether or not the user filled that field in, so a
    cleared input arrives as "" — it has to fall through to the file rather than
    override it, or the shared file could never reach a bundle user at all. `shared`
    lets one caller resolve several settings from the same file snapshot.
    """
    from_env = (os.environ.get(name) or "").strip()
    if from_env:
        return from_env
    values = store.read() if shared is None else shared
    return (values.get(name) or "").strip() or None


def _credentials(shared: dict[str, str]) -> tuple[str | None, str | None]:
    """The API key and its secret, always taken from the same source.

    Resolving them independently could pair a leftover DELTA_API_KEY in someone's
    shell with a secret from the shared file. That combination was never issued
    together, so every signed request fails while the server reports the account
    surface as available — the least diagnosable outcome available. Taking both from
    wherever either one appears turns that into the partial-credentials warning,
    which says exactly what is wrong.
    """
    # Stripped like every other setting, so a whitespace-only field reads as unanswered
    # and falls through. Stripping also absorbs the trailing newline a pasted key
    # usually carries, which would otherwise fail signing and look like a wrong key.
    key = (os.environ.get("DELTA_API_KEY") or "").strip() or None
    secret = (os.environ.get("DELTA_API_SECRET") or "").strip() or None
    if key or secret:
        return key, secret
    return (
        (shared.get("DELTA_API_KEY") or "").strip() or None,
        (shared.get("DELTA_API_SECRET") or "").strip() or None,
    )


def load() -> Config:
    config_file = store.ensure()
    # `store.write` replaces a complete file atomically. Read it once so one Config
    # cannot combine the environment from the old file with credentials from the new.
    shared = store.read()

    env = (setting("DELTA_MCP_ENV", shared) or DEFAULT_ENV).lower()
    if env not in BASE_URLS:
        raise ValueError(
            f"DELTA_MCP_ENV must be one of {sorted(BASE_URLS)}, got {env!r}"
        )

    # Mode is the one setting the shared file may not supply. Everything else there is
    # per-machine convenience; this one places real orders, so it stays scoped to the
    # single client whose config was deliberately edited to enable it.
    mode = (os.environ.get("DELTA_MCP_MODE", "") or "").strip().lower() or DEFAULT_MODE
    if mode not in MODES:
        raise ValueError(f"DELTA_MCP_MODE must be one of {sorted(MODES)}, got {mode!r}")

    api_key, api_secret = _credentials(shared)

    return Config(
        env=env,  # type: ignore[arg-type]
        base_url=BASE_URLS[env],
        api_key=api_key,
        api_secret=api_secret,
        debug=(setting("DELTA_MCP_DEBUG", shared) or "").lower() in TRUTHY,
        mode=mode,  # type: ignore[arg-type]
        config_file=config_file,
    )
