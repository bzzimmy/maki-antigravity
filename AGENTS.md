maki-antigravity puts Google Antigravity behind maki's dynamic provider
mechanism. It loads through the maki pack system, not as a builtin. Two parts:

- `providers/antigravity`: a Python 3 script, the maki dynamic provider.
  Google OAuth login, token storage, refresh, the model list, and the request
  proxy. Standard library only, one file, no `.py` extension because maki runs
  it by name. `info` declares `google` as the base protocol, `models` lists
  the Gemini runtime ids, and `resolve` points maki at the loopback proxy
  with the bearer header. The proxy (`serve`) wraps maki's Gemini request in
  the Cloud Code Assist envelope, adds the project id, forwards the bearer,
  and strips the `response` wrapper from each SSE chunk. Nothing else about
  the request changes.
- `plugin/maki_antigravity.lua`: installs the script into the config
  `providers/` directory, starts the proxy as a plugin-scoped job, and
  registers `/antigravity` for a status line. Keep it to that: anything else
  the script can do is reachable through `maki auth`.

## Code guidelines

- No trivial comments, minimal bloat, no unnecessary state.
- Constants at the top of each file, in both languages.
- Lua: fallible runtime operations return the `(value, err)` pair and never
  throw. Setup at load logs and returns on the first failure instead of
  failing the package.
- Python: user-facing failures raise `Fail`; `main` prints them to stderr and
  exits non-zero, which is how maki surfaces script errors. The proxy answers
  errors as JSON bodies with the upstream status so maki's Gemini parser
  reports them.
- `plugin.toml` grants exactly what the Lua calls. Keep it aligned by hand.

## Testing

Cheapest first:

- `just check` runs `cargo check --tests` and byte-compiles the script.
- `just lint`
- `just test-py` runs the Python tests, including the proxy against a fake
  upstream on an ephemeral port.
- `just test` runs both suites; the Rust part needs `cargo-nextest`.

The Rust tests load the package through `PluginHost::load_package`, passing the
repo root. Loading installs the script and starts the proxy job, so the test
points `HOME` and the XDG variables at a temporary directory before creating
the host; the job dies with the host. Assert Lua-visible effects: the
registered command and the installed file.

Dev-dependencies pin a revision of maki. Move the pin when the host changes
what the plugin uses.

## Layout

- `providers/antigravity`: the provider script.
- `plugin/`: the Lua entry file.
- `plugin.toml`: `min_maki_version` and the `[permissions]` request.
- `tests/plugin.rs`: host harness. `tests/test_provider.py`: script tests.
- `justfile`: check, lint, test, test-py, fmt-lua.

## Docs

The README is the canonical home for install and usage. Follow the maki docs
voice: plain words, no em-dashes, no contractions, state facts once.
