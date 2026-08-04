"""Bringing the account tools up mid-session, without restarting the client.

These drive a real client session over the real protocol rather than calling the tool
functions directly, because every interesting part of this is protocol-level: whether the
server declared that its tool list can change, whether the notification reaches the
client, and whether a `tools/list` after it shows tools that did not exist at startup.
Calling `save_credentials` in-process proves none of that.
"""

import json
from contextlib import asynccontextmanager

import anyio
import mcp.types as types
import pytest
from mcp.client.session import ClientSession
from mcp.shared.memory import create_client_server_memory_streams

from delta_exchange_mcp import config as config_mod
from delta_exchange_mcp import credentials, server, store

KEY = "typed-into-the-form-key"
SECRET = "typed-into-the-form-secret"


class Session:
    """A connected client plus the notifications the server pushed to it."""

    def __init__(self, client, initialized):
        self.client = client
        self.initialized = initialized
        self.notifications = []

    async def tool_names(self):
        return {t.name for t in (await self.client.list_tools()).tools}

    async def call(self, name, **arguments):
        result = await self.client.call_tool(name, arguments)
        return json.loads(result.content[0].text)

    def saw_tool_list_changed(self):
        return any(
            isinstance(n, types.ToolListChangedNotification) for n in self.notifications
        )


@asynccontextmanager
async def connected(cfg=None, client_name=None):
    """A client talking to a server started the way `main` starts it.

    The SDK's own `create_connected_server_and_client_session` builds initialization
    options from scratch, which would silently drop the one capability under test here.
    """
    mcp = server.build_server(cfg or config_mod.load())
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        client_read, client_write = client_streams
        server_read, server_write = server_streams
        async with anyio.create_task_group() as tg:
            tg.start_soon(
                lambda: mcp._mcp_server.run(
                    server_read,
                    server_write,
                    server.initialization_options(mcp),
                    raise_exceptions=True,
                )
            )
            box = {}

            async def collect(message):
                if isinstance(message, types.ServerNotification):
                    box["session"].notifications.append(message.root)

            info = (
                types.Implementation(name=client_name, version="1")
                if client_name
                else None
            )
            async with ClientSession(
                client_read, client_write, message_handler=collect, client_info=info
            ) as client:
                initialized = await client.initialize()
                box["session"] = Session(client, initialized)
                yield box["session"]
            tg.cancel_scope.cancel()


@pytest.fixture
def accepted(monkeypatch):
    """Delta accepts whatever key is offered, without a live call."""

    async def check(env, key, secret):
        return credentials.Check(ok=True, reachable=True, detail="someone@delta.exchange")

    monkeypatch.setattr(credentials, "check", check)


async def save(session):
    await session.call("setup_credentials")
    return await session.call(
        "save_credentials",
        environment="india_testnet",
        api_key=KEY,
        api_secret=SECRET,
    )


# --- what the server promises at startup ---------------------------------------------


async def test_the_server_declares_that_its_tool_list_can_change():
    """Without this the notification is one a client was told never to expect.

    A client reads `tools/list` once and re-reads it only when told the list changed, so
    declaring `listChanged: false` and then sending the notification means the account
    tools stay invisible and the restart is unavoidable — with nothing failing anywhere
    to say so.
    """
    async with connected() as session:
        assert session.initialized.capabilities.tools.listChanged is True


async def test_the_model_is_told_how_to_reach_the_form_before_any_key_exists():
    """The state with no key has no account tool to carry a hint on its own description."""
    async with connected() as session:
        instructions = session.initialized.instructions
        assert "setup_credentials" in instructions
        assert "Never ask for an API key" in instructions


async def test_the_status_tool_exists_with_no_credentials(accepted):
    """"Am I connected?" is asked most often by someone who is not."""
    async with connected() as session:
        assert "get_connection_status" in await session.tool_names()
        status = await session.call("get_connection_status")
        assert status["credentials_configured"] is False
        assert status["account_tools_available"] is False
        assert status["restart_required"] is False


# --- bringing the surface up ---------------------------------------------------------


async def test_a_saved_key_makes_the_account_tools_reachable_without_a_restart(accepted):
    """The whole point: the client sees tools that did not exist when it connected."""
    async with connected() as session:
        before = await session.tool_names()
        assert "get_positions" not in before

        result = await save(session)
        assert result["status"] == "saved"

        assert session.saw_tool_list_changed()
        after = await session.tool_names()
        assert "get_positions" in after
        assert "get_wallet_balances" in after


async def test_the_saved_message_leads_with_carrying_on_rather_than_restarting(accepted):
    async with connected() as session:
        message = (await save(session))["message"]
        assert "live in this session" in message
        assert "someone@delta.exchange" in message


async def test_the_status_tool_reports_the_surface_that_is_actually_live(accepted):
    async with connected() as session:
        await save(session)
        status = await session.call("get_connection_status")
        assert status["credentials_configured"] is True
        assert status["account_tools_available"] is True
        assert status["restart_required"] is False
        # The environment typed into the form, not the one loaded at startup.
        assert status["environment"] == "india_testnet"
        assert json.dumps(status).find(SECRET) == -1


