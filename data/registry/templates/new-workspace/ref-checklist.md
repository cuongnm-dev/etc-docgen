# ref-checklist.md — Scaffold Checklist & Verification

## § Verification Commands (by stack)

| Stack | Lint | Typecheck | Test | Build | Health check |
|---|---|---|---|---|---|
| Next.js | `pnpm lint` | `pnpm typecheck` | `pnpm test` | `pnpm build` | `curl localhost:3000/api/health` |
| NestJS | `pnpm lint` | `pnpm typecheck` | `pnpm test` | `pnpm build` | `curl localhost:3000/health` |
| Node API | `pnpm lint` | `pnpm typecheck` | `pnpm test` | `pnpm build` | `curl localhost:3000/health` |
| FastAPI | `uv run ruff check .` | `uv run mypy app/` | `uv run pytest` | `docker compose build` | `curl localhost:8000/health` |
| Go | `golangci-lint run` | `go vet ./...` | `go test ./...` | `go build ./cmd/...` | `curl localhost:8080/health` |
| Rust | `cargo clippy` | (included) | `cargo test` | `cargo build --release` | `curl localhost:8080/health` |
| React SPA | `pnpm lint` | `pnpm typecheck` | `pnpm test` | `pnpm build` | n/a |
| Vue/Nuxt | `pnpm lint` | `pnpm typecheck` | `pnpm test` | `pnpm build` | n/a |
| React Native | `pnpm lint` | `pnpm typecheck` | `pnpm test` | n/a | n/a |
| Flutter | `flutter analyze` | (included) | `flutter test` | `flutter build` | n/a |

**Run order:** lint → typecheck → test → build → health check (if API)
Stop on first failure. Report exact error + file:line. Do not mark complete until all pass.

---

## § Scaffold Commands (by stack)

| Stack | Init command |
|---|---|
| React SPA | `pnpm create vite {name} --template react-ts` |
| Next.js | `pnpm create next-app {name} --typescript --tailwind --eslint --app --import-alias "@/*"` |
| Vue | `pnpm create vue@latest` |
| Nuxt | `pnpm dlx nuxi@latest init {name}` |
| NestJS | `pnpm dlx @nestjs/cli new {name} --package-manager pnpm --strict` |
| FastAPI | `uv init {name} && cd {name} && uv add fastapi uvicorn pydantic-settings sqlalchemy alembic && uv add --dev pytest httpx ruff mypy` |
| Go | `mkdir {name} && cd {name} && go mod init github.com/{org}/{name}` |
| Rust | `cargo new {name}` |
| React Native | `pnpm dlx react-native@latest init {Name}` |
| Flutter | `flutter create {name}` |
| Mono — NX | `npx create-nx-workspace@latest {name}` |
| Mono — Turborepo | `npx create-turbo@latest` |
| Mono — pnpm | `mkdir {name} && pnpm init` then create `pnpm-workspace.yaml` |

---

## § Scaffold Checklist

### Pre-flight ✓
```
□ Folder empty or user confirmed
□ All required tools present (no missing prerequisites)
□ Package manager detected — not assumed
□ Git user identity configured
□ No parent monorepo conflict unresolved
```

### Core files ✓
```
□ git init
□ .gitignore (stack-appropriate)
□ .editorconfig
□ .gitleaks.toml
□ Real starter files created (not empty folders)
□ .env.example (all vars documented with comments)
□ .env (dev defaults pre-filled — app runs without edits)
□ README.md (actual commands filled in, not placeholders)
□ CLAUDE.md (commands verified)
```

### Cursor workspace ✓
```
□ .cursor/AGENTS.md
  □ repo-type set
  □ docs-path-formula table complete and correct
  □ feature-prefix set
  □ stack table filled
  □ PM Integration Notes present
□ .cursor/rules/project-conventions.mdc (stack-appropriate)
□ .cursor/rules/40-project-knowledge.mdc (empty, ready)
```

### Docs ✓
```
□ docs/architecture/adr/ADR-001-tech-stack.md (filled from Phase 4)
□ docs/architecture/adr/ADR-002-repo-structure.md (docs-path matches AGENTS.md)
□ docs/features/ (.gitkeep)
```

### Conditional ✓
```
□ [ORM] Starter schema with User model created
□ [Prisma+SQLite] prisma db push succeeded
□ [Auth] Auth files generated and wired into main entry
□ [Docker] Dockerfile (multi-stage), docker-compose.yml, .dockerignore
□ [Docker] docker compose up -d succeeds
□ [CI=GitHub] .github/workflows/ci.yml
□ [CI=GitLab] .gitlab-ci.yml
□ [Team] .github/PULL_REQUEST_TEMPLATE.md
□ [Team] CONTRIBUTING.md
□ [Team] husky + lint-staged configured
□ [Observability] GET /health returns { status: "ok" }
□ [Observability] Structured logger in main entry (not console.log)
```

### Verification ✓ (all must pass)
```
□ lint → 0 errors
□ typecheck → 0 errors
□ test → exit 0
□ build → success
□ health endpoint responds (API stacks)
```

### Final ✓
```
□ Initial git commit made (after install + verification)
□ Summary card shown with correct commands for detected PM
□ Reproducible command shown
□ .cursor/AGENTS.md last-scaffold config saved
□ Ready for /new-feature
```
