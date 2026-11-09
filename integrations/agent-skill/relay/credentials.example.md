# Relay MCP connection

Copy this file, fill in the placeholders and keep the copy private. Never commit real keys.

| Setting | Value |
|---|---|
| Site URL | `https://<your-relay-site>` |
| MCP endpoint | `https://<your-relay-site>/api/method/relay_core.mcp.endpoint` |
| Protocol | JSON-RPC 2.0 over HTTP POST (MCP Streamable HTTP) |
| Auth header | `Authorization: token <api_key>:<api_secret>` |

The endpoint refuses browser requests and cookie logins. Use the token header only.

## 1. Make the API key (Relay admin)

1. In Frappe, open **User** and create a user for the AI, for example `ai-agent@<your-domain>`.
2. Give the user the roles **Relay Communication User** and **Relay AI Agent**.
3. In Relay, open **Settings > Business types and users** and add the user to each business type whose chats the AI may answer.
4. On the same User form, open **Settings > API Access** and click **Generate Keys**.
5. Copy the API secret now. Frappe shows it only once. The API key stays on the form.

## 2. Add Relay as an MCP server

### Claude Code

```bash
claude mcp add --transport http relay https://<your-relay-site>/api/method/relay_core.mcp.endpoint \
  --header "Authorization: token <api_key>:<api_secret>"
```

### Claude Desktop

Add this to `claude_desktop_config.json` (Settings > Developer > Edit Config). It uses the `mcp-remote` bridge, which needs Node.js:

```json
{
  "mcpServers": {
    "relay": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote",
        "https://<your-relay-site>/api/method/relay_core.mcp.endpoint",
        "--header", "Authorization:${RELAY_AUTH}"
      ],
      "env": { "RELAY_AUTH": "token <api_key>:<api_secret>" }
    }
  }
}
```

### Codex

Add this to `~/.codex/config.toml`, and set `RELAY_AUTH` in the shell that starts Codex:

```toml
[mcp_servers.relay]
url = "https://<your-relay-site>/api/method/relay_core.mcp.endpoint"
env_http_headers = { "Authorization" = "RELAY_AUTH" }
```

```bash
export RELAY_AUTH="token <api_key>:<api_secret>"
```

### Any other MCP client

Use an HTTP MCP server with the endpoint above and the `Authorization` header.

## 3. Check the connection

```bash
curl -s https://<your-relay-site>/api/method/relay_core.mcp.endpoint \
  -H "Authorization: token <api_key>:<api_secret>" \
  -H "Content-Type: application/json" \
  -d '{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "persona_read", "arguments": {}}}'
```

A JSON result means the key works. A 401 means the key or secret is wrong. A 403 means the user has no Relay role.

## 4. Load the skill

Put the `relay` folder (with `SKILL.md`) in your agent's skills folder, for example `~/.claude/skills/relay/` for Claude Code.
