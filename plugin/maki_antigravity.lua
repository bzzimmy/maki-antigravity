maki.api.register_tool({
  name = "maki_antigravity_ping",
  kind = "execute",
  description = "Reply with pong. Use it to check the plugin is alive.",
  schema = {
    type = "object",
    properties = {
      message = {
        type = "string",
        description = "Text to echo back",
        required = true,
      },
    },
  },
  handler = function(input)
    if not input.message or input.message:match("^%s*$") then
      return { llm_output = "error: message is required", is_error = true }
    end
    return "pong: " .. input.message
  end,
})

-- A tool that exposes a guarded capability needs two more keys, and the
-- capability must be granted in plugin.toml:
--
--   permission = "run",
--   permission_scopes = function(input)
--     return { scopes = { input.command }, force_prompt = true }
--   end,
