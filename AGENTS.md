maki lua plugins extend maki with tools, commands, keybindings, and event handlers. This template loads through the maki pack system, not as a builtin.

## Code guidelines

- Lua in `plugin/`. No trivial comments, minimal bloat, no unnecessary state.
- Keep the `MAX_*` constants at the top of the file.
- Fallible runtime operations return the `(value, err)` pair and never throw. Tool handlers fail with `{ llm_output = msg, is_error = true }`; a plain string is always success.
- Every tool that declares `permission_scopes` must also declare `permission`, and the capability must be granted in `plugin.toml`. maki refuses the load otherwise.
- `plugin.toml` grants exactly what the code calls. maki walks bundled plugins' lua and requires to keep manifests honest; keep ours aligned by hand.

## Testing

This repository is a cargo-generate template. The Rust checks run inside a project generated from it, not at the root:

```
cargo generate --path . --name ci-check
cd ci-check && just check && just lint && just test
```

CI does the same in `.github/workflows/template.yml`. Cheapest first:

- `just check`
- `just lint`
- `just test`

Tests live in `tests/` and load the plugin through the real `maki-lua` host with `PluginHost::load_package`, passing the repo root (it derives `plugin/` itself; passing `plugin/` fails with `PackageEmpty`).

Dev-dependencies pin a revision of maki. Move the pin when the host changes what the plugin uses.

Assert Lua-visible effects (callback output, mailbox messages), not just files. `smol::unblock` side effects land even when a callback aborts, so file-only checks can pass while the Lua-level API is broken.

## Layout

- `plugin/` — the plugin entry files, loaded sorted by file name; chunks share one environment.
- `plugin.toml` — `min_maki_version` and the `[permissions]` request.
- `tests/` — host harness and integration tests.
- `justfile` — check, lint, test, fmt-lua.

## Docs

The README is the canonical home for install and usage. Follow the maki docs voice: plain words, no em-dashes, no contractions, state facts once.
