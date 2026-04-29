# Async Job API

The job-based pipeline lets clients submit large `content-data.json` payloads
to etc-platform without ever putting the bytes through an LLM context window.
It is the recommended path for any payload above ~50 KB.

```
   ┌────────┐  POST /workspaces (multipart) ┌──────────┐
   │ client │ ──────────────────────────────►          │
   │ (LLM)  │ ◄────── workspace_id ─────────┤ etc-     │
   │        │                               │ docgen   │
   │        │  POST /jobs (MCP)             │          │
   │        │ ──── workspace_id ────────────►          │
   │        │ ◄──────── job_id ─────────────┤  store + │
   │        │                               │  worker  │
   │        │  GET  /jobs/<id>              │  pool    │
   │        │ ──────────────────────────────►          │
   │        │ ◄──── status / outputs ───────┤          │
   │        │  GET  /jobs/<id>/files/<name> │          │
   │        │ ──────────────────────────────►          │
   │        │ ◄──── binary stream ──────────┤          │
   └────────┘                               └──────────┘
```

## Sources: workspace vs upload

| Source | When to use | What it carries |
|---|---|---|
| **Workspace** (recommended) | Any project — required for HDSD with screenshots | content-data.json + screenshots/ + diagrams/ |
| Upload (legacy) | Code-only docs (TKKT/TKCS/TKCT/xlsx) on tiny demos | content-data.json only |

Workspaces are content-addressed: re-uploading identical content returns the
same `workspace_id` (TTL refreshed) so re-rendering is free of byte cost.

## Endpoints

### `POST /workspaces`

Multipart form with multiple file parts. Each file's workspace-relative path
is encoded in the form field name as `files[<path>]`. Optional `label` form
field for human grepping.

```bash
curl -fsS -X POST http://localhost:8000/workspaces \
  -F "files[content-data.json]=@content-data.json;type=application/json" \
  -F "files[screenshots/F-001-step-01-initial.png]=@step-01.png;type=image/png" \
  -F "files[screenshots/F-001-step-02-filled.png]=@step-02.png;type=image/png" \
  -F "label=customs-stage6"
```

**Path rules** (enforced by validator):
- POSIX-style relative paths only
- No `..`, no leading `/`, no backslashes
- Max depth 4 (`a/b/c/d.txt` OK, `a/b/c/d/e.txt` rejected)
- Charset: `[A-Za-z0-9_-./]`
- Max 200 files per workspace; 100 MB total; 10 MB per file (configurable)

**Response** `201 Created`:

```json
{
  "workspace_id": "ws_4kJ9mP3qSx...",
  "sha256": "8a91f...",
  "parts": [
    {"path": "content-data.json",
     "size_bytes": 173420, "sha256": "...",
     "content_type": "application/json"},
    {"path": "screenshots/F-001-step-01-initial.png",
     "size_bytes": 245312, "sha256": "...",
     "content_type": "image/png"}
  ],
  "total_size": 23845210,
  "file_count": 4,
  "created_at": "...",
  "expires_at": "...",
  "label": "customs-stage6"
}
```

**Errors**
- `400 WORKSPACE_INVALID_PATH` — path violates validator
- `400 EMPTY_WORKSPACE` — no `files[...]` parts
- `413 WORKSPACE_TOO_LARGE` — exceeds total / per-file / file-count limit
- `415 UNSUPPORTED_MEDIA_TYPE` — content-type not allowed (future)

### `GET /workspaces/{workspace_id}`

Returns the manifest. Use to verify TTL or audit contents before render.

### `DELETE /workspaces/{workspace_id}`

Idempotent.

### `POST /uploads` (legacy)

Multipart form with a single `file` part holding the JSON payload, and an
optional `label` form field for human grepping. Use only when no screenshots
are needed.

```bash
curl -fsS -X POST http://localhost:8000/uploads \
  -F file=@content-data.json \
  -F label=gdt-tax-2030
```

**Response** `201 Created`:

```json
{
  "upload_id": "u_4kJ9mP...",
  "size_bytes": 173420,
  "sha256": "8a91f...",
  "content_type": "application/json",
  "created_at": "2026-04-26T15:30:00Z",
  "expires_at": "2026-04-26T16:00:00Z",
  "label": "gdt-tax-2030"
}
```

