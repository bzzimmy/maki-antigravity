-- Antigravity for maki. The provider itself is `providers/antigravity` in
-- this package, a maki dynamic provider script. This file installs it into
-- the config directory, keeps its request proxy running as a plugin job, and
-- adds /antigravity for a status line.

local SCRIPT_NAME = "antigravity"
local PROVIDERS_DIR = "providers"
local SCRIPT_MODE = "755"
local JOB_WAIT_MS = 20000
local PROXY_JOB = "antigravity-proxy"
local TITLE = "antigravity"
local LOGIN_HINT = "run `maki auth login antigravity` in a terminal, then restart maki"

local function notify(msg, level)
  maki.notify(msg, level or "info", { title = TITLE })
end

local function package_root()
  local src = debug.info(1, "s") or ""
  src = src:match('^%[string "(.-)"%]$') or src:gsub("^[=@]", "")
  return maki.fs.dirname(maki.fs.dirname(src))
end

local function script_install_path()
  local dir = maki.env.config_dir()
  if not dir then
    return nil, "cannot locate the maki config directory"
  end
  return maki.fs.joinpath(dir, PROVIDERS_DIR, SCRIPT_NAME)
end

-- Plugin scope: at load there is no task for a job to belong to.
local function run(argv)
  local job = maki.fn.jobstart(argv, { scope = "plugin" })
  local result = maki.fn.jobwait(job, JOB_WAIT_MS)
  if not result then
    maki.fn.jobstop(job)
    return nil, "timed out: " .. table.concat(argv, " ")
  end
  if result.exit_code ~= 0 then
    local err = result.stderr:match("^%s*(.-)%s*$")
    return nil, err ~= "" and err or ("exit code " .. tostring(result.exit_code))
  end
  return result.stdout
end

-- Copies the script from the package into the config providers directory when
-- the two differ. Returns the installed path and whether it changed.
local function install_script()
  local dst, err = script_install_path()
  if not dst then
    return nil, err
  end
  local source = maki.fs.joinpath(package_root(), PROVIDERS_DIR, SCRIPT_NAME)
  local content, read_err = maki.fs.read(source)
  if not content then
    return nil, "cannot read " .. source .. ": " .. tostring(read_err)
  end
  if maki.fs.read(dst) == content then
    return dst, nil, false
  end
  local ok, mk_err = maki.fs.mkdir(maki.fs.dirname(dst), { parents = true })
  if not ok then
    return nil, mk_err
  end
  local written, write_err = maki.fs.atomic_write(dst, content)
  if not written then
    return nil, write_err
  end
  local _, chmod_err = run({ "chmod", SCRIPT_MODE, dst })
  if chmod_err then
    return nil, "chmod failed: " .. chmod_err
  end
  return dst, nil, true
end

-- The proxy lives as long as the plugin. A second maki cannot bind the port,
-- so its job exits at once and the first maki's proxy serves both.
local function start_proxy(script)
  maki.fn.jobstart({ script, "serve" }, {
    scope = "plugin",
    name = PROXY_JOB,
    on_exit = function(_, code)
      if code ~= 0 then
        maki.log.warn("maki-antigravity: proxy exited with code " .. tostring(code))
      end
    end,
  })
end

local function status_line(s)
  if not s.logged_in then
    return "not logged in, " .. LOGIN_HINT
  end
  local who = s.email and (" as " .. s.email) or ""
  local proxy = maki.fn.jobfind(PROXY_JOB) and "proxy running" or "proxy not running"
  if s.expires_in_s <= 0 then
    return ("logged in%s, token expired, it refreshes on the next request, %s"):format(who, proxy)
  end
  return ("logged in%s, token valid for %d min, %s"):format(who, math.floor(s.expires_in_s / 60), proxy)
end

local function status()
  maki.async.run(function()
    local script, err = script_install_path()
    if not script then
      notify(err, "error")
      return
    end
    local out, run_err = run({ script, "status" })
    if not out then
      notify(run_err, "error")
      return
    end
    local s = maki.json.decode(out)
    if type(s) ~= "table" then
      notify("unexpected output from `antigravity status`: " .. out, "error")
      return
    end
    notify(status_line(s), s.logged_in and "info" or "warn")
  end)
end

maki.api.register_command({
  name = "antigravity",
  description = "Antigravity: login state, token expiry, and proxy status",
  handler = status,
})

local path, err, changed = install_script()
if not path then
  maki.log.error("maki-antigravity: " .. err)
  notify(err, "error")
  return
end
if changed then
  maki.log.info("maki-antigravity: installed provider script at " .. path)
  notify("provider script installed at " .. path .. ", restart maki, then " .. LOGIN_HINT)
end
start_proxy(path)
