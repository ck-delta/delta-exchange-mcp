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

Two later facts come from the spec itself (`src/spec.types.ts` in
modelcontextprotocol/ext-apps) rather than from the probe. The host's reply to
`ui/initialize` carries a `hostContext` with the active theme and a palette of CSS custom
properties, refreshed by a `ui/notifications/host-context-changed` notification; the view
reads both and falls back to Delta's own neutrals, so a host that sends nothing still looks
deliberate. And `prefersBorder` is the field that decides who draws the box — omitting it
left Claude Desktop drawing one and this view drawing a second inside it. There is no
`preferredSize` field; the height is whatever the view reports.

Colour is split on purpose. Surfaces, text and borders prefer the host's tokens, so the
form sits inside whatever theme the client is running. Brand and semantic colours are
always Delta's own, taken from the `--brand-india-*`, `--positive-*` and `--negative-*`
families on delta.exchange, because those are what make it recognisably Delta rather than
a generic form. The one brand asset that could not come across is the Aileron typeface —
it is a web font, and fetching it would hit the same policy that blanks the frame.

Everything the host can decide, the host decides. The view sets no pixel size, no width and
no spacing scale: type comes from the `--font-text-*` and `--font-heading-*` tokens, one
`--gap` in em follows whatever that type turns out to be, and the fields, radios, checkbox
and select are left as the platform draws them. That last part is why `color-scheme` matters
beyond the `light-dark()` it enables — it is what makes a native field render dark inside a
dark client, for free. A hand-styled field with its own padding, border and background was
what looked wrong in Codex: the numbers were tuned against an assumed 14px base and the host
does not run one. Fonts are the same story from the other side: the host may send
`@font-face` rules in `hostContext.styles.css.fonts`, and the spec makes installing them the
app's job, so a view that ignores them names a family in `--font-sans` that its own frame
never loaded.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from delta_exchange_mcp import credentials, store
from delta_exchange_mcp.config import (
    BASE_URLS,
    DASHBOARDS,
    DEFAULT_ENV,
    DEFAULT_MODE,
    MODES,
    mode_key,
)

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
<style id="host-fonts"></style>
<style>
  /* Nothing below sets a pixel size, a width or a spacing step of its own. Type comes from
     the host's typography tokens, spacing is one em-relative step that tracks that type,
     and the native form controls are left as the platform draws them. What is left is
     Delta's brand colour and the two pieces of layout that are genuinely structural: the
     logo beside the title, and the checkbox opposite the link. */
  :root {
    color-scheme: light dark;
    /* Delta's own, always. These are the colours that make it Delta rather than a form. */
    --brand: #fe6c02;
    --brand-hover: #e76202;
    --on-brand: #ffffff;
    /* The host's tokens, falling back to the platform's own system colours rather than to
       literals, so a host that sends no palette still lands on the right side of light or
       dark by way of the color-scheme above. */
    --ink: var(--color-text-primary, canvastext);
    --muted: var(--color-text-secondary, color-mix(in srgb, canvastext 66%, canvas));
    --faint: var(--color-text-tertiary, color-mix(in srgb, canvastext 48%, canvas));
    --positive: var(--color-text-success, #00a876);
    --negative: var(--color-text-danger, #dc4e4e);
    --sans: var(--font-sans, ui-sans-serif, system-ui, -apple-system, sans-serif);
    --mono: var(--font-mono, ui-monospace, SFMono-Regular, Menlo, Consolas, monospace);
    --small: var(--font-text-sm-size, .875em);
    --radius: var(--border-radius-md, 6px);
    /* One spacing step for the whole view, in em, so it follows the host's type size
       instead of being tuned against an assumed one. */
    --gap: 1em;
  }

  /* An opaque background on either of these paints over the chat behind the frame. */
  html, body { margin: 0; background: transparent; }
  body { font-family: var(--sans); font-size: var(--font-text-md-size, 1rem);
         line-height: var(--font-text-md-line-height, 1.5); color: var(--ink); }
  p { margin: 0 0 var(--gap); }

  .head { display: flex; align-items: center; gap: .5em; }
  .mark { width: 1.35em; height: 1.35em; flex: none; }
  h1 { font-size: var(--font-heading-xs-size, 1em); margin: 0;
       font-weight: var(--font-weight-semibold, 600);
       line-height: var(--font-heading-xs-line-height, inherit); }
  .sub, .note, legend, .lab, .reveal, #state, #done p { font-size: var(--small);
      color: var(--muted); }
  .note:empty { display: none; }

  fieldset { border: 0; padding: 0; margin: 0 0 var(--gap); }
  legend { padding: 0; }
  .lab { display: block; }
  .choice { display: block; cursor: pointer; }
  .choice .site { color: var(--faint); }

  /* Native controls, drawn by the platform. `font` is the one thing they do not inherit,
     and the color-scheme above is what makes their chrome match the client's theme —
     restyling them by hand is what previously fought the host's own metrics. A native
     select also draws its menu outside the frame, so it cannot be clipped by the app's
     bounds the way a hand-built one would be. */
  input, select, button { font: inherit; }
  input[type=text], input[type=password] { font-family: var(--mono); }
  input[type=text], input[type=password], select {
      width: 100%; box-sizing: border-box; margin: 0 0 var(--gap); }
  input[type=radio], input[type=checkbox] { accent-color: var(--brand); }
  input::placeholder { font-family: var(--sans); color: var(--faint); }

  .row { display: flex; align-items: center; justify-content: space-between;
         gap: var(--gap); flex-wrap: wrap; margin-bottom: var(--gap); }
  .reveal { display: flex; align-items: center; gap: .4em; cursor: pointer; }

  button { background: var(--brand); color: var(--on-brand); border: 0; cursor: pointer;
           font-weight: var(--font-weight-medium, 500); padding: .5em 1.1em;
           border-radius: var(--radius); }
  button:hover { background: var(--brand-hover); }
  button[aria-disabled=true], button[aria-disabled=true]:hover {
      background: color-mix(in srgb, var(--ink) 14%, transparent);
      color: var(--faint); cursor: not-allowed; }
  button.link, button.link:hover { background: none; color: var(--muted); padding: 0;
      font-size: var(--small); font-weight: inherit; text-decoration: underline;
      text-underline-offset: 2px; }
  button.link[aria-disabled=true] { background: none; color: var(--faint); }

  :focus-visible { outline: 2px solid var(--brand); outline-offset: 2px; }

  #state:not(:empty) { margin-top: var(--gap); }
  #state.err { color: var(--negative); }

  #done { display: none; }
  body.done #entry { display: none; }
  body.done #done { display: block; }
  #done .who { color: var(--positive); font-weight: var(--font-weight-semibold, 600);
               font-size: inherit; }
