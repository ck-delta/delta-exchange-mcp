import os
import stat

import pytest

from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp import store


@pytest.fixture(autouse=True)
def no_ambient_settings(monkeypatch):
    """Start every test from an environment that supplies nothing.

    The suite inherits the developer's shell, and a stray DELTA_API_KEY there would
    silently win over the file these tests are about.
    """
    for name in (
        "DELTA_MCP_ENV",
        "DELTA_MCP_MODE",
        "DELTA_MCP_DEBUG",
        "DELTA_API_KEY",
        "DELTA_API_SECRET",
    ):
        monkeypatch.delenv(name, raising=False)


def write_store(text):
    path = store.path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_template_is_created_on_first_load_owner_only():
    cfg = config_mod.load()
    path = store.path()
    assert cfg.config_file == path
    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    # The instructions someone needs are in the file, because the moment they open it
    # is the moment they are asking these exact questions.
    body = path.read_text()
    assert "Read Data" in body
    assert "india_testnet" in body
    assert "DELTA_API_KEY=" in body


def test_existing_file_is_never_overwritten():
    written = write_store("DELTA_API_KEY=mine\nDELTA_API_SECRET=also-mine\n")
    config_mod.load()
    assert written.read_text() == "DELTA_API_KEY=mine\nDELTA_API_SECRET=also-mine\n"


def test_unwritable_location_does_not_stop_the_server(tmp_path, monkeypatch):
    """Market data needs no credentials, so an unusable settings file is not fatal."""
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv("DELTA_MCP_CONFIG_FILE", str(blocker / "config.env"))
    cfg = config_mod.load()
    assert cfg.config_file is None
    assert cfg.env == "india_prod"
    assert cfg.has_credentials is False


def test_store_supplies_settings_when_the_environment_is_silent():
    write_store("DELTA_API_KEY=k\nDELTA_API_SECRET=s\nDELTA_MCP_ENV=india_testnet\n")
    cfg = config_mod.load()
    assert cfg.env == "india_testnet"
    assert cfg.base_url == config_mod.INDIA_TESTNET_REST
    assert (cfg.api_key, cfg.api_secret) == ("k", "s")


def test_client_environment_beats_the_store(monkeypatch):
    write_store("DELTA_API_KEY=from-file\nDELTA_API_SECRET=from-file\n")
    monkeypatch.setenv("DELTA_API_KEY", "from-client")
    monkeypatch.setenv("DELTA_API_SECRET", "from-client")
    cfg = config_mod.load()
    assert (cfg.api_key, cfg.api_secret) == ("from-client", "from-client")


@pytest.mark.parametrize("blank", ["", "   "])
def test_blank_client_values_fall_through_to_the_store(monkeypatch, blank):
    """A bundle substitutes every variable it declares, filled in or not.

    Leaving the API key field empty in the Claude Desktop form puts "" in the
    environment. Treating that as an answer would mean the shared file could never
    reach a bundle user at all.
    """
    write_store("DELTA_API_KEY=k\nDELTA_API_SECRET=s\nDELTA_MCP_ENV=india_testnet\n")
    monkeypatch.setenv("DELTA_API_KEY", blank)
    monkeypatch.setenv("DELTA_API_SECRET", blank)
    monkeypatch.setenv("DELTA_MCP_ENV", blank)
    cfg = config_mod.load()
    assert cfg.env == "india_testnet"
    assert (cfg.api_key, cfg.api_secret) == ("k", "s")


def test_a_stray_key_never_pairs_with_the_stores_secret(monkeypatch):
    """The key and secret always come from the same source.

    Resolving them independently would pair a leftover key from someone's shell with
    a secret from the file. That pair was never issued together, so every signed call
    would fail while the server advertised the account surface as working. Taking both
    from wherever either appears turns it into the partial-credentials warning instead.
    """
    write_store("DELTA_API_KEY=file-key\nDELTA_API_SECRET=file-secret\n")
    monkeypatch.setenv("DELTA_API_KEY", "leftover-shell-key")
    cfg = config_mod.load()
    assert cfg.api_key == "leftover-shell-key"
    assert cfg.api_secret is None
    assert cfg.partial_credentials is True
    assert cfg.has_credentials is False


def test_trade_mode_is_never_read_from_the_store():
    """The one setting the shared file may not supply.

    Everything else there is per-machine convenience. This one places real orders, so
    it stays scoped to the single client whose config was deliberately edited.
    """
    write_store("DELTA_API_KEY=k\nDELTA_API_SECRET=s\nDELTA_MCP_MODE=trade\n")
    cfg = config_mod.load()
    assert cfg.mode == "read"
    assert cfg.has_credentials is True


def test_trade_mode_still_works_from_the_client(monkeypatch):
    write_store("DELTA_API_KEY=k\nDELTA_API_SECRET=s\n")
    monkeypatch.setenv("DELTA_MCP_MODE", "trade")
    assert config_mod.load().mode == "trade"


def test_debug_and_path_overrides_come_from_the_store(tmp_path):
    write_store(
        "DELTA_MCP_DEBUG=1\n"
        f"DELTA_MCP_AUDIT_FILE={tmp_path / 'audit.log'}\n"
        f"DELTA_MCP_DEBUG_FILE={tmp_path / 'debug.log'}\n"
    )
    assert config_mod.load().debug is True
    assert config_mod.setting("DELTA_MCP_AUDIT_FILE") == str(tmp_path / "audit.log")
    assert config_mod.setting("DELTA_MCP_DEBUG_FILE") == str(tmp_path / "debug.log")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ('DELTA_API_KEY="quoted"', "quoted"),
        ("export DELTA_API_KEY=exported", "exported"),
        ("DELTA_API_KEY=plain  # trailing note", "plain"),
        ("DELTA_API_KEY = spaced", "spaced"),
        ("DELTA_API_KEY=windows\r", "windows"),
    ],
)
def test_a_hand_edited_file_survives_the_usual_mistakes(line, expected):
    """Each of these silently corrupts a credential under a naive KEY=value split.

    Three of the five then fail as a signature error indistinguishable from a wrong
    key, which is the worst outcome for the people this file exists to help.
    """
    write_store(f"{line}\nDELTA_API_SECRET=s\n")
    assert config_mod.load().api_key == expected


def test_blank_entries_in_the_template_are_not_credentials():
    """The shipped template has empty values; they must read as absent."""
    config_mod.load()  # writes the template
    cfg = config_mod.load()  # reads it back
    assert cfg.has_credentials is False
    assert cfg.partial_credentials is False
    assert cfg.env == "india_prod"


def test_world_readable_file_is_reported_not_fatal():
    path = write_store("DELTA_API_KEY=k\nDELTA_API_SECRET=s\n")
    os.chmod(path, 0o644)
    warning = store.insecure_permissions()
    assert warning is not None
    assert "chmod 600" in warning
    assert config_mod.load().has_credentials is True

    os.chmod(path, 0o600)
    assert store.insecure_permissions() is None


def test_missing_file_reports_no_permission_warning(tmp_path, monkeypatch):
    monkeypatch.setenv("DELTA_MCP_CONFIG_FILE", str(tmp_path / "absent.env"))
    assert store.insecure_permissions() is None
