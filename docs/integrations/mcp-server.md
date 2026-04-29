# MCP Server Integration

etc-platform exposes its documentation tools via the **Model Context Protocol (MCP)**, allowing any MCP-compatible AI agent (VS Code Copilot, Cursor, Claude Desktop, Windsurf, etc.) to call tools directly without subprocess CLI parsing.

## Tools

| Tool            | Description                                        |
| --------------- | -------------------------------------------------- |
| `validate`      | Validate content-data.json against Pydantic schema |
| `export`        | Render Office files (HDSD, TKKT, TKCS, Test Cases) |
| `schema`        | Get full JSON Schema for content-data.json         |
| `template_list` | List bundled ETC templates with sizes              |
| `template_fork` | Fork an ETC template by adding Jinja2 tags         |

## Resources

| URI                     | Description                       |
| ----------------------- | --------------------------------- |
| `schema://content-data` | JSON Schema for content-data.json |

## Setup

### 1. Install etc-platform

```bash
pip install etc-platform
# or from source
pip install -e /path/to/etc-platform
```

### 2. Configure your IDE

Choose the config for your IDE below and add it to the appropriate settings file.

---

### VS Code (GitHub Copilot)

Add to `.vscode/mcp.json` in your project (or User settings):

```json
{
  "servers": {
    "etc-platform": {
      "command": "etc-platform-mcp",
      "type": "stdio"
    }
  }
}
```

Or if `etc-platform-mcp` is not on PATH:

```json
{
  "servers": {
    "etc-platform": {
      "command": "python",
      "args": ["-m", "etc_platform.mcp_server"],
      "type": "stdio"
    }
  }
}
```

---

### Cursor

Add to `.cursor/mcp.json` in your project root:

```json
{
  "mcpServers": {
    "etc-platform": {
      "command": "etc-platform-mcp",
      "type": "stdio"
    }
  }
}
```

Or with explicit Python path:

```json
{
  "mcpServers": {
    "etc-platform": {
      "command": "python",
      "args": ["-m", "etc_platform.mcp_server"],
      "type": "stdio"
    }
  }
}
```

---

### Claude Desktop

Add to `claude_desktop_config.json`:

- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "etc-platform": {
      "command": "etc-platform-mcp",
      "type": "stdio"
    }
  }
}
```

---

### Claude Code

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "etc-platform": {
      "command": "etc-platform-mcp",
      "type": "stdio"
    }
  }
}
```

Or via Claude Code CLI:

```bash
claude mcp add etc-platform etc-platform-mcp
```

---

### Windsurf

Add to `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "etc-platform": {
      "command": "etc-platform-mcp",
      "type": "stdio"
    }
  }
}
```

---

## Example: Agent workflow

Once configured, an AI agent can:

```
1. Call `schema` → understand content-data.json format
2. Research codebase → produce content-data.json
3. Call `validate` → ensure data is correct
4. Call `export(targets=["hdsd"])` → generate HDSD docx
```

The agent never needs to parse CLI text output — all tool responses are structured JSON.

## CLI alternative

You can also start the MCP server manually:

```bash
# Via CLI command
etc-platform mcp

# Via Python module
python -m etc_platform.mcp_server
```
