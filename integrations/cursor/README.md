# Cursor 3 integration

Thin skill wrapper that orchestrates `etc-platform` CLI from within Cursor agent chat.

## Installation

1. Install `etc-platform`:
   ```bash
   pip install etc-platform
   # or editable from source
   pip install -e /path/to/etc-platform
   ```

2. Copy skill to Cursor:
   ```bash
   cp -r integrations/cursor/skill ~/.cursor/skills/generate-docs
   ```

3. Restart Cursor.

## Usage

In Cursor chat:
```
/generate-docs
```

Skill guides you through:
1. Create/edit `etc-platform.yaml` (@-mention to help fill fields)
2. Set credentials in environment
3. Run `etc-platform generate`
4. Review output + [CẦN BỔ SUNG] markers

## Cursor 3 optimizations

| Phase | Cursor native leverage |
|---|---|
| Research | `@Codebase` semantic search → pass hints to `etc-platform research` |
| Capture | Playwright MCP directly OR `etc-platform capture` (v0.2+) |
| Data review | Composer diff for `content-data.json` before save |
| Export | Integrated terminal + multi-terminal parallel |

## How it differs from Claude Code

- **Single-agent sequential** — no `Agent()` dispatch
- **@-mentions** to direct agent focus
- **Design Mode** (Cmd+Shift+D) replaces vision screenshot reviewer
- **MEMORIES.md** caches project config across sessions
