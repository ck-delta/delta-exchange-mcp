"""An in-chat form for entering an API key, so nobody has to open a terminal.

Every other way of setting a credential asks the user to leave the conversation: edit a
JSON file whose shape differs per client, or run a command. Marketing tried both and got
stuck on which file and whether a terminal was required, which is the problem this
solves. MCP Apps (SEP-1865) lets a server ship a small HTML view that the client renders
inline, so the key is typed into a field a few lines below the question that prompted it.

The point is not convenience. What is typed into the view is typed into an iframe the
model cannot read, and it reaches this process as the arguments of a view-initiated tool
call. Asking the user to paste a key into the chat instead would put the secret into the
model's context and into the stored conversation permanently. That difference was
measured rather than assumed: a probe against Claude Desktop 1.0.0 (protocol 2025-11-25)
and Codex desktop (codex-mcp-client 0.146.0-alpha.9.2, protocol 2025-06-18) confirmed a
value typed into a view does not reach the model, and does not appear in host logs.

Three constraints came out of that probe and are load-bearing here:

* Everything is inlined. Both hosts apply a content-security policy that blocks any
  external fetch, so a stylesheet, font or script from a CDN leaves the frame blank.
* The handshake must complete. A view that does not answer `ui/initialize` and then send
  `ui/notifications/initialized` stays collapsed with nothing shown.
* Host capabilities cannot be used as a feature test. Claude Desktop renders MCP Apps
  without advertising the `io.modelcontextprotocol/ui` extension at all, so gating on
  that capability would disable the form on a client that supports it.

Not every client renders MCP Apps. `setup_credentials` therefore returns text that names
the file and the `login` command as well, so on a client that shows nothing the model
still has something correct to say.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from delta_exchange_mcp import credentials, store
from delta_exchange_mcp.config import BASE_URLS, DASHBOARDS, DEFAULT_ENV

# Given the session to notify on, brings the tool list up to date for a credential that
# was just saved, and reports whether anything is still waiting for a restart.
Activate = Callable[[ServerSession], Awaitable[bool]]

VIEW_URI = "ui://delta-exchange/credentials.html"

# The profile parameter is what marks an HTML resource as an app view rather than a
# document; a client renders it in a sandboxed frame instead of treating it as content.
VIEW_MIME = "text/html;profile=mcp-app"

# Both spellings of the same association. The nested form is what SEP-1865 specifies and
# the flat one is what earlier implementations read; sending both costs nothing and
# neither host was willing to say which it uses.
_OPENS_VIEW = {"ui": {"resourceUri": VIEW_URI}, "ui/resourceUri": VIEW_URI}

# Hides the tool from the model while leaving it callable from inside the view. Verified
# honoured by both hosts. See `register` for what happens on a client that ignores it.
_APP_ONLY = {"ui": {"visibility": ["app"]}}

ENVIRONMENTS = [
    {
        "value": "india_prod",
        "label": "Real account",
        "site": "delta.exchange",
    },
    {
        "value": "india_testnet",
        "label": "Practice account",
        "site": "demo.delta.exchange",
    },
]

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>Connect your Delta Exchange account</title>
<style>
  html, body { margin: 0; }
  body { font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, sans-serif; padding: 14px; }
  .card { border: 1px solid color-mix(in srgb, currentColor 20%, transparent);
          border-radius: 10px; padding: 16px; max-width: 520px; }
  h1 { font-size: 15px; margin: 0 0 4px; }
  .sub { margin: 0 0 14px; opacity: .72; font-size: 13px; }
  fieldset { border: 0; padding: 0; margin: 0 0 12px; }
  legend { font-size: 12px; opacity: .8; padding: 0 0 5px; }
  .choice { display: block; margin-bottom: 4px; font-size: 13px; }
  .choice input { margin-right: 7px; }
  .choice .site { opacity: .6; }
  label.field { display: block; font-size: 12px; opacity: .8; margin-bottom: 3px; }
  input[type=text], input[type=password] {
      font: inherit; width: 100%; box-sizing: border-box; padding: 7px 9px;
      margin-bottom: 10px; border-radius: 6px; color: inherit; background: transparent;
      border: 1px solid color-mix(in srgb, currentColor 28%, transparent); }
  .reveal { font-size: 12px; opacity: .75; margin-bottom: 12px; display: block; }
  .reveal input { margin-right: 6px; }
  button { font: inherit; padding: 8px 15px; border-radius: 6px; cursor: pointer;
           border: 1px solid color-mix(in srgb, currentColor 30%, transparent);
           background: transparent; color: inherit; }
  button[disabled] { opacity: .45; cursor: default; }
  button.link { border: 0; padding: 0; text-decoration: underline; font-size: 13px;
                opacity: .85; }
  .hint { font-size: 12px; opacity: .72; margin: 0 0 14px; }
  #state { margin-top: 12px; font-size: 13px; min-height: 1.4em; }
  .ok { color: #16a34a; } .err { color: #dc2626; }
</style>
</head>
<body>
<div class="card">
  <h1>Connect your Delta Exchange account</h1>
  <p class="sub">What you type here is saved to a file on this computer. It does not
  become part of this conversation, and the assistant cannot read it.</p>

  <fieldset id="envs">
    <legend>Where was your key created?</legend>
  </fieldset>

  <p class="hint">
    A key only works on the site it was created on. Under Account &rarr; API Keys,
    the <strong>Read Data</strong> permission is enough unless you intend to trade,
    and the key needs your IP whitelisted.
    <button id="create" class="link" type="button" disabled>Open the API keys page</button>
  </p>

  <label class="field" for="key">API key</label>
  <input id="key" type="password" autocomplete="off" spellcheck="false"
         placeholder="paste or type it here">

  <label class="field" for="secret">API secret</label>
  <input id="secret" type="password" autocomplete="off" spellcheck="false"
         placeholder="shown only once, when you create the key">

  <label class="reveal"><input id="show" type="checkbox">Show what I typed</label>

  <button id="save" type="button" disabled>Check and save</button>
  <div id="state">Starting&hellip;</div>
</div>
<script>
(function () {
  var CONFIG = __CONFIG__;
  var PROTOCOL = "2026-01-26";
  var nextId = 1;
  var pending = {};

  var envsEl = document.getElementById("envs");
  var keyEl = document.getElementById("key");
  var secretEl = document.getElementById("secret");
  var showEl = document.getElementById("show");
  var saveEl = document.getElementById("save");
  var createEl = document.getElementById("create");
  var stateEl = document.getElementById("state");

  CONFIG.environments.forEach(function (env, i) {
    var row = document.createElement("label");
    row.className = "choice";
    var radio = document.createElement("input");
    radio.type = "radio";
    radio.name = "env";
    radio.value = env.value;
    radio.checked = env.value === CONFIG.default_environment || (i === 0 && !CONFIG.default_environment);
    row.appendChild(radio);
    row.appendChild(document.createTextNode(env.label + " "));
    var site = document.createElement("span");
    site.className = "site";
    site.textContent = "\\u2014 " + env.site;
    row.appendChild(site);
    envsEl.appendChild(row);
  });

  function chosenEnv() {
    var picked = envsEl.querySelector("input[name=env]:checked");
    return picked ? picked.value : CONFIG.default_environment;
  }

  function say(text, cls) {
    stateEl.textContent = text;
    stateEl.className = cls || "";
    resize();
  }

  function post(msg) { window.parent.postMessage(msg, "*"); }

  function request(method, params, timeoutMs) {
    var id = nextId++;
    post({ jsonrpc: "2.0", id: id, method: method, params: params || {} });
    return new Promise(function (resolve, reject) {
      pending[id] = { resolve: resolve, reject: reject };
      setTimeout(function () {
        if (pending[id]) { delete pending[id]; reject(new Error(method + " timed out")); }
      }, timeoutMs || 30000);
    });
  }

  window.addEventListener("message", function (event) {
    if (event.source !== window.parent) return;
    var msg = event.data;
    if (!msg || msg.jsonrpc !== "2.0") return;
    if (msg.id !== undefined && msg.method === undefined) {
      var p = pending[msg.id];
      if (!p) return;
      delete pending[msg.id];
      if (msg.error) p.reject(new Error(msg.error.message || "request failed"));
      else p.resolve(msg.result);
      return;
    }
    // The host may call into the view; answer rather than ignore, so a host waiting on a
    // reply is not left holding a request that never settles.
    if (msg.method !== undefined && msg.id !== undefined) {
      post({ jsonrpc: "2.0", id: msg.id,
             error: { code: -32601, message: "not implemented: " + msg.method } });
    }
  });

  function resize() {
    post({ jsonrpc: "2.0", method: "ui/notifications/size-changed",
           params: { height: document.documentElement.scrollHeight } });
  }

  function refreshSaveState() {
    saveEl.disabled = !ready || !keyEl.value.trim() || !secretEl.value.trim();
  }

  showEl.addEventListener("change", function () {
    var type = showEl.checked ? "text" : "password";
    keyEl.type = type;
    secretEl.type = type;
  });

  keyEl.addEventListener("input", refreshSaveState);
  secretEl.addEventListener("input", refreshSaveState);

  createEl.addEventListener("click", function () {
    var url = CONFIG.dashboards[chosenEnv()];
    if (!url) { say("No key page for that environment.", "err"); return; }
    request("ui/open-link", { url: url }).catch(function (err) {
      say("This client would not open a link. Go to " + url + " yourself.", "err");
    });
  });

  saveEl.addEventListener("click", function () {
    var key = keyEl.value.trim();
    var secret = secretEl.value.trim();
    saveEl.disabled = true;
    say("Checking the key against Delta\\u2026");
    // Longer than the default: this call asks Delta about the key, and the client behind
    // it backs off and retries a rate limit. Timing out sooner than the work can finish
    // would report a failure over a key that was in fact saved.
    request("tools/call", {
      name: "save_credentials",
      arguments: { environment: chosenEnv(), api_key: key, api_secret: secret },
    }, 120000).then(function (result) {
      var payload = readResult(result);
      var status = payload.status || "failed";
      if (status === "saved" || status === "unverified") {
        // Do not leave a secret sitting in a rendered field once it is stored.
        keyEl.value = "";
        secretEl.value = "";
        showEl.checked = false;
        keyEl.type = secretEl.type = "password";
      } else {
        saveEl.disabled = false;
      }
      say(payload.message || status, status === "saved" ? "ok" : status === "unverified" ? "" : "err");
    }).catch(function (err) {
      saveEl.disabled = false;
      say("Could not tell whether it saved: " + err.message +
          ". Restart this client and ask whether your account is connected.", "err");
    });
  });

  function readResult(result) {
    // Hosts differ over whether a tool result arrives parsed in structuredContent or as
    // JSON text; try the parsed form first and fall back rather than pick one.
    if (result && result.structuredContent) return result.structuredContent;
    var content = (result && result.content) || [];
    for (var i = 0; i < content.length; i++) {
      if (content[i] && content[i].type === "text") {
        try { return JSON.parse(content[i].text); } catch (e) { return { message: content[i].text }; }
      }
    }
    return {};
  }

  var ready = false;
  say("Connecting to this app\\u2026");
  request("ui/initialize", {
    appCapabilities: {},
    appInfo: { name: "Delta Exchange credentials", version: "1" },
    protocolVersion: PROTOCOL,
  }).then(function () {
    post({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
    ready = true;
    createEl.disabled = false;
    refreshSaveState();
    say("");
    resize();
    keyEl.focus();
  }).catch(function (err) {
    say("This client could not open the form: " + err.message, "err");
  });

  window.addEventListener("resize", resize);
  resize();
})();
</script>
</body>
</html>
"""

