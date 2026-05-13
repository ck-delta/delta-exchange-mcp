from __future__ import annotations

from typing import Any

# Documented in slate `_authentication.md`. Lookup of server error code → human hint.
_AUTH_HINTS: dict[str, str] = {
    "SignatureExpired": (
        "request signature expired (>5s drift). Sync your system clock via NTP."
    ),
    "InvalidApiKey": (
        "API key not found. Prod and testnet keys are separate — confirm DELTA_MCP_ENV "
        "matches the dashboard the key was created on."
    ),
    "invalid_api_key": (
        "API key not found. Prod and testnet keys are separate — confirm DELTA_MCP_ENV "
        "matches the dashboard the key was created on."
    ),
    "UnauthorizedApiAccess": (
        "API key lacks permission for this endpoint. Enable Read Data (or Trading) on "
        "the key in Delta API management."
    ),
    "unauthorized_api_access": (
        "API key lacks permission for this endpoint. Enable Read Data (or Trading) on "
        "the key in Delta API management."
    ),
    "ip_not_whitelisted_for_api_key": (
        "request IP not whitelisted for this API key. Add the IP shown in the error "
        "context under Delta API management."
    ),
    "Signature Mismatch": (
        "signature mismatch — usually clock skew or a path/query encoding bug."
    ),
    "signature_mismatch": (
        "signature mismatch — usually clock skew or a path/query encoding bug."
    ),
}


def _extract_ip(context: Any) -> str | None:
    if not isinstance(context, dict):
        return None
    for key in ("ip", "client_ip", "whitelisted_ip", "request_ip"):
        v = context.get(key)
        if isinstance(v, str) and v:
            return v
    return None


class DeltaApiError(Exception):
    def __init__(self, code: str, context: Any = None, status: int | None = None):
        self.code = code
        self.context = context
        self.status = status
        self.hint = _AUTH_HINTS.get(code)

        msg = f"delta api error: {code}"
        if self.hint:
            extra_ip = _extract_ip(context) if code == "ip_not_whitelisted_for_api_key" else None
            msg += f" — {self.hint}"
            if extra_ip:
                msg += f" (request IP: {extra_ip})"
        if context:
            msg += f" (context={context})"
        if status:
            msg += f" [http {status}]"
        super().__init__(msg)


class ConfigError(Exception):
    pass
