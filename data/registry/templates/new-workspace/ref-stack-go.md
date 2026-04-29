# ref-stack-go.md — Go API

## Directory Tree
```
{name}/
  cmd/app/        main.go
  internal/
    handler/      handler.go | health.go
    service/      {resource}_service.go
    repository/   {resource}_repo.go
    domain/       types.go | errors.go
    middleware/   logger.go | requestid.go
  pkg/            (exported packages)
  configs/
  migrations/
  tests/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .github/workflows/ | Dockerfile | docker-compose.yml | .dockerignore
  .env.example | .env | .gitignore | .editorconfig | README.md | CLAUDE.md
  go.mod | go.sum | Makefile
```

## Starter Code

**`cmd/app/main.go`**
```go
package main

import (
    "encoding/json"
    "log/slog"
    "net/http"
    "os"
    "time"
)

func main() {
    logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))
    mux := http.NewServeMux()

    mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(map[string]string{"status": "ok", "ts": time.Now().UTC().Format(time.RFC3339)})
    })
    mux.HandleFunc("GET /", func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(map[string]string{"message": "Hello from {project-name}"})
    })

    port := os.Getenv("PORT")
    if port == "" { port = "8080" }
    logger.Info("starting server", "port", port)
    if err := http.ListenAndServe(":"+port, mux); err != nil {
        logger.Error("server error", "err", err)
        os.Exit(1)
    }
}
```

**`Makefile`**
```makefile
.PHONY: dev build test lint
dev:   go run ./cmd/app
build: go build -o bin/app ./cmd/app
test:  go test -race ./...
lint:  golangci-lint run
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: Go conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (Go)
## Layer Rules
- Handler: parse request, call service, write response. No business logic.
- Service: business rules, depend on repository interfaces (not concrete types).
- Repository: data access only. Accept context.Context as first param.
- Errors: wrap with context `fmt.Errorf("op: %w", err)`. Never swallow.
- No global vars except logger + config (init once at startup).
## Anti-patterns
No `panic` in request paths | No `interface{}` unless unavoidable
No goroutines without bounded lifetime | No SQL in handler or service layers
```

## `.env.example`
```bash
PORT=8080
DATABASE_URL=postgres://postgres:postgres@localhost:5432/appdb?sslmode=disable
LOG_LEVEL=info
```

## `.gitignore`
```
/bin/
/tmp/
.env
*.log
.DS_Store
```

## Scaffold command
```bash
mkdir {name} && cd {name}
go mod init github.com/{org}/{name}
go get github.com/joho/godotenv
```

## Verification
`golangci-lint run` → `go vet ./...` → `go test -race ./...` → `go build ./cmd/...` → `curl localhost:8080/health`
