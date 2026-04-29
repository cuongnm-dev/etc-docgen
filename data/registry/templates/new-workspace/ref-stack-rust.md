# ref-stack-rust.md — Rust (Axum)

## Directory Tree
```
{name}/
  src/
    routes/       health.rs | mod.rs
    models/       mod.rs
    state.rs
    main.rs
  tests/
  docs/architecture/adr/ | docs/features/
  .cursor/AGENTS.md | .cursor/rules/
  .github/workflows/ | Dockerfile | docker-compose.yml | .dockerignore
  .env.example | .env | .gitignore | .editorconfig | README.md | CLAUDE.md
  Cargo.toml | Cargo.lock
```

## Starter Code

**`src/main.rs`**
```rust
use axum::{routing::get, Json, Router};
use serde_json::{json, Value};
use std::net::SocketAddr;
use tokio::net::TcpListener;
use chrono::Utc;

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();
    let app = Router::new()
        .route("/", get(root))
        .route("/health", get(health));
    let port: u16 = std::env::var("PORT").ok().and_then(|p| p.parse().ok()).unwrap_or(8080);
    let addr = SocketAddr::from(([0, 0, 0, 0], port));
    tracing::info!("Listening on {}", addr);
    let listener = TcpListener::bind(addr).await.unwrap();
    axum::serve(listener, app).await.unwrap();
}
async fn root() -> Json<Value> { Json(json!({"message": "Hello from {project-name}"})) }
async fn health() -> Json<Value> { Json(json!({"status": "ok", "ts": Utc::now().to_rfc3339()})) }
```

**`Cargo.toml`**
```toml
[package]
name = "{name}"
version = "0.1.0"
edition = "2021"

[dependencies]
axum = "0.7"
tokio = { version = "1", features = ["full"] }
serde = { version = "1", features = ["derive"] }
serde_json = "1"
chrono = { version = "0.4", features = ["serde"] }
tracing = "0.1"
tracing-subscriber = "0.3"
dotenvy = "0.15"

[dev-dependencies]
axum-test = "14"
```

## `.cursor/rules/project-conventions.mdc`
```markdown
---
description: Rust/Axum conventions for {project-name}. Supplements global rules.
alwaysApply: false
---
# Conventions: {project-name} (Rust/Axum)
## Rules
- Return `Result<T, AppError>` from handlers and services. No `unwrap()` in production paths.
- Use `tracing::info!/warn!/error!` — never `println!`.
- Shared state via `Arc<AppState>` passed with `Extension` layer.
- Use `serde::Serialize/Deserialize` derives — no manual JSON construction.
## Anti-patterns
No `unwrap()` in handlers | No `panic!` in request paths | No global mutable state
```

## `.env.example`
```bash
PORT=8080
DATABASE_URL=postgres://postgres:postgres@localhost:5432/appdb
RUST_LOG=info
```

## `.gitignore`
```
/target/
.env
*.log
.DS_Store
```

## Scaffold command
```bash
cargo new {name}
cd {name}
```

## Verification
`cargo clippy -- -D warnings` → `cargo test` → `cargo build --release` → `curl localhost:8080/health`
