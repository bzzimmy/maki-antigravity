<h1><img src="assets/antigravity-logo.svg" alt="Antigravity" width="40" align="absmiddle"> maki-antigravity</h1>

Use Google Antigravity in [maki](https://github.com/tontinton/maki). The
package adds an `antigravity` provider that signs in with your Antigravity CLI
(`agy`) account. Antigravity speaks the Gemini request format inside a Cloud
Code Assist envelope, so a small loopback proxy wraps each request and unwraps
each streamed chunk. maki's own Gemini support handles everything else.

Not sure how many people even use Antigravity because Gemini models currently
suck pretty bad, but if you want, from [G2A](https://www.g2a.com/) you can get a
Google AI Pro subscription for less than $2 for 6+ months and use Gemini models
with decent usage basically for free.

## Requirements

- maki 0.7.0 or newer
- [agy](https://antigravity.google/docs/cli/install), signed in once
- Python 3.8 or newer on `PATH` as `python3`
- macOS, or Linux with `secret-tool` (libsecret)

## Install

Add the package in `~/.config/maki/init.lua`:

```lua
maki.pack.add({
  { src = "https://github.com/bzzimmy/maki-antigravity", version = "main" },
})
```

maki asks once to approve the permissions and the `antigravity` provider name.

## Setup

Run `agy` and sign in, if you have not yet. Then check that maki can use it:

```
maki auth login antigravity
```

The plugin reads the agy sign-in from the system keyring (the macOS Keychain
or Secret Service) and never changes it. macOS may ask once whether `security`
can read the `gemini` item. maki keeps its own short-lived access token in its
state directory and renews it from the agy sign-in when it expires.

Pick a model with `/model`. The catalog comes from your account at runtime,
matching `agy models`, for example `antigravity/gemini-4-neon-xhigh`,
`antigravity/gemini-3.8-flash-high`, or `antigravity/claude-opus-5-5-medium`.

`maki auth logout antigravity` removes maki's token. The agy sign-in stays.

## How requests flow

The plugin starts `proxy/antigravity_proxy.py` as a plugin job, listening on
`127.0.0.1:51123`, and points maki's Gemini requests at it with the bearer
token, user agent, and project id as headers. The proxy sets the `xhigh`
thinking level value when needed, adds the ids that Claude and GPT require on
tool calls, wraps the request in the envelope, and posts it to
`daily-cloudcode-pa.googleapis.com`. The job ends with maki. A second maki on
the same machine cannot bind the port, so its proxy exits and the first one
serves both. If the first maki quits, restart the second.

## Permissions

The package requests exactly what it uses: `net` for the proxy, the Google
token endpoint, and Cloud Code Assist, and `run` to read the agy sign-in from
the keyring and to start the proxy.

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