</style>
</head>
<body>
  <div class="head">
    <!-- Delta's own mark, inlined. The one gradient in the original is flattened to its
         midpoint: it is imperceptible at 20px, and painting it needs a fragment reference
         written in the same syntax the test bans to keep external fetches out. -->
    <svg class="mark" viewBox="0 0 53 52" aria-hidden="true">
      <path fill="#FD7D02" d="M17.834 17.334 35.166 26 52.5 17.334 17.834 0v17.334Z"/>
      <path fill="#219b21" d="M17.834 34.667V52L52.5 34.667 35.166 26l-17.332 8.667Z"/>
      <path fill="#2CB72C" d="M52.5 34.667V17.333L35.167 26 52.5 34.667Z"/>
      <path fill="#FF9300" d="M17.832 17.333v17.334L.5 26l17.332-8.667Z"/>
    </svg>
    <h1>Connect your Delta Exchange account</h1>
  </div>

  <div id="done">
    <p class="who" id="done-who"></p>
    <p id="done-where"></p>
    <p class="next" id="done-next"></p>
    <button id="again" class="link" type="button">Use a different key</button>
  </div>

  <div id="entry">
    <p class="sub">Type your key here rather than in the chat. It is saved to a file on
    this computer, and the assistant never sees it.</p>

    <fieldset id="envs">
      <legend>Where was your key created?</legend>
    </fieldset>

    <label class="lab" for="mode">What should the assistant be able to do?</label>
    <select id="mode">
      <option value="read">Read only &mdash; balances, positions and orders</option>
      <option value="trade">Read and trade &mdash; also place and cancel orders</option>
    </select>
    <p class="note" id="mode-note"></p>

    <label class="lab" for="key">API key</label>
    <input id="key" type="password" autocomplete="off" autocapitalize="none"
           spellcheck="false" placeholder="paste it here">

    <label class="lab" for="secret">API secret</label>
    <input id="secret" type="password" autocomplete="off" autocapitalize="none"
           spellcheck="false" placeholder="shown only once, when you create the key">

    <div class="row">
      <label class="reveal"><input id="show" type="checkbox">Show what I typed</label>
      <button id="create" class="link" type="button" aria-disabled="true">
        Get a key &mdash; Read Data is enough</button>
    </div>

    <button id="save" type="button" aria-disabled="true">Check and save</button>
  </div>
  <div id="state" role="status" aria-live="polite"></div>
