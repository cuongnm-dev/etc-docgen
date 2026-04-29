# ref-ci.md — CI/CD Templates

## GitHub Actions — Node.js (`.github/workflows/ci.yml`)
```yaml
name: CI
on:
  push: { branches: [main, develop] }
  pull_request: { branches: [main, develop] }

jobs:
  ci:
    runs-on: ubuntu-latest
    services:                          # remove if no PostgreSQL
      postgres:
        image: postgres:16-alpine
        env: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: testdb }
        options: >-
          --health-cmd pg_isready --health-interval 10s
          --health-timeout 5s --health-retries 5
        ports: ["5432:5432"]
    steps:
      - uses: actions/checkout@v4
      - uses: pnpm/action-setup@v4
      - uses: actions/setup-node@v4
        with: { node-version: 22, cache: pnpm }
      - run: pnpm install --frozen-lockfile
      - run: pnpm lint
      - run: pnpm typecheck
      - run: pnpm test --coverage
      - run: pnpm build
```

## GitHub Actions — Python (`.github/workflows/ci.yml`)
```yaml
name: CI
on:
  push: { branches: [main, develop] }
  pull_request: { branches: [main, develop] }

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
        with: { python-version: "3.12" }
      - run: uv sync --frozen
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy app/
      - run: uv run pytest --cov --cov-report=xml
```

## GitHub Actions — Go (`.github/workflows/ci.yml`)
```yaml
name: CI
on:
  push: { branches: [main, develop] }
  pull_request: { branches: [main, develop] }

jobs:
  ci:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-go@v5
        with: { go-version: '1.23' }
      - run: go mod download
      - run: go vet ./...
      - run: go test -race -coverprofile=coverage.out ./...
      - run: go build ./...
```

## GitLab CI (`.gitlab-ci.yml`) — Node.js
```yaml
stages: [lint, test, build]
default:
  image: node:22-alpine
  before_script: [corepack enable, pnpm install --frozen-lockfile]

lint:
  stage: lint
  script: [pnpm lint, pnpm typecheck]

test:
  stage: test
  services: [postgres:16-alpine]
  variables: { POSTGRES_PASSWORD: postgres, POSTGRES_DB: testdb }
  script: [pnpm test --coverage]
  artifacts:
    reports:
      coverage_report: { coverage_format: cobertura, path: coverage/cobertura-coverage.xml }

build:
  stage: build
  script: [pnpm build]
  artifacts: { paths: [dist/] }
```

## `.github/PULL_REQUEST_TEMPLATE.md`
```markdown
## What does this PR do?
{1-2 sentences — the why, not just the what}

## Type
- [ ] Feature  - [ ] Bug fix  - [ ] Refactor  - [ ] Docs / config

## Related
- Feature: {PREFIX-YYYYMMDD-NNN}
- Issue: #{issue}

## Checklist
- [ ] Tests added / updated
- [ ] Docs updated (if applicable)
- [ ] No hardcoded secrets or credentials
- [ ] Lint + typecheck pass locally
```
