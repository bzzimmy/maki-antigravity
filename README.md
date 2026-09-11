<h1><img src="assets/antigravity-logo.svg" alt="Antigravity" width="40" align="absmiddle"> maki-antigravity</h1>

Use Google Antigravity in [maki](https://github.com/tontinton/maki). The
package adds an `antigravity` provider that logs in with the same Google OAuth
flow as the Antigravity CLI. Antigravity speaks the Gemini request format inside
a Cloud Code Assist envelope, so the provider runs a loopback proxy that wraps
each request and unwraps each streamed chunk; maki's own Gemini support handles
everything else, including token refresh.

## Requirements

- maki 0.5.3 or newer
- Python 3.8 or newer on `PATH` as `python3`
- A Google account with access to Antigravity
- Linux or macOS

## Install

Add the package in `~/.config/maki/init.lua`:

```lua
maki.pack.add({
  { src = "https://github.com/bzzimmy/maki-antigravity", version = "main" },
})
```

Start maki once so the plugin installs the provider script to
`~/.config/maki/providers/antigravity`, then restart after login so maki
discovers it.

## Setup

```
maki auth login antigravity
```

Login opens the browser. If the browser is on another machine, paste the
final redirect URL into the terminal. Tokens and the Antigravity project id
are stored in the maki state directory with mode 0600 and refresh on their
own.

Pick a model with `/model`; the catalog is under the `antigravity/` prefix and
uses the runtime ids Antigravity advertises, with the thinking level in the
name, for example `antigravity/gemini-3.8-flash-high`. Gemini models only.

- `/antigravity` shows the login state, token expiry, and whether the proxy
  is running.
- `maki auth logout antigravity` removes the stored tokens.

## How requests flow

The plugin starts `providers/antigravity serve` as a plugin job, listening on
`127.0.0.1:51123`. The provider script tells maki to use that address as the
Gemini base URL and sends the bearer token as a header. The proxy forwards
the token, adds the project id, and posts the envelope to
`daily-cloudcode-pa.googleapis.com`. When that host answers 404 or 429 the
proxy retries the same request on the sandbox host and then on
`cloudcode-pa.googleapis.com`. The job ends with maki. A second maki on the
same machine cannot bind the port, so its job exits and the first proxy serves
both; if the first maki quits, restart the second.

## Permissions

The package requests exactly what it calls: `fs_read` and `fs_write` to
install the script, `run` to mark it executable, keep the proxy alive, and
call it for `/antigravity`. The proxy is the only thing that talks to Google
for model requests; login and refresh go from the script to Google directly.

## Development

Clone the repository and run the checks from its root. The Rust tests load
the package through the real maki Lua host and need `cargo-nextest`.

```sh
git clone https://github.com/bzzimmy/maki-antigravity.git
cd maki-antigravity
just check && just lint && just test
```

This project is not affiliated with or endorsed by Google. Use it only with
an account and services you are authorized to access.
