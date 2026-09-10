use std::path::Path;
use std::sync::Arc;

use maki_agent::ToolOutput;
use maki_agent::tools::ToolRegistry;
use maki_lua::{PluginHost, PluginPermissions};
use serde_json::json;

const PLUGIN_NAME: &str = "maki-antigravity";
const PING_TOOL: &str = "maki_antigravity_ping";

fn plugin_host() -> (Arc<ToolRegistry>, PluginHost) {
    let reg = Arc::new(ToolRegistry::new());
    let host = PluginHost::new(Arc::clone(&reg)).unwrap();
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    host.load_package(
        PLUGIN_NAME,
        root,
        PluginPermissions::trusted(),
        Default::default(),
    )
    .unwrap();
    (reg, host)
}

fn exec_tool(reg: &ToolRegistry, name: &str, input: serde_json::Value) -> Result<String, String> {
    let entry = reg
        .get(name)
        .unwrap_or_else(|| panic!("tool {name} not registered"));
    let inv = entry.tool.parse(&input).expect("parse failed");
    let ctx = maki_agent::tools::test_support::stub_ctx(&maki_agent::AgentMode::Build);
    smol::block_on(async { inv.execute(&ctx).await })
        .output
        .map_or_else(Err, |out| match out {
            ToolOutput::Plain(s) => Ok(s.text),
            other => panic!("unexpected output: {other:?}"),
        })
}

#[test]
fn tools_register() {
    let (reg, _host) = plugin_host();
    assert!(reg.has(PING_TOOL), "the example tool should register");
}

#[test]
fn ping_answers_and_rejects_blank_messages() {
    let (reg, _host) = plugin_host();
    let pong = exec_tool(&reg, PING_TOOL, json!({ "message": "hello" })).unwrap();
    assert_eq!(pong, "pong: hello");

    let err = exec_tool(&reg, PING_TOOL, json!({ "message": "  " })).unwrap_err();
    assert!(err.contains("message is required"), "got: {err}");
}
