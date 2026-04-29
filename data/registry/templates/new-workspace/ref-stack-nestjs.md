# ref-stack-nestjs.md — NestJS

## Directory Tree
```
{name}/
  src/
    health/           health.controller.ts | health.module.ts
    {module}/         {module}.module | controller | service | repository
                      dto/ | entities/
    common/           filters/ | guards/ | interceptors/ | pipes/ | decorators/
    config/           configuration.ts
    app.module.ts | main.ts
  db/migrations/
  tests/unit/ | tests/integration/ | tests/e2e/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .github/workflows/ | Dockerfile | docker-compose.yml | .dockerignore
  .env.example | .env | .gitignore | .editorconfig | README.md | CLAUDE.md
  package.json | tsconfig.json | nest-cli.json | biome.json
```

## Starter Code

**`src/health/health.controller.ts`**
```ts
import { Controller, Get } from '@nestjs/common'
@Controller('health')
export class HealthController {
  @Get()
  check() { return { status: 'ok', ts: new Date().toISOString() } }
}
```

**`src/main.ts`**
```ts
import { NestFactory } from '@nestjs/core'
import { ValidationPipe } from '@nestjs/common'
import { AppModule } from './app.module'
async function bootstrap() {
  const app = await NestFactory.create(AppModule)
  app.useGlobalPipes(new ValidationPipe({ whitelist: true, transform: true }))
  app.enableCors()
  await app.listen(process.env.PORT ?? 3000)
  console.log(`Application running on port ${process.env.PORT ?? 3000}`)
}
bootstrap()
```

**`src/app.module.ts`**
```ts
import { Module } from '@nestjs/common'
import { ConfigModule } from '@nestjs/config'
import { HealthController } from './health/health.controller'
@Module({
  imports: [ConfigModule.forRoot({ isGlobal: true })],
  controllers: [HealthController],
})
export class AppModule {}
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: NestJS conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (NestJS)
## Layer Rules
- Controller: HTTP only (parse, validate, serialize, status codes). No business logic.
- Service: business logic only. No HTTP knowledge, no direct DB calls.
- Repository: DB queries only. No business rules.
- DTOs: class-validator on every input field. Always whitelist: true.
- Never return raw ORM entities — always map to response DTOs.
## Error Handling
Throw domain exceptions from services. Exception filter maps to HTTP. Never expose stack traces.
## Anti-patterns
No `any` | No business logic in controllers | No direct DB in services
```

## `.env.example`
```bash
NODE_ENV=development
PORT=3000
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/appdb
# JWT (if auth selected)
JWT_SECRET=change-me-min-32-chars
JWT_EXPIRES_IN=15m
REFRESH_TOKEN_EXPIRES_IN=7d
# Redis (if cache selected)
REDIS_URL=redis://localhost:6379
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
pnpm dlx @nestjs/cli new {name} --package-manager pnpm --strict
```

## Verification
`pnpm lint` → `pnpm typecheck` → `pnpm test` → `pnpm build` → `curl localhost:3000/health`
