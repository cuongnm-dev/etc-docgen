# ref-docker.md — Docker Templates

## Dockerfiles (per language)

### Node.js (pnpm, multi-stage)
```dockerfile
FROM node:22-alpine AS deps
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/dist ./dist
COPY --from=deps /app/node_modules ./node_modules
COPY package.json ./
EXPOSE 3000
CMD ["node", "dist/main.js"]
```

### Python (uv, multi-stage)
```dockerfile
FROM python:3.12-slim AS deps
WORKDIR /app
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

FROM python:3.12-slim AS runner
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
COPY --from=deps /app/.venv ./.venv
COPY ./app ./app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Go (distroless, multi-stage)
```dockerfile
FROM golang:1.23-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 GOOS=linux go build -o /bin/app ./cmd/app

FROM gcr.io/distroless/static-debian12
COPY --from=builder /bin/app /app
EXPOSE 8080
ENTRYPOINT ["/app"]
```

### Rust (multi-stage)
```dockerfile
FROM rust:1.78-alpine AS builder
WORKDIR /app
RUN apk add --no-cache musl-dev
COPY Cargo.toml Cargo.lock ./
RUN mkdir src && echo "fn main(){}" > src/main.rs && cargo build --release && rm -rf src
COPY src ./src
RUN touch src/main.rs && cargo build --release

FROM gcr.io/distroless/static-debian12
COPY --from=builder /app/target/release/app /app
EXPOSE 8080
ENTRYPOINT ["/app"]
```

---

## docker-compose.yml — Mini-repo (compose per selections)

**Base template — always include:**
```yaml
services:
  app:
    build: .
    ports: ["${PORT:-3000}:${PORT:-3000}"]   # adjust port per stack
    env_file: .env
    restart: unless-stopped
    develop:
      watch:
        - { action: sync, path: ./src, target: /app/src }
```

**Port defaults per stack:**
| Stack | PORT |
|---|---|
| Node.js (NestJS, node-api, nextjs, react-spa, vue) | 3000 |
| Python FastAPI | 8000 |
| Go | 8080 |
| Rust | 8080 |

**`depends_on` block — add to `app` service when db is selected:**
```yaml
    depends_on:
      db:
        condition: service_healthy
```

**Add `cache` to depends_on when Redis selected:**
```yaml
    depends_on:
      db:
        condition: service_healthy
      cache:
        condition: service_started
```

**PostgreSQL service block — add when database = PostgreSQL:**
```yaml
  db:
    image: postgres:16-alpine
    environment:
      POSTGRES_DB: ${DB_NAME:-appdb}
      POSTGRES_USER: ${DB_USER:-postgres}
      POSTGRES_PASSWORD: ${DB_PASSWORD:-postgres}
    ports: ["5432:5432"]
    volumes: [db_data:/var/lib/postgresql/data]
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER:-postgres}"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  db_data:
```

**MySQL service block — add when database = MySQL:**
```yaml
  db:
    image: mysql:8-alpine
    environment:
      MYSQL_DATABASE: ${DB_NAME:-appdb}
      MYSQL_USER: ${DB_USER:-appuser}
      MYSQL_PASSWORD: ${DB_PASSWORD:-apppass}
      MYSQL_ROOT_PASSWORD: ${DB_ROOT_PASSWORD:-rootpass}
    ports: ["3306:3306"]
    volumes: [db_data:/var/lib/mysql]
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  db_data:
```

**MongoDB service block — add when database = MongoDB:**
```yaml
  db:
    image: mongo:7
    environment:
      MONGO_INITDB_DATABASE: ${DB_NAME:-appdb}
      MONGO_INITDB_ROOT_USERNAME: ${DB_USER:-mongo}
      MONGO_INITDB_ROOT_PASSWORD: ${DB_PASSWORD:-mongo}
    ports: ["27017:27017"]
    volumes: [db_data:/data/db]
    healthcheck:
      test: ["CMD", "mongosh", "--eval", "db.adminCommand('ping')"]
      interval: 5s
      timeout: 5s
      retries: 5

volumes:
  db_data:
```

**Redis service block — add when cache = Redis:**
```yaml
  cache:
    image: redis:7-alpine
    ports: ["6379:6379"]
    command: redis-server --save 20 1 --loglevel warning
    volumes: [cache_data:/data]

volumes:
  cache_data:
```

*(If both db and cache volumes exist, merge `volumes:` into one block at end of file.)*

---

## docker-compose.yml — Monorepo (add new service)

When `/new-project` adds a service to an existing monorepo, append to existing `docker-compose.yml`.
Use the actual path based on type: `src/services/<name>` for backend services, `src/apps/<name>` for frontend apps.

```yaml
  <name>:
    build:
      context: .
      dockerfile: src/services/<name>/Dockerfile    # or src/apps/<name>/Dockerfile
    ports: ["${PORT:-3000}:${PORT:-3000}"]          # use next available port
    env_file: .env
    restart: unless-stopped
    depends_on:                                     # only if db/cache already in compose
      db:
        condition: service_healthy
    develop:
      watch:
        - { action: sync, path: ./src/services/<name>/src, target: /app/src }
```

**Port assignment for monorepo — increment to avoid conflicts:**
- First service: 3000 (or 8000/8080 per stack)
- Second service: next +1 (3001, 8001, etc.)
- Check existing ports in `docker-compose.yml` before assigning

---

## .env — Templates per stack (dev defaults, matches docker-compose)

### Node.js stacks (NestJS, node-api, Next.js, React SPA, Vue)
```bash
NODE_ENV=development
PORT=3000

# Database — matches docker-compose service defaults
DB_HOST=localhost
DB_PORT=5432
DB_NAME={name}db
DB_USER=postgres
DB_PASSWORD=postgres
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/{name}db

# Redis — uncomment if cache=Redis selected
# REDIS_URL=redis://localhost:6379

# Auth — fill if auth provider selected
# SUPABASE_URL=
# SUPABASE_ANON_KEY=
# JWT_SECRET=dev-secret-change-in-production
```

### Python FastAPI
```bash
PORT=8000
PYTHONUNBUFFERED=1
APP_ENV=development

# Database — matches docker-compose service defaults
DB_HOST=localhost
DB_PORT=5432
DB_NAME={name}db
DB_USER=postgres
DB_PASSWORD=postgres
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/{name}db

# Redis — uncomment if cache=Redis selected
# REDIS_URL=redis://localhost:6379

# Auth
# JWT_SECRET=dev-secret-change-in-production
# JWT_ALGORITHM=HS256
# ACCESS_TOKEN_EXPIRE_MINUTES=30
```

### Go
```bash
PORT=8080
APP_ENV=development
LOG_LEVEL=debug

# Database — matches docker-compose service defaults
DB_HOST=localhost
DB_PORT=5432
DB_NAME={name}db
DB_USER=postgres
DB_PASSWORD=postgres
DATABASE_URL=postgres://postgres:postgres@localhost:5432/{name}db?sslmode=disable

# Redis — uncomment if cache=Redis selected
# REDIS_URL=redis://localhost:6379
```

### Rust
```bash
PORT=8080
RUST_LOG=debug
APP_ENV=development

# Database — matches docker-compose service defaults
DB_HOST=localhost
DB_PORT=5432
DB_NAME={name}db
DB_USER=postgres
DB_PASSWORD=postgres
DATABASE_URL=postgres://postgres:postgres@localhost:5432/{name}db

# Redis — uncomment if cache=Redis selected
# REDIS_URL=redis://localhost:6379
```

### Monorepo `.env` — root (aggregates all services)
```bash
# Shared
NODE_ENV=development

# Database — shared across services
DB_HOST=localhost
DB_PORT=5432
DB_NAME={name}db
DB_USER=postgres
DB_PASSWORD=postgres

# Redis — shared
REDIS_URL=redis://localhost:6379

# Per-service ports (each service reads its own PORT var)
{SERVICE_NAME}_PORT=3000
# Add new service ports here when running /new-project
```

---

## .dockerignore
```
node_modules/
.next/
dist/
build/
coverage/
.git/
.env
.env.local
*.log
__pycache__/
.venv/
target/
```