VIEW_HTML = _TEMPLATE.replace(
    "__CONFIG__",
    json.dumps(
        {
            "environments": ENVIRONMENTS,
            "dashboards": DASHBOARDS,
            "default_environment": DEFAULT_ENV,
        }
    ),
)


def _opened_message() -> str:
    """What the model is told after opening the form.

    Deliberately says what *not* to do first. Left to itself a model asked for help with
    an API key will offer to take it in the chat, which is the one outcome this whole
    module exists to prevent, and the offer sounds helpful enough that people accept it.
    """
    return (
        "A form is now open in this conversation. Tell the user to type their API key "
        "and secret into it — never ask them to send a key or secret as a chat message, "
        "because anything sent that way is stored in this conversation and visible to "
        "you. You will not see what they type or whether it saved: call "
        "get_connection_status once they say they are done, which reports whether a key "
        "is configured and whether this client still has to be restarted. If no form "
        "appeared, this client cannot display one — tell them to run "
        "`uvx delta-exchange-mcp login` in a terminal, or to open "
        f"{store.path()} and fill in DELTA_API_KEY and DELTA_API_SECRET, then to restart "
        "this client."
    )


def register(mcp: FastMCP, activate: Activate | None = None) -> None:
    """Add the credential form and the two tools that drive it.

    `activate` brings up the surface a newly saved credential unlocks, in the running
    process, and reports whether anything is still outstanding. Without it a save can only
    end in "restart this client", which is a poor thing to say to someone in the middle of
    a conversation. It is optional so a test can register the form on its own rather than
    build a whole server.

    `save_credentials` is hidden from the model by `_meta.ui.visibility`, which both
    tested hosts honour. On a client that ignores it the tool becomes model-callable,
    so it is written to be harmless there: it returns no stored value and never reads
    the file back, meaning the worst a caller who does not already know the credentials
    can achieve is to overwrite them with a pair Delta accepts — which they would have
    to own. `shown` narrows even that, by requiring the form to have been opened first,
    which is something the user can see happen.
    """
    shown = False

    @mcp.tool(meta=_OPENS_VIEW)
    async def setup_credentials() -> dict[str, str]:
        """Open a form for the user to enter their Delta API key, kept out of the chat.

        Call this whenever the user wants to log in, sign in, connect their Delta
        account, add or replace an API key, or when an account tool is unavailable
        because none is configured. Call this first even when they say "login" — the
        `login` terminal command is the fallback for clients that cannot display a form,
        and whether this one can is reported back to you by this tool. Never ask for the
        key or secret in the conversation instead.
        """
        nonlocal shown
        shown = True
        return {"status": "form_opened", "instructions": _opened_message()}

    @mcp.tool(meta=_APP_ONLY)
    async def save_credentials(
        environment: str, api_key: str, api_secret: str, ctx: Context
    ) -> dict[str, str]:
        """Save a key typed into the credential form. Called by the form, not by you.

        The values come from what the user typed inside the form's own frame. Do not
        call this yourself, and do not ask the user for these values in the chat.
        """
        if not shown:
            return {
                "status": "refused",
                "message": "Open the credential form first.",
            }

        env = (environment or "").strip().lower()
        if env not in BASE_URLS:
            return {
                "status": "invalid",
                "message": f"{environment!r} is not one of {sorted(BASE_URLS)}.",
            }

        key = (api_key or "").strip()
        secret = (api_secret or "").strip()
        if not key or not secret:
            return {
                "status": "invalid",
                "message": (
                    "Both the key and its secret are needed — one without the other "
                    "leaves the server on market data only."
                ),
            }

        result = await credentials.check(env, key, secret)
        if result.reachable and not result.ok:
            return {"status": "rejected", "message": f"Delta rejected this key. {result.detail}"}

        problem = credentials.save(env, key, secret)
        if problem is not None:
            return {"status": "failed", "message": problem}

        # Leads with carrying on rather than restarting. The tools are registered by then,
        # so the only open question is whether this client acted on being told the list
        # changed, and asking it something settles that faster than a restart nobody needed.
        ready = await activate(ctx.session) if activate is not None else False
        next_step = (
            "Your account tools are live in this session — just ask about your account. "
            "If this client does not show them yet, restart it."
            if ready
            else "Restart this client to use your account."
        )

        if not result.reachable:
            # Saved unverified on purpose: a flaky connection must not cost someone a key
            # they typed correctly, and the next real call will report the truth anyway.
            return {
                "status": "unverified",
                "message": (
                    f"Saved to {store.path()}, but Delta could not be reached to check "
                    f"it. {result.detail} {next_step}"
                ),
            }

        # The account email is included because it is the only signal that distinguishes
        # "saved" from "saved the wrong account's key", and it is not a new disclosure:
        # any assistant with these credentials can read it from the profile endpoint.
        who = f" as {result.detail}" if result.detail else ""
        return {
            "status": "saved",
            "message": (
                f"Connected{who}. Saved to {store.path()}. {next_step} Trading stays "
                "off — that is enabled per client, not here."
            ),
        }

    # Named and titled rather than left to the function name: a host lists this resource
    # to the user, and `credentials_view` is not something anyone asked to open.
    @mcp.resource(
        VIEW_URI,
        name="credentials-form",
        title="Connect your Delta Exchange account",
        description="A form for entering a Delta API key without putting it in the chat.",
        mime_type=VIEW_MIME,
        meta={"ui": {"preferredSize": {"height": 560}}},
    )
    def credentials_view() -> str:
        return VIEW_HTML
