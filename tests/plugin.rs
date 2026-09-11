use std::path::{Path, PathBuf};
use std::sync::{Arc, OnceLock};

use maki_agent::tools::ToolRegistry;
use maki_lua::{PluginHost, PluginPermissions};

const PLUGIN_NAME: &str = "maki-antigravity";
const COMMAND: &str = "/antigravity";
const SCRIPT_REL: &str = "providers/antigravity";
const INSTALLED_REL: &str = "maki/providers/antigravity";

/// The plugin writes into the maki config directory at load, so every test
/// process points HOME and the XDG bases at a directory of its own first.
fn isolated_home() -> &'static PathBuf {
    static HOME: OnceLock<PathBuf> = OnceLock::new();
    HOME.get_or_init(|| {
        let dir =
            std::env::temp_dir().join(format!("maki-antigravity-test-{}", std::process::id()));
        std::fs::create_dir_all(&dir).unwrap();
        for var in [
            "HOME",
            "XDG_CONFIG_HOME",
            "XDG_DATA_HOME",
            "XDG_STATE_HOME",
            "XDG_CACHE_HOME",
        ] {
            // Set once, before any thread resolves paths.
            unsafe { std::env::set_var(var, &dir) };
        }
        dir
    })
}

fn plugin_host() -> (Arc<ToolRegistry>, PluginHost) {
    isolated_home();
    let reg = Arc::new(ToolRegistry::new());
    let host = PluginHost::new(Arc::clone(&reg)).unwrap();
    let root = Path::new(env!("CARGO_MANIFEST_DIR"));
    host.load_package(
        PLUGIN_NAME,
        root,
        PluginPermissions::from_approved(["fs_read", "fs_write", "run"]),
        Default::default(),
    )
    .unwrap();
    (reg, host)
}

#[test]
fn command_registers() {
    let (_reg, host) = plugin_host();
    let snap = host.command_reader().load();
    assert!(
        snap.commands.iter().any(|c| c.name.as_ref() == COMMAND),
        "the /antigravity command should register"
    );
}

#[test]
fn load_installs_the_provider_script() {
    let (_reg, _host) = plugin_host();
    let installed = isolated_home().join(INSTALLED_REL);
    let expected = std::fs::read(Path::new(env!("CARGO_MANIFEST_DIR")).join(SCRIPT_REL)).unwrap();
    assert_eq!(
        std::fs::read(&installed).unwrap(),
        expected,
        "the installed script should match the package copy"
    );
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mode = std::fs::metadata(&installed).unwrap().permissions().mode();
        assert_eq!(
            mode & 0o111,
            0o111,
            "the installed script should be executable"
        );
    }
}
