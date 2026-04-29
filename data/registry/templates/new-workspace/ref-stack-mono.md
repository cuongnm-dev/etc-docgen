# ref-stack-mono.md — Monorepo

## Directory Tree (tool-agnostic layout)
```
{name}/
  src/
    apps/
      web/                ← deployable frontend app (example)
        src/
        docs/features/
        package.json | tsconfig.json
    services/
      api/                ← backend service (example)
        src/
        db/migrations/
        docs/features/
        Dockerfile
        package.json | tsconfig.json
    shared/               ← shared code (imported as @{workspace}/*)
      types/              type definitions
      ui/                 shared UI components
      utils/              shared utilities
  packages/               ← shared tooling configs (eslint, tsconfig base)
    config/
  infra/                  Docker, K8s, CI configs
  docs/
    architecture/adr/
    business/
    features/             ← cross-cutting features only
  .cursor/AGENTS.md | .cursor/rules/
  .gitignore | .editorconfig | .gitleaks.toml | README.md | CLAUDE.md | CONTRIBUTING.md
  {tool-config}           ← nx.json | turbo.json | pnpm-workspace.yaml
  package.json | tsconfig.base.json
```

## Tool-specific root files

**pnpm-workspace.yaml** (paths MUST match Directory Tree above)
```yaml
packages:
  - 'src/apps/*'
  - 'src/services/*'
  - 'src/shared/*'
  - 'packages/*'
```

**turbo.json**
```json
{
  "$schema": "https://turbo.build/schema.json",
  "ui": "tui",
  "tasks": {
    "build": { "dependsOn": ["^build"], "inputs": ["$TURBO_DEFAULT$"], "outputs": [".next/**", "dist/**"] },
    "dev": { "cache": false, "persistent": true },
    "test": { "dependsOn": ["^build"] },
    "lint": {},
    "typecheck": {}
  }
}
```

**Root `package.json` (pnpm workspaces)**
```json
{
  "name": "{name}",
  "private": true,
  "scripts": {
    "dev":       "turbo dev",
    "build":     "turbo build",
    "test":      "turbo test",
    "lint":      "turbo lint",
    "typecheck": "turbo typecheck"
  },
  "devDependencies": {
    "turbo": "latest",
    "typescript": "^5",
    "@biomejs/biome": "latest"
  },
  "packageManager": "pnpm@9"
}
```

**`tsconfig.base.json`**
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022"],
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "strict": true,
    "skipLibCheck": true,
    "paths": {
      "@{name}/types": ["./src/shared/types/src/index.ts"],
      "@{name}/ui": ["./src/shared/ui/src/index.ts"],
      "@{name}/utils": ["./src/shared/utils/src/index.ts"]
    }
  }
}
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: Monorepo conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (Monorepo)
## Import Rules
- Apps/services import from `src/shared/` only — never from each other directly.
- Cross-service data: API calls only — never direct package import between services.
- Internal shared packages declared as workspace deps: `"@{name}/types": "workspace:*"`.
- No circular dependencies between shared packages.
## Docs-Path Rules
- Cross-cutting feature: `docs/features/{feature-id}/`
- App-scoped: `src/apps/{app}/docs/features/{feature-id}/`
- Service-scoped: `src/services/{svc}/docs/features/{feature-id}/`
## Commands
Run `--filter {app}` to scope to one app: `pnpm --filter {app} dev`
```

## `.env.example`
```bash
# Root .env — shared vars
NODE_ENV=development
# Each app/service has its own .env — see src/apps/<app>/.env.example
```

## `.gitignore`
```
node_modules/
dist/
.next/
.turbo/
.cache/
build/
.env
.env.local
coverage/
*.log
.DS_Store
```

## Scaffold commands
```bash
# Turborepo
npx create-turbo@latest {name}

# NX
npx create-nx-workspace@latest {name}

# pnpm workspaces (manual)
mkdir {name} && cd {name}
pnpm init
# create pnpm-workspace.yaml, tsconfig.base.json manually
mkdir -p src/apps src/services src/shared packages infra docs/architecture/adr docs/features
```

## Verification
`pnpm lint` → `pnpm typecheck` → `pnpm test` → `pnpm build`
