import pytest

from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp import login, store


class FakeTty:
    def isatty(self):
        return True


@pytest.fixture
def terminal(monkeypatch):
    """Answer the prompts as a person at a keyboard would."""
    monkeypatch.setattr(login.sys, "stdin", FakeTty())
    monkeypatch.setattr("builtins.input", lambda prompt="": "india_testnet")
    secrets = iter(["a-real-key", "a-real-secret"])
    monkeypatch.setattr(login.getpass, "getpass", lambda prompt="": next(secrets))


def check_returning(**kwargs):
    async def fake(env, key, secret):
        return login.Check(**kwargs)

    return fake


def test_refuses_without_a_terminal(monkeypatch, capsys):
    """getpass alone would read a pipe and echo it.

    `echo $KEY | delta-exchange-mcp login` is what an agent trying to help would run,
    and it would put the secret in shell history and in that agent's transcript.
    """

    class NotATty:
        def isatty(self):
            return False

    monkeypatch.setattr(login.sys, "stdin", NotATty())
    assert login.run() == 2
    assert "needs a terminal" in capsys.readouterr().err
    assert not store.path().exists()


def test_saves_after_a_successful_check(terminal, monkeypatch):
    monkeypatch.setattr(login, "_check", check_returning(ok=True, reachable=True, detail=""))
    assert login.run() == 0

    cfg = config_mod.load()
    assert (cfg.api_key, cfg.api_secret) == ("a-real-key", "a-real-secret")
    assert cfg.env == "india_testnet"


def test_saving_keeps_the_template_and_its_instructions(terminal, monkeypatch):
    """The file has to stay hand-editable after login has written to it."""
    monkeypatch.setattr(login, "_check", check_returning(ok=True, reachable=True, detail=""))
    login.run()

    body = store.path().read_text()
    assert "Read Data" in body
    assert "DELTA_MCP_MODE=trade" in body  # the commented-out explanation survives


def test_a_rejected_key_is_not_saved(terminal, monkeypatch, capsys):
    """Saving a key that does not work would register the account tools and fail every call.

    That is the state placeholder credentials used to produce, and the reason the check
    exists at all.
    """
    monkeypatch.setattr(
        login,
        "_check",
        check_returning(
            ok=False,
            reachable=True,
            detail="delta api error: InvalidApiKey — API key not found.",
        ),
    )
    assert login.run() == 1
    assert "Nothing was saved" in capsys.readouterr().err
    assert config_mod.load().has_credentials is False


def test_an_unreachable_api_still_saves(terminal, monkeypatch, capsys):
    """A flaky connection must not cost someone a key they typed correctly."""
    monkeypatch.setattr(
        login,
        "_check",
        check_returning(ok=False, reachable=False, detail="could not reach Delta: timeout"),
    )
    assert login.run() == 0
    assert "unverified" in capsys.readouterr().err
    assert config_mod.load().has_credentials is True


def test_no_verify_skips_the_call(terminal, monkeypatch):
    async def explode(env, key, secret):
        raise AssertionError("--no-verify must not reach the API")

    monkeypatch.setattr(login, "_check", explode)
    assert login.run(verify=False) == 0
    assert config_mod.load().has_credentials is True


def test_half_a_pair_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(login.sys, "stdin", FakeTty())
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    secrets = iter(["only-a-key", ""])
    monkeypatch.setattr(login.getpass, "getpass", lambda prompt="": next(secrets))

    assert login.run() == 1
    assert "both a key and its secret" in capsys.readouterr().err
    assert config_mod.load().has_credentials is False


def test_an_unknown_environment_is_refused(monkeypatch, capsys):
    monkeypatch.setattr(login.sys, "stdin", FakeTty())
    monkeypatch.setattr("builtins.input", lambda prompt="": "mainnet")

    assert login.run() == 1
    assert "not an environment" in capsys.readouterr().err


def test_a_shell_export_that_would_shadow_the_file_is_reported(terminal, monkeypatch, capsys):
    """A client launched from this shell inherits the export, and the client always wins.

    Without this the key just saved would appear to do nothing at all.
    """
    monkeypatch.setenv("DELTA_API_KEY", "exported-in-the-shell")
    monkeypatch.setattr(login, "_check", check_returning(ok=True, reachable=True, detail=""))
    assert login.run() == 0
    assert "takes precedence over the file" in capsys.readouterr().err
