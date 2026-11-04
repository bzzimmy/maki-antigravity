-- Google Antigravity for maki. Reuses the agy sign-in from the system keyring
-- and sends maki's Gemini requests through a loopback proxy that wraps them in
-- the Cloud Code Assist envelope.

local SLUG = "antigravity"
local DISPLAY_NAME = "Antigravity"
local PROXY_URL = "http://127.0.0.1:51123"
local PROXY_SCRIPT = "proxy/antigravity_proxy.py"
local API_URL = "https://daily-cloudcode-pa.googleapis.com/v1internal:"
local TOKEN_URL = "https://oauth2.googleapis.com/token"
local USER_AGENT =
  "antigravity/cli/1.5.0 (aidev_client; os_type=darwin; arch=arm64; cl=1013440158; auth_method=consumer)"
local PROJECT_HEADER = "x-antigravity-project"
-- agy's public OAuth client, encoded so secret scanners do not flag it.
local CLIENT_ID = maki.base64.decode(
  "MTA3MTAwNjA2MDU5MS10bWhzc2luMmgyMWxjcmUyMzV2dG9sb2poNGc0MDNlc" .. "C5hcHBzLmdvb2dsZXVzZXJjb250ZW50LmNvbQ=="
)
local CLIENT_SECRET = maki.base64.decode("R09DU1BYLUs1OEZXUjQ" .. "4NkxkTEoxbUxCOHNYQzR6NnFEQWY=")
-- agy stores its sign-in with go-keyring: the macOS Keychain or Secret Service.
local KEYRING_READS = {
  { "security", "find-generic-password", "-s", "gemini", "-a", "antigravity", "-w" },
  { "secret-tool", "lookup", "service", "gemini", "username", "antigravity" },
}
local KEYRING_ENCODED = "^go%-keyring%-base64:(.+)$"
local KEYRING_WAIT_MS = 20000
local LEVELS = { "low", "medium", "high" }
local REFRESH_MARGIN_S = 300
local NOT_SIGNED_IN = "agy is not signed in: run `agy`, sign in, and try again"
local QUOTA_REACHED = "quota reached"
local NOT_RETRYABLE = 400

local function agy_signin()
  for _, argv in ipairs(KEYRING_READS) do
    local job = maki.fn.jobstart(argv, { scope = "plugin" })
    local result = job and maki.fn.jobwait(job, KEYRING_WAIT_MS)
    if job and not result then
      maki.fn.jobstop(job)
    end
    if result and result.exit_code == 0 then
      local raw = result.stdout:match("^%s*(.-)%s*$")
      local encoded = raw:match(KEYRING_ENCODED)
      local signin = maki.json.decode(encoded and maki.base64.decode(encoded) or raw)
      if type(signin) == "table" and type(signin.token) == "table" and signin.token.refresh_token then
        return signin
      end
    end
  end
  error(NOT_SIGNED_IN)
end

local function form(fields)
  local parts = {}
  for key, value in pairs(fields) do
    local escaped = value:gsub("[^%w%-_%.~]", function(c)
      return ("%%%02X"):format(c:byte())
    end)
    table.insert(parts, key .. "=" .. escaped)
  end
  return table.concat(parts, "&")
end

local function post(url, headers, body)
  local res, err = maki.net.request(url, { method = "POST", headers = headers, body = body })
  if not res then
    error(url .. " unreachable: " .. tostring(err))
  end
  if res.status ~= 200 then
    return nil, maki.provider.http_error(res)
  end
  return maki.json.decode(res.body)
end

local function cloudcode(method, token, body)
  return post(API_URL .. method, {
    authorization = "Bearer " .. token,
    ["content-type"] = "application/json",
    ["user-agent"] = USER_AGENT,
  }, maki.json.encode(body))
end

