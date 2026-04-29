# ref-stack-react-spa.md — React SPA (Vite)

## Directory Tree
```
{name}/
  src/
    components/   shared reusable UI
    pages/        route-level components
    hooks/        custom React hooks (use* prefix)
    services/     API clients (lib/{service}/client.ts)
    stores/       state (Zustand/Jotai)
    lib/          pure utilities
    types/        TypeScript types/interfaces
    assets/
    App.tsx | main.tsx | router.tsx
  public/
  tests/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .github/workflows/
  .env.example | .env | .gitignore | .editorconfig | README.md | CLAUDE.md
  package.json | tsconfig.json | vite.config.ts | biome.json
```

## Starter Code

**`src/App.tsx`**
```tsx
export default function App() {
  return (
    <main style={{ display:'flex', minHeight:'100vh', alignItems:'center', justifyContent:'center' }}>
      <h1>PROJECT_NAME</h1>
    </main>
  )
}
// Replace PROJECT_NAME with actual project name when scaffolding
```

**`src/main.tsx`**
```tsx
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './index.css'
createRoot(document.getElementById('root')!).render(<StrictMode><App /></StrictMode>)
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: React SPA conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (React SPA)
## Rules
- Components: PascalCase. Props interface: `{Name}Props`. No default exports in non-page files.
- Hooks: `use` prefix. Custom hooks in `hooks/`.
- Server state: TanStack Query. Client/UI: Zustand/Jotai — one store per domain.
- All API calls via `services/{resource}/client.ts` — no raw fetch in components.
- Colocate state with the component that owns it. Lift only when forced.
## Anti-patterns
No `any` | No prop drilling beyond 2 levels | No business logic in components
```

## `.env.example`
```bash
VITE_APP_TITLE={project-name}
VITE_API_URL=http://localhost:3000
# VITE_SUPABASE_URL=
# VITE_SUPABASE_ANON_KEY=
```

## `.gitignore`
```
node_modules/
dist/
.env
.env.local
coverage/
*.log
.DS_Store
```

## Scaffold command
```bash
pnpm create vite {name} --template react-ts
cd {name} && pnpm install
```

## Verification
`pnpm lint` → `pnpm typecheck` → `pnpm test` → `pnpm build`