**Errors**
- `413 UPLOAD_TOO_LARGE` — payload exceeds `ETC_DOCGEN_MAX_UPLOAD_BYTES`.
- `4xx` — payload is not valid JSON / UTF-8.

### `GET /uploads/{upload_id}`

Returns the upload metadata. Use to verify TTL before submitting a job.

### `DELETE /uploads/{upload_id}`

Idempotent. Returns `204` whether or not the upload existed.

### `POST /jobs`

Provide EXACTLY ONE source: `workspace_id` (recommended) OR `upload_id` (legacy).

JSON body:

```json
{
  "workspace_id": "ws_...",
  "targets": ["tkkt", "tkct", "xlsx", "hdsd"],
  "auto_render_mermaid": true,
  "label": "stage-6-export"
}
```

Or, legacy single-file flow:

```json
{
  "upload_id": "u_...",
  "targets": ["tkkt"],
  "auto_render_mermaid": true
}
```

`targets` is a subset of `xlsx | hdsd | tkkt | tkcs | tkct`; defaults to all 5.

**Response** `202 Accepted`:

```json
{
  "job_id": "j_uX2k...",
  "workspace_id": "ws_4kJ9...",
  "upload_id": null,
  "status": "queued",
  "targets": ["tkkt", "tkct", "xlsx", "hdsd"],
  "created_at": "2026-04-26T15:31:00Z",
  "expires_at": "2026-04-26T16:31:00Z",
  "outputs": [],
  "error": null,
  "label": "stage-6-export"
}
```

**Errors**
- `400 MISSING_SOURCE`    — neither workspace_id nor upload_id provided.
- `400 AMBIGUOUS_SOURCE`  — both provided.
- `400 INVALID_TARGET`    — unknown name in `targets[]`.
- `404 WORKSPACE_NOT_FOUND` / `UPLOAD_NOT_FOUND` — id does not exist or has expired.
- `503 QUEUE_FULL`        — runner queue saturated; retry after 5–20 s backoff.

### `GET /jobs/{job_id}`

Returns the job's public view. Poll every 1–2 s. Status reaches one of
`succeeded | failed | cancelled | expired` within `RUNNER_TIMEOUT_S`
(default 300 s).

On `succeeded`, `outputs[]` contains:

```json
[
  {
    "target": "tkkt",
    "filename": "thiet-ke-kien-truc.docx",
    "size_bytes": 73128,
    "sha256": "deadbeef...",
    "download_url": "/jobs/j_uX2k.../files/thiet-ke-kien-truc.docx"
  }
]
```

### `GET /jobs/{job_id}/files/{filename}`

Streams the rendered output. `Content-Type` reflects the actual format
(`...wordprocessingml.document` for `.docx`, `...spreadsheetml.sheet` for
`.xlsx`). The agent saves the bytes to its target directory; nothing is
parsed in the LLM.

### `DELETE /jobs/{job_id}`

Idempotent.

### `GET /healthz` / `GET /readyz`

`/healthz` — liveness, no I/O.
`/readyz`  — exercises storage write + reports runner stats.

## MCP tools (same protocol, in-process)

The same operations are reachable from MCP clients without doing curl:

| MCP tool                | What it does                                                              |
| ----------------------- | ------------------------------------------------------------------------- |
| `validate_workspace`    | Validate content-data inside a workspace (auto-detects content-data.json) |
| `validate_uploaded`     | Validate a legacy single-file upload                                      |
| `export_async`          | Equivalent to `POST /jobs`. Accepts `workspace_id` or `upload_id`         |
| `job_status`            | Equivalent to `GET /jobs/{id}`                                            |
| `cancel_job`            | Mark a queued job as cancelled                                            |
| `upload_capacity`       | `/readyz` data — useful before big batches                                |

Notes:
* `upload` and `workspace` creation have no MCP equivalent — bytes are
  deliberately routed via HTTP only, so they never enter the LLM token stream.
* MCP tools and HTTP endpoints share one in-process JobStore + JobRunner
  through `etc_platform.jobs.shared`.

## Authentication

If `ETC_DOCGEN_API_KEY` is set, every route except `/healthz` requires a
matching `X-API-Key` header. Use TLS-terminating reverse proxy (nginx,
Caddy, Traefik) for transport security. The server itself speaks plain
HTTP by design — no key material on disk.

## Environment variables