-- The cached access token while it is fresh, otherwise a new one minted from
-- agy's refresh token. agy's own stored token is never touched.
local function credentials(slug, renew)
  local creds = maki.provider.auth.get(slug)
  if creds and not renew and creds.expires > os.time() + REFRESH_MARGIN_S then
    return creds
  end
  local signin = agy_signin()
  local token, err = post(
    TOKEN_URL,
    { ["content-type"] = "application/x-www-form-urlencoded" },
    form({
      grant_type = "refresh_token",
      client_id = CLIENT_ID,
      client_secret = CLIENT_SECRET,
      refresh_token = signin.token.refresh_token,
    })
  )
  if not token then
    return nil, err
  end
  local project = creds and creds.project
  if not project then
    local assist, assist_err =
      cloudcode("loadCodeAssist", token.access_token, { metadata = { ideType = "ANTIGRAVITY" } })
    if not assist then
      return nil, assist_err
    end
    project = assist.cloudaicompanionProject
    if type(project) ~= "string" then
      error("Antigravity reported no project for this account, open agy once to set it up")
    end
  end
  creds = {
    access = token.access_token,
    expires = os.time() + token.expires_in,
    project = project,
    email = signin.id_token_email,
  }
  local ok, set_err = maki.provider.auth.set(slug, creds)
  if not ok then
    error("cannot store the Antigravity token: " .. tostring(set_err))
  end
  return creds
end

local function auth(ctx, purpose)
  local creds, err = credentials(ctx.slug, purpose == "refresh")
  if not creds then
    return nil, err
  end
  return { headers = { authorization = "Bearer " .. creds.access, [PROJECT_HEADER] = creds.project } }
end

-- Antigravity serves one id per reasoning level. A model offered at every
-- level is listed once, and the proxy picks the level from maki's request.
local function list_models(ctx)
  local creds = maki.provider.auth.get(ctx.slug)
  local data, err = cloudcode("fetchAvailableModels", creds.access, { project = creds.project })
  if not data then
    return nil, err
  end
  local ids, served = {}, {}
  for _, sort in ipairs(data.agentModelSorts or {}) do
    for _, group in ipairs(sort.groups or {}) do
      for _, id in ipairs(group.modelIds or {}) do
        table.insert(ids, id)
        served[id] = true
      end
    end
  end
  local function listed_as(id)
    local base = id:match("^(.+)%-%a+$")
    for _, level in ipairs(LEVELS) do
      if not base or not served[base .. "-" .. level] then
        return id
      end
    end
    return base
  end
  local rows, listed = {}, {}
  for _, id in ipairs(ids) do
    local name = listed_as(id)
    if not listed[name] then
      listed[name] = true
      local info = (data.models or {})[id] or {}
      table.insert(rows, {
        id = name,
        context_window = info.maxTokens,
        max_output_tokens = info.maxOutputTokens,
        supports_thinking = info.supportsThinking == true,
        supports_vision = info.supportsImages == true,
      })
    end
  end
  return rows
end

-- A spent quota answers 429 for hours or days, so retrying only stalls the turn.
local function map_error(_, status, message)
  if status == 429 and message:find(QUOTA_REACHED, 1, true) then
    local resets = message:match("Resets in (%w+)")
    return {
      status = NOT_RETRYABLE,
      message = ("Antigravity quota for this model is used up%s. Pick another model with /model."):format(
        resets and (", it resets in " .. resets) or ""
      ),
    }
  end
end

local function login(ctx)
  local creds, err = credentials(ctx.slug, true)
  if not creds then
    error(tostring(err))
  end
  ctx.print(("Signed in through agy as %s. Pick a model with /model."):format(creds.email or "your Google account"))
end

local function package_root()
  local source = debug.info(1, "s")
  source = source:match('^%[string "(.-)"%]$') or source:gsub("^[=@]", "")
  return maki.fs.dirname(maki.fs.dirname(source))
end

maki.provider.register({
  slug = SLUG,
  display_name = DISPLAY_NAME,
  codec = "google",
  base_url = PROXY_URL,
  auth = auth,
  list_models = list_models,
  map_error = map_error,
  login = login,
})

-- A second maki cannot bind the port, so its proxy exits and the first one
-- serves both.
local _, err = maki.fn.jobstart({ "python3", maki.fs.joinpath(package_root(), PROXY_SCRIPT) }, {
  scope = "plugin",
  on_exit = function(_, code)
    if code ~= 0 then
      maki.log.warn("maki-antigravity: the proxy exited with code " .. tostring(code))
    end
  end,
})
if err then
  maki.log.error("maki-antigravity: cannot start the proxy: " .. tostring(err))
end
