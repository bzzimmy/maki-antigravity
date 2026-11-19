maki-antigravity puts Google Antigravity behind a maki plugin provider. It
loads through the maki pack system, not as a builtin. Two parts:

- `plugin/maki_antigravity.lua`: one `maki.provider.register` call with the
  `google` codec and a loopback `base_url`, plus the job that starts the
  proxy. The `auth` hook mints access tokens from the agy refresh token in the
  system keyring and caches them, with the project id, through
  `maki.provider.auth`. `list_models` reads `fetchAvailableModels` and lists
  the model ids verbatim. `login` only checks the agy sign-in. There is no
  OAuth flow of its own and nothing is written to the keyring.
- `proxy/antigravity_proxy.py`: standard library only. Wraps maki's Gemini
  request in the Cloud Code Assist envelope, maps `-xhigh` thinking level to
  Antigravity's proto enum value, adds the tool call ids Claude and GPT
  require, and strips the `response` wrapper from each SSE chunk. Nothing else
  about the request changes. The proxy exists because the `google` codec has
  no body hook and Lua cannot listen on a port.

The wire details (host, user agent, envelope fields, model discovery) come
from captures of agy itself. Check a change against agy before guessing.

## Code guidelines

- No trivial comments, minimal bloat, no unnecessary state.
- Constants at the top of each file, in both languages.
- Lua hooks fail the way maki expects: an HTTP failure returns
  `nil, maki.provider.http_error(res)` so maki retries it, anything else
  raises with `error`, which is the message the user reads.
- The proxy answers errors as JSON bodies with the upstream status so maki's
  Gemini parser reports them.
- `plugin.toml` grants exactly what the Lua calls, `net_hosts` lists every
  host it reaches, and `providers` lists the slug. Keep it aligned by hand.

## Testing

Cheapest first:

- `just check` runs `cargo check --tests` and byte-compiles the proxy.
- `just lint`
- `just test-py` runs the proxy tests against a fake upstream on an ephemeral
  port.
- `just test` runs both suites; the Rust part needs `cargo-nextest`.

The Rust tests load the package through `PluginHost::load_package`, passing the
repo root, with the grants `plugin.toml` asks for. The provider registry and
the environment are global, so each test needs a process of its own, which
nextest gives it. The test points `HOME` and the XDG variables at a temporary
directory before creating the host. Assert effects maki sees: the registered
provider and what `auth` resolves from cached credentials. Anything that reads
the keyring or reaches Google is checked by hand with a real agy sign-in.

Dev-dependencies pin a revision of maki. Move the pin when the host changes
what the plugin uses.

## Layout

- `plugin/`: the Lua entry file.
- `proxy/`: the request proxy.
- `plugin.toml`: `min_maki_version`, `providers`, and the `[permissions]`
  request.
- `tests/plugin.rs`: host harness. `tests/test_proxy.py`: proxy tests.
- `justfile`: check, lint, test, test-py, fmt-lua.

## Docs

The README is the canonical home for install and usage. Follow the maki docs
voice: plain words, no em-dashes, no contractions, state facts once.
