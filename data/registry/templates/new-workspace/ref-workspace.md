# ref-workspace.md — .cursor/ Workspace Templates

## `.cursor/AGENTS.md` template

```markdown
# Project: {project-name}

## Overview
{1-2 sentences: what this project is and what problem it solves}

## Repo Config
| Field | Value |
|---|---|
| repo-type | mini \| mono |
| feature-prefix | {ABBR} |
| output-mode | lean |
| default-path | S |
| package-manager | {pm} |
| input-watch-dir | docs/input |

## Tech Stack
| Layer | Technology |
|---|---|
| Frontend | {framework or N/A} |
| Backend | {framework or N/A} |
| Database | {db + ORM or N/A} |
| Auth | {provider or N/A} |
| Cache | {Redis or N/A} |
| Deployment | {target} |
| CI/CD | {tool} |

## Docs-Path Formula
<!-- PM reads this at EVERY pipeline intake — single source of truth -->
| Scenario | docs_path |
|---|---|
| mini-repo | `docs/features/{feature-id}` |
| mono — cross-cutting | `docs/features/{feature-id}` |
| mono — app: {app-name} | `src/apps/{app-name}/docs/features/{feature-id}` |
| mono — service: {svc-name} | `src/services/{svc-name}/docs/features/{feature-id}` |

## Active Apps / Services (monorepo only)
| Name | Stack | Type | Path |
|---|---|---|---|
| {name} | {stack} | app/service/lib | {path} |

## Key Decisions
- {Decision made at inception — e.g. "Auth via Supabase, not custom JWT"}

## PM Integration Notes
- Read this file at every pipeline intake (Stage 1)
- Resolve docs_path from Docs-Path Formula table above
- For mono: ask user which app/service if not clear from request
- Write resolved docs_path into _state.md frontmatter before any delegation
- When invoked with no arguments: scan `input-watch-dir` for unprocessed files → auto-trigger doc-intel pipeline
```

---

## `.cursor/rules/40-project-knowledge.mdc` template

```markdown
---
description: Project knowledge for {project-name}. PM reads once per pipeline, injects per agent. Not alwaysApply.
globs: []
alwaysApply: false
---
# Project Knowledge: {project-name}

## Domain Conventions
<!-- ba, domain-analyst, sa | [FEAT-ID] Convention -->
_No entries yet._

## Architectural Decisions (Standing)
<!-- sa, tech-lead, dev | [FEAT-ID] Decision — Rationale -->
_No entries yet._

## Coding Conventions & Anti-Patterns
<!-- dev, reviewer | [FEAT-ID] Pattern — Where it applies -->
_No entries yet._

## Known Failure Modes
<!-- qa, reviewer, security | [FEAT-ID] Failure — How to detect -->
_No entries yet._

## DevOps / Deployment Patterns
<!-- devops, release-manager | [FEAT-ID] Pattern — Why it matters -->
_No entries yet._

## Knowledge Injection Guide for PM
| Agent | Sections |
|---|---|
| ba, domain-analyst | Domain Conventions |
| sa | Domain Conventions, Architectural Decisions |
| tech-lead, dev | Architectural Decisions, Coding Conventions |
| qa, reviewer | Coding Conventions, Known Failure Modes |
| security | Known Failure Modes |
| devops, release-manager | DevOps / Deployment Patterns |
Cap ≤5 items per agent. Skip if empty.
```
