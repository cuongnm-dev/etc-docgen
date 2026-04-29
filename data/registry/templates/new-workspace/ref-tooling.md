# ref-tooling.md — Node.js Tooling Configs

## `biome.json`
```json
{
  "$schema": "https://biomejs.dev/schemas/1.9.0/schema.json",
  "vcs": { "enabled": true, "clientKind": "git", "useIgnoreFile": true },
  "formatter": { "enabled": true, "indentStyle": "space", "indentWidth": 2 },
  "linter": {
    "enabled": true,
    "rules": {
      "recommended": true,
      "correctness": { "noUnusedVariables": "error" },
      "suspicious": { "noExplicitAny": "error" }
    }
  },
  "javascript": { "formatter": { "quoteStyle": "single", "trailingCommas": "all" } },
  "organizeImports": { "enabled": true }
}
```

## `vitest.config.ts`
```ts
import { defineConfig } from 'vitest/config'
import { resolve } from 'path'

export default defineConfig({
  test: {
    globals: true,
    environment: 'node',  // change to 'jsdom' for React/Vue
    coverage: { provider: 'v8', reporter: ['text', 'json', 'html'], thresholds: { lines: 80 } },
  },
  resolve: { alias: { '@': resolve(__dirname, './src') } },
})
```

## `lint-staged.config.mjs` (team projects)
```js
export default {
  '*.{ts,tsx,js,jsx}': ['biome check --write'],
  '*.{json,md,yaml,yml}': ['biome format --write'],
}
```

## `commitlint.config.mjs` (team projects)
```js
export default { extends: ['@commitlint/config-conventional'] }
```

## `.husky/pre-commit`
```sh
pnpm lint-staged
```

## `.husky/commit-msg`
```sh
pnpm exec commitlint --edit $1
```

## `package.json` scripts (normalized — same names regardless of stack)
```json
{
  "scripts": {
    "dev":        "{framework dev command}",
    "build":      "{build command}",
    "start":      "{start prod server}",
    "test":       "vitest run",
    "test:watch": "vitest",
    "test:ui":    "vitest --ui",
    "test:e2e":   "playwright test",
    "lint":       "biome check .",
    "lint:fix":   "biome check --write .",
    "typecheck":  "tsc --noEmit",
    "db:push":    "prisma db push",
    "db:migrate": "prisma migrate dev",
    "db:seed":    "tsx prisma/seed.ts",
    "db:studio":  "prisma studio"
  }
}
```
Remove scripts for unselected features (no `db:*` without ORM, no `test:e2e` without Playwright).
