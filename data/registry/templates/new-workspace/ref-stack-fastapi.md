# ref-stack-fastapi.md — Python FastAPI

## Directory Tree
```
{name}/
  app/
    api/v1/routers/   health.py | {resource}.py
    api/v1/schemas/   {resource}.py
    core/             config.py | security.py | logging.py | database.py
    models/           user.py | {resource}.py
    repositories/     user_repository.py
    services/         user_service.py
    dependencies.py | main.py
  db/migrations/      (Alembic)
  tests/unit/ | tests/integration/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .github/workflows/ | Dockerfile | docker-compose.yml | .dockerignore
  .env.example | .env | .gitignore | .editorconfig | README.md | CLAUDE.md
  pyproject.toml
```

## Starter Code

**`app/main.py`**
```python
from contextlib import asynccontextmanager
from datetime import datetime, UTC
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = structlog.get_logger()

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info('startup', app='{project-name}')
    yield
    logger.info('shutdown')

app = FastAPI(title='{project-name}', lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=['http://localhost:3000'], allow_credentials=True, allow_methods=['*'], allow_headers=['*'])

@app.get('/health')
async def health():
    return {'status': 'ok', 'ts': datetime.now(UTC).isoformat()}

@app.get('/')
async def root():
    return {'message': 'Hello from {project-name}'}
```

**`app/core/config.py`**
```python
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')
    ENVIRONMENT: str = 'development'
    DATABASE_URL: str = 'sqlite+aiosqlite:///./dev.db'
    SECRET_KEY: str = 'change-me'
    ALGORITHM: str = 'HS256'
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15

settings = Settings()
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: FastAPI conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (FastAPI)
## Layer Rules
- Router: HTTP only — call services, return schemas, set status codes.
- Service: business logic — call repositories, enforce invariants.
- Repository: session + queries only. No business rules.
- All inputs validated by Pydantic schema at router boundary.
- `async def` for all endpoints and DB operations.
- Settings via `pydantic-settings` — never `os.environ` directly.
## Anti-patterns
No `*` imports | No logic in `__init__.py` | No `print()` — use structlog
No raw SQLAlchemy models in responses — always serialize via schema
```

## `.env.example`
```bash
ENVIRONMENT=development
DATABASE_URL=sqlite+aiosqlite:///./dev.db
# For PostgreSQL: postgresql+asyncpg://postgres:postgres@localhost:5432/appdb
SECRET_KEY=change-me-min-32-chars
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
```

## `.gitignore`
```
__pycache__/
*.pyc
.venv/
venv/
.env
.pytest_cache/
.ruff_cache/
htmlcov/
.coverage
dist/
*.egg-info/
.DS_Store
```

## Scaffold command
```bash
uv init {name}
cd {name}
uv add fastapi uvicorn pydantic-settings sqlalchemy alembic structlog
uv add --dev pytest pytest-cov pytest-asyncio httpx ruff mypy
```

## Verification
`uv run ruff check .` → `uv run mypy app/` → `uv run pytest` → `curl localhost:8000/health`
