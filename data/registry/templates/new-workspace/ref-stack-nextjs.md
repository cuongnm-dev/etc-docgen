# ref-stack-nextjs.md — Next.js (App Router)

## Directory Tree
```
{name}/
  app/
    (auth)/           layout.tsx | login/page.tsx
    (dashboard)/      layout.tsx | page.tsx
    api/health/       route.ts
    layout.tsx | page.tsx | error.tsx | loading.tsx
  components/
    ui/               base components
    {feature}/        feature-specific components
  lib/
    {service}/        API clients, utilities
  hooks/
  types/
  public/
  tests/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .github/workflows/ | .env.example | .env
  .gitignore | .editorconfig | README.md | CLAUDE.md
  package.json | tsconfig.json | next.config.ts | biome.json
```

## Starter Code

**`app/page.tsx`**
```tsx
export default function Home() {
  return <main className="flex min-h-screen items-center justify-center"><h1 className="text-4xl font-bold">PROJECT_NAME</h1></main>
}
// Replace PROJECT_NAME with actual project name when scaffolding
```

**`app/api/health/route.ts`**
```ts
import { NextResponse } from 'next/server'
export const runtime = 'edge'
export function GET() {
  return NextResponse.json({ status: 'ok', ts: new Date().toISOString() })
}
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: Next.js coding conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (Next.js)
## Stack
Next.js {ver} | TypeScript strict | Tailwind | {Zustand|Jotai} | TanStack Query
## Rules
- Server Components by default. `"use client"` only: event handlers, browser APIs, stateful hooks.
- Props interface: `{Name}Props`. No default exports except page.tsx/layout.tsx.
- Server state: TanStack Query. Client/UI: one Zustand/Jotai store per domain.
- All external calls via `lib/{service}/client.ts` — no raw fetch in components.
- Error shape: `{ error: string, code?: string }` from API routes.
## Anti-patterns
No `any` | No `useEffect` for data fetching | No business logic in components | No `console.log`
```

## `.env.example`
```bash
NODE_ENV=development
NEXT_PUBLIC_APP_URL=http://localhost:3000
# Database (if ORM selected)
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/appdb
# Auth (fill for chosen provider)
# NEXT_PUBLIC_SUPABASE_URL=
# NEXT_PUBLIC_SUPABASE_ANON_KEY=
# JWT_SECRET=change-me-min-32-chars
```

## `.gitignore`
```
node_modules/
.next/
dist/
.env
.env.local
.env.*.local
coverage/
*.log
.DS_Store
```

## Scaffold command
```bash
pnpm create next-app {name} --typescript --tailwind --eslint --app --import-alias "@/*"
```

## Verification
`pnpm lint` → `pnpm typecheck` → `pnpm test` → `pnpm build` → `curl localhost:3000/api/health`
