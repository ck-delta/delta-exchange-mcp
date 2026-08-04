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
async def connected(cfg=None):
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

            async with ClientSession(
                client_read, client_write, message_handler=collect
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


async def test_a_key_from_the_other_site_names_the_choice_not_the_variable(monkeypatch):
    """The commonest first-run mistake, answered in the words on the form's own radios."""

    async def not_found(env, key, secret):
        return credentials.Check(
            ok=False,
            reachable=True,
            detail="delta api error: InvalidApiKey — confirm DELTA_MCP_ENV matches",
            code="InvalidApiKey",
        )

    monkeypatch.setattr(credentials, "check", not_found)
    async with connected() as session:
        message = (await save(session))["message"]
        assert "Practice account" in message and "demo.delta.exchange" in message
        assert "Real account" in message and "delta.exchange" in message


async def test_a_failure_that_is_not_a_missing_key_gets_no_site_advice(monkeypatch):
    """Telling someone to switch sites over an unwhitelisted IP sends them nowhere useful."""

    async def blocked(env, key, secret):
        return credentials.Check(
            ok=False,
            reachable=True,
            detail="delta api error: ip_not_whitelisted_for_api_key (request IP: 1.2.3.4)",
            code="ip_not_whitelisted_for_api_key",
        )

    monkeypatch.setattr(credentials, "check", blocked)
    async with connected() as session:
        message = (await save(session))["message"]
        assert "1.2.3.4" in message
        assert "choose" not in message.lower()


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
