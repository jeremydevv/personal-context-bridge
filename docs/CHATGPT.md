# Connect your private installation to ChatGPT

Local stdio clients can use the generated `mcp.json` directly. For ChatGPT web,
use your own [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
It provides outbound connectivity to a private stdio server. Each user needs their
own tunnel and runtime API key, with permission to use the tunnel and to add a
custom MCP server in their ChatGPT workspace.

Install `tunnel-client` from the official guide. Export `PERSONAL_CONTEXT_DB` and
`PERSONAL_CONTEXT_KEY_FILE` as described in SETUP.md. Supply `CONTROL_PLANE_API_KEY`
through your credential manager/private runtime environment; do not place it in
this repository. Set `CONTEXT_TUNNEL_ID` to your own tunnel identifier.

```sh
tunnel-client init \
  --sample sample_mcp_stdio_local \
  --profile personal-context \
  --tunnel-id "$CONTEXT_TUNNEL_ID" \
  --mcp-command "/absolute/project/.venv/bin/python -m personal_context.mcp_server"
tunnel-client doctor --profile personal-context --explain
tunnel-client run --profile personal-context
```

Keep the client running. In ChatGPT Plugins, add a custom MCP server, choose the
Tunnel connection, select your tunnel, and review the authentication/access
settings. Workspace restrictions may affect availability. Test with fictional
records first.

This repository distributes software. The tunnel connects each user's private
installation; it is not a public ChatGPT plugin listing. Health, travel, and
Obsidian can use separate profiles pointing to their documented module commands.
