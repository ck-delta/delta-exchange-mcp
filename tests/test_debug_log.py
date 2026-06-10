import logging

import httpx
import pytest
import respx

from delta_exchange_mcp import debug_log
from delta_exchange_mcp.client import DeltaClient
from delta_exchange_mcp.config import INDIA_TESTNET_REST, Config


@pytest.fixture(autouse=True)
def _clear_handlers():
    """Each test attaches a FileHandler to module loggers; remove them after so the open
    file doesn't leak into the next test (and the idempotency guard starts fresh)."""
    yield
    for name in debug_log.LOGGER_NAMES:
        logger = logging.getLogger(name)
        for h in list(logger.handlers):
            h.close()
            logger.removeHandler(h)
        logger.setLevel(logging.NOTSET)
        logger.propagate = True


def _cfg(tmp_path, **kw):
    return Config(env="india_testnet", base_url=INDIA_TESTNET_REST, **kw)


@pytest.mark.asyncio
@respx.mock
async def test_logs_request_and_body_but_no_secrets(tmp_path, monkeypatch):
    log_file = tmp_path / "d.log"
    monkeypatch.setenv("DELTA_MCP_DEBUG_FILE", str(log_file))
    cfg = _cfg(tmp_path, api_key="APIKEY123", api_secret="SUPERSECRET", debug=True)
    path = debug_log.configure(cfg)
    assert path == log_file

    route = respx.get(f"{INDIA_TESTNET_REST}/wallet/transactions").mock(
        return_value=httpx.Response(
            200,
            json={"success": True, "result": [{"transaction_type": "deposit"}], "meta": {"total_count": 3}},
        )
    )
    client = DeltaClient(cfg)
    await client.get("/wallet/transactions", params={"transaction_types": "deposit"}, auth=True)
    await client.aclose()

    for h in logging.getLogger("delta_exchange_mcp").handlers:
        h.flush()
    text = log_file.read_text()

    # Request + body are captured.
    assert "wallet/transactions" in text
    assert "transaction_types=deposit" in text
    assert "total_count" in text
    assert "200" in text
    # Credentials are never written.
    assert "SUPERSECRET" not in text
    assert "APIKEY123" not in text
    signature = route.calls[0].request.headers["signature"]
    assert signature not in text


def test_debug_off_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DELTA_MCP_DEBUG_FILE", str(tmp_path / "d.log"))
    assert debug_log.configure(_cfg(tmp_path, debug=False)) is None
    assert not (tmp_path / "d.log").exists()
