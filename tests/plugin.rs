use std::path::Path;
use std::sync::Arc;

use maki_agent::tools::ToolRegistry;
use maki_lua::test_support::runtime;
use maki_lua::{PluginHost, PluginPermissions};
use maki_providers::{Timeouts, plugin};
use maki_storage::StateDir;
use maki_storage::auth::save_plugin_auth;
use serde_json::json;

const PLUGIN_NAME: &str = "maki-antigravity";
const SLUG: &str = "antigravity";
const DISPLAY_NAME: &str = "Antigravity";
const NET_HOSTS: [&str; 3] = [
    "127.0.0.1",
    "oauth2.googleapis.com",
    "daily-cloudcode-pa.googleapis.com",
];
const ACCESS: &str = "access-token";
const PROJECT: &str = "project-1";
const PROJECT_HEADER: &str = "x-antigravity-project";
const FAR_FUTURE_S: u64 = 4102444800;

/// The provider registry and the environment are global, so every test leans
/// on nextest running it in a process of its own.
fn plugin_host() -> PluginHost {
    let dir = std::env::temp_dir().join(format!("maki-antigravity-test-{}", std::process::id()));
    std::fs::create_dir_all(&dir).unwrap();
    for var in [
        "HOME",
        "XDG_CONFIG_HOME",
        "XDG_DATA_HOME",
        "XDG_STATE_HOME",
        "XDG_CACHE_HOME",
    ] {
        unsafe { std::env::set_var(var, &dir) };
    }
    let host = PluginHost::new(Arc::new(ToolRegistry::new())).unwrap();
    let mut permissions = PluginPermissions::from_approved(["net", "run"]);
    permissions.set_net_hosts(Some(NET_HOSTS.map(String::from).into()));
    host.load_package(
        PLUGIN_NAME,
        Path::new(env!("CARGO_MANIFEST_DIR")),
        permissions,
        Default::default(),
    )
    .unwrap();
    plugin::commit_load();
    host
}

#[test]
fn registers_a_login_provider() {
    let _host = plugin_host();
    assert!(plugin::auth_providers().contains(&(SLUG.to_owned(), DISPLAY_NAME.to_owned())));
}

#[test]
fn a_cached_token_becomes_the_bearer_and_project_headers() {
    let _host = plugin_host();
    let creds = json!({ "access": ACCESS, "expires": FAR_FUTURE_S, "project": PROJECT });
    save_plugin_auth(
        &StateDir::resolve().unwrap(),
        SLUG,
        creds.as_object().unwrap(),
    )
    .unwrap();

    let provider = plugin::create(SLUG, Timeouts::default()).unwrap();
    runtime().block_on(provider.reload_auth()).unwrap();

    let headers = plugin::resolved_auth(SLUG).unwrap().headers;
    let header = |name: &str| {
        headers
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case(name))
            .map(|(_, v)| v.as_str())
    };
    assert_eq!(
        header("authorization"),
        Some(format!("Bearer {ACCESS}").as_str())
    );
    assert_eq!(header(PROJECT_HEADER), Some(PROJECT));
}