async def test_a_second_save_does_not_register_the_account_tools_twice(accepted):
    """Rotating a key goes through the same path, and FastMCP would keep both copies."""
    async with connected() as session:
        await save(session)
        first = await session.tool_names()
        await save(session)
        assert await session.tool_names() == first


async def test_replacing_a_key_already_in_use_asks_for_a_restart(accepted):
    """The registered account tools hold a client built from the key being replaced.

    Nothing rebuilds them, so they would go on signing with the old key. Both the message
    and the status tool have to say so, or they contradict each other.
    """
    async with connected() as session:
        await save(session)
        again = await save(session)
        assert "Restart this client" in again["message"]
        assert (await session.call("get_connection_status"))["restart_required"] is True


# --- what still needs a restart ------------------------------------------------------


async def test_trade_mode_still_waits_for_a_restart(accepted, monkeypatch):
    """Order placement must follow from the client config the user edited.

    Arming it from a form submitted in a chat would mean a mutating surface appeared
    without the user doing the thing that enables it.
    """
    monkeypatch.setenv("DELTA_MCP_MODE", "trade")
    async with connected() as session:
        result = await save(session)
        assert "Restart this client" in result["message"]

        # The reads still came up — only the mutations wait. Suppressing the notification
        # too would leave them registered and unreachable, which is the worst of both.
        assert session.saw_tool_list_changed()
        names = await session.tool_names()
        assert "get_positions" in names
        assert "place_order" not in names

        status = await session.call("get_connection_status")
        assert status["mode"] == "trade"
        assert status["restart_required"] is True


async def test_a_key_the_client_config_outranks_says_so_instead_of_reporting_success(
    accepted, monkeypatch
):
    """The failure this replaces was silent, and restarting made it look broken.

    config resolves the process environment before the shared file, so a client passing
    its own key wins on every launch. The save verified a real account and would have
    reported it by name while the server went on signing with the other one.
    """
    monkeypatch.setenv("DELTA_API_KEY", "from-the-client-config")
    monkeypatch.setenv("DELTA_API_SECRET", "from-the-client-config")
    async with connected() as session:
        result = await save(session)
        assert result["status"] == "overridden"
        assert "DELTA_API_KEY" in result["message"]
        assert "will not be used" in result["message"]
        # The email of the account it checked must not be reported as connected.
        assert "someone@delta.exchange" not in result["message"]

        # The key still belongs in the file — every other client on the machine reads it.
        assert store.read()["DELTA_API_KEY"] == KEY

        status = await session.call("get_connection_status")
        assert status["overridden_by_client"] == ["DELTA_API_KEY", "DELTA_API_SECRET"]
        # Restarting cannot help: the client passes its own value again every launch.
        assert status["restart_required"] is False


async def test_an_environment_the_client_config_outranks_is_reported_too(accepted, monkeypatch):
    """Picking the practice site is just as ignorable, and fails as a rejected key later."""
    monkeypatch.setenv("DELTA_MCP_ENV", "india_prod")
    async with connected() as session:
        result = await save(session)
        assert result["status"] == "overridden"
        assert "DELTA_MCP_ENV" in result["message"]
        # This case still uses the key, so saying it is unused would be wrong — it is sent
        # to the site it was not created on, where Delta rejects it as unknown.
        assert "will not be used at all" not in result["message"]
        assert "against the other site" in result["message"]


async def test_a_client_pinning_the_same_environment_is_not_reported(accepted, monkeypatch):
    """The Cursor install link sets DELTA_MCP_ENV=india_prod for everyone who uses it.

    Testing for presence rather than for a difference would tell every one of those users
    that the key they just saved would not be used, which is both false and alarming.
    """
    monkeypatch.setenv("DELTA_MCP_ENV", "india_testnet")
    async with connected() as session:
        # The same environment the form is about to save.
        result = await save(session)
        assert result["status"] == "saved"
        assert (await session.call("get_connection_status"))["overridden_by_client"] == []


# --- trading, scoped to the client that asked for it ---------------------------------


def credentialled(mode_for=None):
    """A settings file with a working key, and optionally a client entitled to trade."""
    values = {
        "DELTA_MCP_ENV": "india_testnet",
        "DELTA_API_KEY": KEY,
        "DELTA_API_SECRET": SECRET,
    }
    if mode_for:
        values[config_mod.mode_key(mode_for)] = "trade"
    store.write(values)


async def test_trading_arms_only_for_the_client_it_was_enabled_for():
    """The settings file is shared by every client on the machine.

    An unscoped mode in it would hand order placement to all of them at once, which is
    why `load` refuses to read that name from the file. The scoped name is what the form
    writes, and only the client whose handshake matches it gets the mutating tools.
    """
    credentialled(mode_for="Claude Desktop")

    async with connected(client_name="Claude Desktop") as session:
        names = await session.tool_names()
        assert "place_order" in names
        assert "get_trading_status" in names
        assert (await session.call("get_connection_status"))["mode"] == "trade"

    async with connected(client_name="Cursor") as session:
        names = await session.tool_names()
        assert "place_order" not in names
        status = await session.call("get_connection_status")
        assert status["mode"] == "read"
        assert status["mode_after_restart"] == "read"


