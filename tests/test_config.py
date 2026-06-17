import pytest

from delta_exchange_mcp import config as config_mod


def test_defaults_to_india_prod(monkeypatch):
    monkeypatch.delenv("DELTA_MCP_ENV", raising=False)
    monkeypatch.delenv("DELTA_API_KEY", raising=False)
    monkeypatch.delenv("DELTA_API_SECRET", raising=False)
    cfg = config_mod.load()
    assert cfg.env == "india_prod"
    assert cfg.base_url == config_mod.INDIA_PROD_REST
    assert cfg.has_credentials is False


def test_testnet_override(monkeypatch):
    monkeypatch.setenv("DELTA_MCP_ENV", "india_testnet")
    cfg = config_mod.load()
    assert cfg.env == "india_testnet"
    assert cfg.base_url == config_mod.INDIA_TESTNET_REST


def test_invalid_env_rejected(monkeypatch):
    monkeypatch.setenv("DELTA_MCP_ENV", "mainnet")  # old alias no longer accepted
    with pytest.raises(ValueError, match="DELTA_MCP_ENV"):
        config_mod.load()


def test_credentials_loaded_from_env(monkeypatch):
    monkeypatch.setenv("DELTA_API_KEY", "k")
    monkeypatch.setenv("DELTA_API_SECRET", "s")
    cfg = config_mod.load()
    assert cfg.api_key == "k"
    assert cfg.api_secret == "s"
    assert cfg.has_credentials is True


def test_partial_credentials_do_not_count(monkeypatch):
    monkeypatch.setenv("DELTA_API_KEY", "k")
    monkeypatch.delenv("DELTA_API_SECRET", raising=False)
    cfg = config_mod.load()
    assert cfg.has_credentials is False


def test_debug_off_by_default(monkeypatch):
    monkeypatch.delenv("DELTA_MCP_DEBUG", raising=False)
    assert config_mod.load().debug is False


@pytest.mark.parametrize("value", ["1", "true", "yes", "on", "ON", " True "])
def test_debug_truthy_values(monkeypatch, value):
    monkeypatch.setenv("DELTA_MCP_DEBUG", value)
    assert config_mod.load().debug is True


@pytest.mark.parametrize("value", ["0", "false", "", "no"])
def test_debug_falsy_values(monkeypatch, value):
    monkeypatch.setenv("DELTA_MCP_DEBUG", value)
    assert config_mod.load().debug is False