| Variable                          | Default      | Meaning                                  |
| --------------------------------- | ------------ | ---------------------------------------- |
| `ETC_DOCGEN_JOBS_ROOT`            | `/data/_jobs`| Filesystem root for uploads + jobs + workspaces. |
| `ETC_DOCGEN_UPLOAD_TTL_S`         | `1800`       | Upload TTL (sec).                        |
| `ETC_DOCGEN_WORKSPACE_TTL_S`      | `86400`      | Workspace TTL (24h — longer than job).   |
| `ETC_DOCGEN_MAX_WORKSPACE_BYTES`  | `104857600`  | Workspace cap, 100 MB total.             |
| `ETC_DOCGEN_MAX_WORKSPACE_FILES`  | `200`        | Workspace cap, max files per bundle.     |
| `ETC_DOCGEN_JOB_TTL_S`            | `3600`       | Job TTL (sec).                           |
| `ETC_DOCGEN_MAX_UPLOAD_BYTES`     | `10485760`   | Per-upload cap (bytes, 10 MB).           |
| `ETC_DOCGEN_RUNNER_WORKERS`       | `2`          | Concurrent rendering jobs.               |
| `ETC_DOCGEN_RUNNER_QUEUE_MAX`     | `100`        | Queue back-pressure threshold.           |
| `ETC_DOCGEN_RUNNER_TIMEOUT_S`     | `300`        | Per-job hard ceiling.                    |
| `ETC_DOCGEN_API_KEY`              | unset        | Enable API-key auth.                     |
| `ETC_DOCGEN_CORS_ORIGINS`         | unset        | Comma-separated allowed origins.         |
| `LOG_LEVEL`                       | `INFO`       | Standard Python log levels.              |

## Migration from inline `export()` (v1.0)

Old:
```python
result = mcp__etc-platform__export(content_data={...173 KB...})
out = base64.b64decode(result["outputs"]["thiet-ke-kien-truc.docx"])
write(out, "/path/to/file.docx")
```

New:
```bash
UPLOAD_ID=$(curl -sS -F file=@content-data.json http://localhost:8000/uploads | jq -r .upload_id)
```
```python
job = mcp__etc-platform__export_async(upload_id=UPLOAD_ID, targets=["tkkt"])
# poll until status in (succeeded, failed)
```
```bash
curl -fsS -o thiet-ke-kien-truc.docx \
  "http://localhost:8000/jobs/$JOB_ID/files/thiet-ke-kien-truc.docx"
```

Token cost change:

| Phase             | v1 inline     | v2 job-based |
| ----------------- | ------------- | ------------ |
| Upload payload    | ~50 K tokens  | 0            |
| Job creation      | included      | ~30 tokens   |
| Status poll (×N)  | n/a           | ~30 each     |
| Outputs return    | ~70 K tokens  | 0            |
| **Per export**    | ~120 K        | ~80          |

## Operational notes

* **Storage growth**: under default TTLs, peak disk = `(workers × largest job output) + (open uploads × max_upload_bytes)`. For a 5-target job with ~150 KB Office files each, that's <5 MB per concurrent job. Plan ~1 GB of disk per shared deployment.
* **Worker tuning**: each worker is CPU-bound during render (docxtpl + openpyxl). On a 4-core host, `ETC_DOCGEN_RUNNER_WORKERS=2` is safe; raise to 4 only if Mermaid is disabled (mermaid-cli forks Chromium and competes for CPU).
* **Backpressure**: when the queue saturates, clients get `503 QUEUE_FULL`. Don't bury the retry — surface it; queue-full means your team is contending for shared infrastructure and someone needs to know.
* **TTL trade-off**: lowering job TTL reclaims disk faster but makes "download later" workflows brittle. The default 1 h matches typical CI run length.

## Threat model

* **Path traversal** — IDs validated against `^[A-Za-z0-9_-]{2,64}$`; download filenames must match a recorded `JobOutput.filename` (no arbitrary stem from URL).
* **Tenant isolation** — single-tenant by default. For multi-tenant, set `ETC_DOCGEN_API_KEY` and run a key per tenant; uploads/jobs are not yet scoped per key (planned).
* **Resource exhaustion** — capped via `MAX_UPLOAD_BYTES` + queue back-pressure + per-job timeout. A misbehaving renderer cannot run forever.
* **Stored XSS / template injection** — content_data is rendered through docxtpl's autoescape; raw HTML is never concatenated into Office XML by hand.
