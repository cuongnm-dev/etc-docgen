# ref-docs.md — Documentation Templates

## `docs/architecture/adr/ADR-001-tech-stack.md`

```markdown
# ADR-001: Tech Stack Selection
**Date:** {YYYY-MM-DD} | **Status:** Accepted

## Context
New project "{project-name}" — {1 sentence business context}.

## Decision
| Layer | Choice | Alternatives |
|---|---|---|
| Frontend | {choice} | {alt} |
| Backend | {choice} | {alt} |
| Database | {choice} | {alt} |
| Auth | {choice} | {alt} |
| Deployment | {choice} | {alt} |

## Rationale
{2 sentences: why these choices}

## Consequences
- {Positive}
- {Trade-off accepted}
```

---

## `docs/architecture/adr/ADR-002-repo-structure.md`

```markdown
# ADR-002: Repository Structure
**Date:** {YYYY-MM-DD} | **Status:** Accepted

## Decision
**{Mini-repo | Monorepo ({tool})}**

Docs-path formula:
{Copy exact table from .cursor/AGENTS.md Docs-Path Formula section}

## Rationale
{Why this structure for this team size and scope}

## Consequences
- Feature pipeline artifacts: `{docs_path}` per feature
- All agents read docs_path from `_state.md` frontmatter — never derive independently
```

---

## `CLAUDE.md` template

```markdown
# {project-name}
{1-2 sentences: what this project is}

## Stack
{stack summary}

## Quick Start
\`\`\`bash
{install command}
cp .env.example .env   # dev defaults pre-filled — app runs immediately
{dev command}
\`\`\`

## Commands
\`\`\`bash
{dev cmd}        # start dev server
{build cmd}      # production build
{test cmd}       # unit tests
{lint cmd}       # lint + format check
{typecheck cmd}  # type checking (if applicable)
{db:push cmd}    # apply DB schema (if ORM selected)
\`\`\`

## Architecture
- **Repo type:** {mini | mono}
- **Docs path:** {docs_path formula from .cursor/AGENTS.md}
- **Feature prefix:** {PREFIX} — e.g. {PREFIX}-20240401-001
- **ADRs:** `docs/architecture/adr/`
- {Key decision 1}
- {Key decision 2}

## Pipeline
Run `/new-feature` to start a new feature pipeline.
```

---

## `CONTRIBUTING.md` template (team projects only)

```markdown
# Contributing to {project-name}

## Branch Strategy
- `main` — production-ready, protected
- `develop` — integration branch
- Features: `feat/{PREFIX}-YYYYMMDD-NNN-short-desc`
- Hotfixes: `hotfix/{PREFIX}-YYYYMMDD-NNN-short-desc`

## Commits (Conventional Commits)
`feat:` | `fix:` | `refactor:` | `docs:` | `test:` | `chore:`

## PR Process
1. Branch from `develop`, fill PR template, get 1 approval, CI must pass

## Starting a Feature
Run `/new-feature` in Cursor — the pipeline handles requirements through delivery.
```