<script>
(function () {
  var CONFIG = __CONFIG__;
  var PROTOCOL = "2026-01-26";
  var nextId = 1;
  var pending = {};
  var ready = false;
  var saving = false;

  var root = document.documentElement;
  var hostFonts = document.getElementById("host-fonts");
  var envsEl = document.getElementById("envs");
  var keyEl = document.getElementById("key");
  var secretEl = document.getElementById("secret");
  var showEl = document.getElementById("show");
  var saveEl = document.getElementById("save");
  var createEl = document.getElementById("create");
  var stateEl = document.getElementById("state");
  var modeEl = document.getElementById("mode");
  var modeNote = document.getElementById("mode-note");
  var againEl = document.getElementById("again");
  var doneWho = document.getElementById("done-who");
  var doneWhere = document.getElementById("done-where");
  var doneNext = document.getElementById("done-next");

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

  // Each variable is applied only when it has a value, so a host sending part of a palette
  // leaves the rest on the fallbacks rather than blanking them.
  function applyHostContext(ctx) {
    if (!ctx) return;
    if (ctx.theme) root.style.colorScheme = ctx.theme;
    var styles = ctx.styles || {};
    var vars = styles.variables;
    if (vars) {
      Object.keys(vars).forEach(function (name) {
        if (vars[name]) root.style.setProperty(name, vars[name]);
      });
    }
    // The host ships the rules that load its own typeface, and the spec makes installing
    // them the app's job. Skipping this leaves --font-sans naming a family the frame never
    // loaded, so every measurement below is taken against a substituted face instead.
    var fonts = styles.css && styles.css.fonts;
    if (fonts) hostFonts.textContent = fonts;
    resize();
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
    // A notification carries a method and no id, so it matches neither of the branches
    // around it. This is how a theme switch mid-conversation arrives.
    if (msg.method !== undefined && msg.id === undefined) {
      if (msg.method === "ui/notifications/host-context-changed") applyHostContext(msg.params);
      return;
    }
    // The host may call into the view; answer rather than ignore, so a host waiting on a
    // reply is not left holding a request that never settles.
    if (msg.method !== undefined && msg.id !== undefined) {
      post({ jsonrpc: "2.0", id: msg.id,
             error: { code: -32601, message: "not implemented: " + msg.method } });
    }
  });

  // scrollHeight never reports less than the frame it is measured in, so reporting it can
  // only grow the frame: one long error message would leave it tall for the rest of the
  // conversation. Forcing intrinsic sizing for the measurement reports the content itself.
  function resize() {
    var previous = root.style.height;
    root.style.height = "max-content";
    var height = Math.ceil(root.getBoundingClientRect().height);
    root.style.height = previous;
    post({ jsonrpc: "2.0", method: "ui/notifications/size-changed",
           params: { height: height } });
  }

  // aria-disabled rather than disabled, because disabling a control while it holds focus
  // drops focus to the body. It does not block clicks, so every handler checks it.
  function enable(el, on) {
    if (on) el.removeAttribute("aria-disabled");
    else el.setAttribute("aria-disabled", "true");
  }

  function off(el) { return el.getAttribute("aria-disabled") === "true"; }

  function refreshSaveState() {
    enable(saveEl, ready && !saving && !!keyEl.value.trim() && !!secretEl.value.trim());
  }

  showEl.addEventListener("change", function () {
    var type = showEl.checked ? "text" : "password";
    keyEl.type = type;
    secretEl.type = type;
  });

  keyEl.addEventListener("input", refreshSaveState);
  secretEl.addEventListener("input", refreshSaveState);

  // Says what the choice costs before it is made. Trading is scoped to this client, so
  // the reassurance about the others is the part worth stating.
  function syncModeNote() {
    modeNote.textContent = modeEl.value === "trade"
      ? "Trading turns on after you restart this app. Other apps on this computer stay "
        + "read only."
      : "";
    resize();
  }

  modeEl.addEventListener("change", syncModeNote);

  againEl.addEventListener("click", function () {
    document.body.classList.remove("done");
    refreshSaveState();
    resize();
    keyEl.focus();
  });

  createEl.addEventListener("click", function () {
    if (off(createEl)) return;
    var url = CONFIG.dashboards[chosenEnv()];
    if (!url) { say("No key page for that environment.", "err"); return; }
    request("ui/open-link", { url: url }).catch(function (err) {
      say("This client would not open a link. Go to " + url + " yourself.", "err");
    });
  });

  saveEl.addEventListener("click", function () {
    if (off(saveEl) || saving) return;
    var key = keyEl.value.trim();
    var secret = secretEl.value.trim();
    saving = true;
    refreshSaveState();
    say("Checking the key against Delta\\u2026");
    // Longer than the default: this call asks Delta about the key, and the client behind
    // it backs off and retries a rate limit. Timing out sooner than the work can finish
    // would report a failure over a key that was in fact saved.
    request("tools/call", {
      name: "save_credentials",
      arguments: {
        environment: chosenEnv(), api_key: key, api_secret: secret, mode: modeEl.value,
      },
    }, 120000).then(function (result) {
      var payload = readResult(result);
      var status = payload.status || "failed";
      // These three all wrote the key and differ only in what there is to say about it.
      // Anything else did not, so the fields stay as typed and the button comes back.
      var stored = status === "saved" || status === "unverified" || status === "overridden";
      if (stored) {
        // Do not leave a secret sitting in a rendered field once it is stored.
        keyEl.value = "";
        secretEl.value = "";
        showEl.checked = false;
        keyEl.type = secretEl.type = "password";
      }
      saving = false;
      refreshSaveState();
      // Only a clean save swaps the form out. The other two stored cases still need the
      // fields, because what they say is "saved, and here is what to fix".
      if (status === "saved" && payload.account) {
        doneWho.textContent = "Connected as " + payload.account;
        doneWhere.textContent = "Saved to " + (payload.path || "this computer");
        doneNext.textContent = payload.next_step || "";
        document.body.classList.add("done");
        say("");
        return;
      }
      say(payload.message || status, stored ? "" : "err");
    }).catch(function (err) {
      saving = false;
      refreshSaveState();
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

  request("ui/initialize", {
    appCapabilities: {},
    appInfo: { name: "Delta Exchange credentials", version: "1" },
    protocolVersion: PROTOCOL,
  }).then(function (result) {
    post({ jsonrpc: "2.0", method: "ui/notifications/initialized" });
    ready = true;
    enable(createEl, true);
    refreshSaveState();
    // The theme and the palette arrive here. Discarding this result is what left the view
    // styling itself off the operating system rather than off the client it renders in.
    applyHostContext(result && result.hostContext);
    // The mode already in force for this client. Without asking, the control would show
    // "Read only" to someone who had already enabled trading, and saving would quietly
    // take it away again.
    request("tools/call", { name: "get_connection_status", arguments: {} }, 15000)
      .then(function (status) {
        var now = readResult(status);
        // What it will be after a restart, not what is live: someone who chose trading a
        // moment ago must not be shown "Read only" and quietly downgraded on the next save.
        var current = now && (now.mode_after_restart || now.mode);
        if (current) { modeEl.value = current; syncModeNote(); }
      })
      .catch(function () {});
    resize();
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


# Delta spells each of these two ways depending on the endpoint.
_KEY_NOT_FOUND = {"InvalidApiKey", "invalid_api_key"}
_NO_PERMISSION = {"UnauthorizedApiAccess", "unauthorized_api_access"}
_IP_BLOCKED = {"ip_not_whitelisted_for_api_key"}


def _rejection(env: str, result: credentials.Check) -> str:
    """What the form says when Delta turns the key down.

    Deliberately replaces the message from `errors.py` rather than adding to it. That one
    is written for a log — it opens with `delta api error:`, quotes the raw code, names
    DELTA_MCP_ENV and ends in `[http 401]` — and none of that is actionable for someone
    looking at two text fields and a pair of radio buttons. Each case here names the thing
    on screen they can change instead.

    Anything without copy of its own keeps the raw message, because for a failure nobody
    anticipated it is the only information there is.
    """
    chosen = next((e for e in ENVIRONMENTS if e["value"] == env), None)
    other = next((e for e in ENVIRONMENTS if e["value"] != env), None)

    if result.code in _KEY_NOT_FOUND and chosen and other:
        return (
            f"Delta does not recognise this key on {chosen['site']}. A key only works on "
            f"the site it was created on — if you made this one on {other['site']}, pick "
            f"{other['label']} above. Otherwise check that both the key and the secret "
            "were pasted in full."
        )
    if result.code in _NO_PERMISSION:
        return (
            "This key cannot read your account. Give it the Read Data permission under "
            "Account → API Keys on Delta, then save again."
        )
    if result.code in _IP_BLOCKED:
        seen = f" It saw {result.ip}." if result.ip else ""
        return (
            "Delta blocked this request because the key only accepts whitelisted IP "
            f"addresses and this computer is not on its list.{seen} Add it to the key "
            "under Account → API Keys, then save again."
        )
    return f"Delta rejected this key. {result.detail}"


def _override_message(overridden: list[str]) -> str:
    """What to say when the client's own configuration outranks what was just saved.

    The two cases fail differently and need saying differently. A client supplying its own
    key discards this one outright. A client supplying only the environment still uses this
    key, against the site it was not created on, where Delta rejects it as unknown.
    """
    if {"DELTA_API_KEY", "DELTA_API_SECRET"} & set(overridden):
        consequence = "so this key will not be used at all"
    else:
        consequence = (
            "so your key will be used against the other site, where Delta will reject it "
            "as a key it has never seen"
        )
    return (
        f"Saved to {store.path()}, but this client sets {', '.join(overridden)} in its own "
        f"configuration, and that beats the file — {consequence}. Clear those from this "
        "client's MCP entry, or from the fields it asked you to fill in when you installed "
        "it, and then restart it. Restarting on its own will not help, because the client "
        "passes its own value again every time it starts."
    )


def _client_name(ctx: Context) -> str:
    """What the connected client called itself, or "" when there is no session to ask.

    The session hangs off the request context, and FastMCP raises rather than returning
    None when there is none — which is what calling the tool in-process does, as the
    tests do. An empty name is handled by the caller, since a trading mode that cannot be
    scoped to a client must not be written at all.
    """
    try:
        params = ctx.session.client_params
    except ValueError:
        return ""
    return params.clientInfo.name if params and params.clientInfo else ""


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
    which is something the user can see happen. The `mode` argument does not widen it:
    it is written scoped to the calling client and takes effect only on that client's
    next start, so the most it can do is arm trading against a key its caller supplied.
    """
    shown = False

    @mcp.tool(meta=_OPENS_VIEW)
    async def setup_credentials() -> dict[str, str]:
        """Open a form for the user to enter their Delta API key, kept out of the chat.

        Call this whenever the user wants to log in, sign in, connect their Delta
        account, add or replace an API key, turn trading on or off for this client, or
        when an account tool is unavailable because none is configured. Call this first
        even when they say "login" — the `login` terminal command is the fallback for
        clients that cannot display a form, and whether this one can is reported back to
        you by this tool. Never ask for the key or secret in the conversation instead.
        """
        nonlocal shown
        shown = True
        return {"status": "form_opened", "instructions": _opened_message()}

    @mcp.tool(meta=_APP_ONLY)
    async def save_credentials(
        environment: str, api_key: str, api_secret: str, ctx: Context, mode: str = "read"
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

        wanted = (mode or "").strip().lower() or DEFAULT_MODE
        if wanted not in MODES:
            return {
                "status": "invalid",
                "message": f"{mode!r} is not one of {sorted(MODES)}.",
            }

        # Trading is stored against the name this client gave in the handshake, never
        # under a shared one: the settings file is read by every client on the machine,
        # and one unscoped value would arm order placement in all of them.
        # Tested on the key rather than the name: a name made only of punctuation is
        # truthy but yields no key, and the mode would be dropped while this reported
        # that trading was on.
        client = _client_name(ctx)
        if wanted == "trade" and not mode_key(client):
            return {
                "status": "invalid",
                "message": (
                    "This client did not say who it is during the handshake, so trading "
                    "cannot be turned on for it alone. Save with read only, then set "
                    "DELTA_MCP_MODE=trade in this client's own configuration."
                ),
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
            return {"status": "rejected", "message": _rejection(env, result)}

        problem = credentials.save(env, key, secret, client, wanted)
        if problem is not None:
            return {"status": "failed", "message": problem}

        # Checked after the write, not before it: the file is what every other client on
        # this machine reads, so the key still belongs there even when this one ignores it.
        overridden = credentials.overridden_by_client()
        if overridden:
            return {
                "status": "overridden",
                "path": str(store.path()),
                "message": _override_message(overridden),
            }

        # Leads with carrying on rather than restarting. The tools are registered by then,
        # so the only open question is whether this client acted on being told the list
        # changed, and asking it something settles that faster than a restart nobody needed.
        ready = await activate(ctx.session) if activate is not None else False
        reads = (
            "Your account tools are live in this session — just ask about your account. "
            "If this client does not show them yet, restart it."
            if ready
            else "Restart this client to use your account."
        )
        # Trading is never armed in the session that asked for it. `activate` cannot see
        # that it was asked for either — the mode it reads comes from the environment, and
        # what was just written is scoped to this client in the file — so the restart has
        # to be stated here rather than inferred from what `activate` returned.
        next_step = (
            f"{reads} Restart this app to turn trading on for it; other apps on this "
            "computer stay read only."
            if wanted == "trade"
            else reads
        )

        if not result.reachable:
            # Saved unverified on purpose: a flaky connection must not cost someone a key
            # they typed correctly, and the next real call will report the truth anyway.
            return {
                "status": "unverified",
                "path": str(store.path()),
                "message": (
                    f"Saved to {store.path()}, but Delta could not be reached to check "
                    f"it. {result.detail} {next_step}"
                ),
            }

        # The account email is included because it is the only signal that distinguishes
        # "saved" from "saved the wrong account's key", and it is not a new disclosure:
        # any assistant with these credentials can read it from the profile endpoint.
        who = f" as {result.detail}" if result.detail else ""
        # The same facts twice: as fields, because the view renders them as its own
        # connected state rather than printing a paragraph, and as one sentence, because
        # that is what a client without a view has to show.
        return {
            "status": "saved",
            "account": result.detail,
            "path": str(store.path()),
            "next_step": next_step,
            "message": (
                f"Connected{who}. Saved to {store.path()}. {next_step}"
                if wanted == "trade"
                else f"Connected{who}. Saved to {store.path()}. {next_step} Trading stays "
                "off — you can turn it on for this app in the same form."
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
        # `prefersBorder` is what decides who draws the box. Omitting it left Claude
        # Desktop drawing one and this view drawing a second inside it. There is no
        # `preferredSize` in the spec — the height comes from what the view reports.
        meta={"ui": {"prefersBorder": True}},
    )
    def credentials_view() -> str:
        return VIEW_HTML
