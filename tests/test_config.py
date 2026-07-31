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


@pytest.mark.parametrize("value", ["", "   "])
def test_blank_env_and_mode_fall_back_to_defaults(monkeypatch, value):
    """A bundle substitutes every declared variable, so a cleared form field arrives blank.

    Treating that as invalid stopped the server from starting at all, which is a worse
    outcome than the default — and for mode the default is also the safe direction.
    """
    monkeypatch.setenv("DELTA_MCP_ENV", value)
    monkeypatch.setenv("DELTA_MCP_MODE", value)
    cfg = config_mod.load()
    assert cfg.env == "india_prod"
    assert cfg.mode == "read"


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


@pytest.mark.parametrize(
    ("key", "secret", "partial"),
    [
        ("k", "s", False),
        (None, None, False),
        ("k", None, True),
        (None, "s", True),
    ],
)
def test_partial_credentials_detects_a_half_supplied_pair(monkeypatch, key, secret, partial):
    """A key without its secret yields public-data mode; the config has to say so."""
    for name, value in (("DELTA_API_KEY", key), ("DELTA_API_SECRET", secret)):
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)
    cfg = config_mod.load()
    assert cfg.partial_credentials is partial
    assert cfg.has_credentials is (key is not None and secret is not None)
