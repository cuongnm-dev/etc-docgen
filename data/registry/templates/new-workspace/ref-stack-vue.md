# ref-stack-vue.md — Vue / Nuxt

## Directory Tree (Vue with Vite)
```
{name}/
  src/
    components/   PascalCase.vue
    pages/        (vue-router) or app/ (Nuxt)
    composables/  use*.ts
    stores/       Pinia stores
    services/     API clients
    types/
    assets/
    App.vue | main.ts | router.ts
  public/
  tests/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .env.example | .env | .gitignore | .editorconfig | README.md | CLAUDE.md
  package.json | tsconfig.json | vite.config.ts | biome.json
```

## Starter Code

**`src/App.vue`**
```vue
<template>
  <main class="container">
    <h1>{{ title }}</h1>
  </main>
</template>

<script setup lang="ts">
const title = '{project-name}'
</script>
```

**`src/main.ts`**
```ts
import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.mount('#app')
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: Vue/Nuxt conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (Vue)
## Rules
- Script Setup (`<script setup lang="ts">`) everywhere. No Options API.
- Components: PascalCase. Props via `defineProps<Props>()`.
- composables/ is hooks/ equivalent — `use` prefix, in `composables/`.
- State: Pinia stores, one per domain. No Vuex.
- Keep templates declarative. Logic in composables or services.
- Server state: TanStack Query (@tanstack/vue-query). No manual fetch in components.
## Anti-patterns
No `any` | No global state mutation outside stores | No business logic in templates
```

## `.env.example`
```bash
VITE_APP_TITLE={project-name}
VITE_API_URL=http://localhost:3000
```

## `.gitignore`
```
node_modules/
dist/
.nuxt/
.output/
.env
.env.local
coverage/
*.log
.DS_Store
```

## Scaffold commands
```bash
# Vue (Vite)
pnpm create vue@latest
# Nuxt
pnpm dlx nuxi@latest init {name}
```

## Verification
`pnpm lint` → `pnpm typecheck` → `pnpm test` → `pnpm build`