async def test_the_client_name_is_matched_however_it_is_punctuated():
    """Clients name themselves freely — "Claude Desktop", "claude-ai", "claude.ai"."""
    credentialled(mode_for="claude-ai")
    async with connected(client_name="Claude AI") as session:
        assert "place_order" in await session.tool_names()


async def test_choosing_trade_does_not_arm_it_in_the_session_that_chose_it(accepted):
    """The restart is the point. Order placement appearing mid-conversation, in the same
    turn that asked for it, is exactly what the whole gate exists to prevent.
    """
    async with connected(client_name="Claude Desktop") as session:
        await session.call("setup_credentials")
        result = await session.call(
            "save_credentials",
            environment="india_testnet",
            api_key=KEY,
            api_secret=SECRET,
            mode="trade",
        )
        assert result["status"] == "saved"
        assert "Restart this app to turn trading on" in result["message"]

        # The reads came up; the mutations did not.
        assert "get_positions" in await session.tool_names()
        assert "place_order" not in await session.tool_names()

        status = await session.call("get_connection_status")
        assert status["mode"] == "read"
        assert status["mode_after_restart"] == "trade"
        # It must not claim everything is done while trading still waits.
        assert status["restart_required"] is True

    # The written entitlement is what the next start reads.
    assert store.read()[config_mod.mode_key("Claude Desktop")] == "trade"
    async with connected(client_name="Claude Desktop") as session:
        assert "place_order" in await session.tool_names()


async def test_a_client_env_var_still_outranks_the_scoped_setting(monkeypatch):
    """Editing the client's own config stays the most deliberate thing anyone can do."""
    credentialled(mode_for="Claude Desktop")
    monkeypatch.setenv("DELTA_MCP_MODE", "read")
    async with connected(client_name="Claude Desktop") as session:
        assert "place_order" not in await session.tool_names()


def rejecting(code, detail="delta api error: raw [http 401] (context={...})", ip=""):
    async def check(env, key, secret):
        return credentials.Check(
            ok=False, reachable=True, detail=detail, code=code, ip=ip
        )

    return check


async def test_a_key_from_the_other_site_names_the_choice_not_the_variable(monkeypatch):
    """The commonest first-run mistake, answered in the words on the form's own radios."""
    monkeypatch.setattr(credentials, "check", rejecting("invalid_api_key"))
    async with connected() as session:
        message = (await save(session))["message"]
        # save() picks the practice site, so that is what it was checked against and the
        # other choice is the one worth offering.
        assert "demo.delta.exchange" in message
        assert "Real account" in message


async def test_a_rejection_never_shows_the_form_the_message_meant_for_a_log(monkeypatch):
    """`delta api error:`, the raw code, DELTA_MCP_ENV and `[http 401]` mean nothing here.

    Appending readable copy to that string rather than replacing it left the user reading
    the machine's version first and the same advice twice.
    """
    monkeypatch.setattr(credentials, "check", rejecting("invalid_api_key"))
    async with connected() as session:
        message = (await save(session))["message"]
        for leak in ("delta api error", "DELTA_MCP_ENV", "http 401", "context=", "_api_key"):
            assert leak not in message, f"{leak!r} leaked into the form"


async def test_a_blocked_ip_says_so_and_shows_the_address_delta_saw(monkeypatch):
    """Telling someone to switch sites over an unwhitelisted IP sends them nowhere useful."""
    monkeypatch.setattr(
        credentials, "check", rejecting("ip_not_whitelisted_for_api_key", ip="1.2.3.4")
    )
    async with connected() as session:
        message = (await save(session))["message"]
        assert "1.2.3.4" in message
        assert "whitelisted" in message
        assert "demo.delta.exchange" not in message


async def test_a_key_without_read_data_says_which_permission_to_add(monkeypatch):
    monkeypatch.setattr(credentials, "check", rejecting("unauthorized_api_access"))
    async with connected() as session:
        assert "Read Data" in (await save(session))["message"]


async def test_an_unanticipated_failure_keeps_the_raw_message(monkeypatch):
    """For a code nobody wrote copy for, the raw text is the only information there is."""
    monkeypatch.setattr(
        credentials, "check", rejecting("SomethingNew", detail="delta api error: SomethingNew")
    )
    async with connected() as session:
        assert "SomethingNew" in (await save(session))["message"]


async def test_a_key_delta_rejects_changes_nothing(monkeypatch):
    async def rejected(env, key, secret):
        return credentials.Check(
            ok=False, reachable=True, detail="delta api error: InvalidApiKey"
        )

    monkeypatch.setattr(credentials, "check", rejected)
    async with connected() as session:
        assert (await save(session))["status"] == "rejected"
        assert not session.saw_tool_list_changed()
        assert "get_positions" not in await session.tool_names()
