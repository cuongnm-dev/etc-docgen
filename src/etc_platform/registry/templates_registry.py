"""Template registry tools for etc-platform MCP server.

Phase 1: minimal-risk centralization. Returns raw template content unchanged.
The calling skill remains responsible for interpretation. Phase 2+ may evolve
to Jinja rendering, structured outputs, etc.

Templates live under ``$ETC_PLATFORM_DATA_DIR/templates/{namespace}/{template_id}.md``.
``namespace`` groups related templates (e.g. ``new-workspace``,
``new-document-workspace``); ``template_id`` is the basename without extension.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

# Resolved on import; tests can monkeypatch via env var.
_DATA_DIR: Path = Path(os.environ.get("ETC_PLATFORM_DATA_DIR", "/data"))
_TEMPLATES_ROOT: Path = _DATA_DIR / "registry" / "templates"


def _resolve_template_path(namespace: str, template_id: str) -> Path:
    """Return absolute path for ``namespace/template_id.md``.

    Disallows traversal: ``..`` segments rejected; resolved path must stay
    inside ``_TEMPLATES_ROOT``.
    """
    if ".." in namespace.split("/") or ".." in template_id.split("/"):
        raise ValueError("Path traversal not allowed in namespace/template_id")
    candidate = (_TEMPLATES_ROOT / namespace / f"{template_id}.md").resolve()
    root = _TEMPLATES_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Resolved template path escapes templates root")
    return candidate


def template_load_impl(namespace: str, template_id: str) -> dict[str, Any]:
    """Read and return raw markdown template content.

    Parameters
    ----------
    namespace
        Logical group, e.g. ``new-workspace``.
    template_id
        Filename without ``.md`` extension, e.g. ``ref-stack-nextjs``.

    Returns
    -------
    dict
        Keys: ``namespace``, ``template_id``, ``content``, ``size_bytes``,
        ``sha256``, ``path`` (server-relative for debugging).

    Raises
    ------
    FileNotFoundError
        Template missing from registry.
    ValueError
        Path traversal attempt.
    """
    path = _resolve_template_path(namespace, template_id)
    if not path.is_file():
        raise FileNotFoundError(
            f"Template not found: {namespace}/{template_id}. "
            f"Use templates_list() to discover available templates."
        )
    content = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "namespace": namespace,
        "template_id": template_id,
        "content": content,
        "size_bytes": len(content.encode("utf-8")),
        "sha256": digest,
        "path": str(path.relative_to(_DATA_DIR)) if path.is_relative_to(_DATA_DIR) else str(path),
    }


def templates_list_impl(namespace: str | None = None) -> dict[str, Any]:
    """List available templates, optionally filtered to a single namespace.

    Returns
    -------
    dict
        Keys: ``namespaces`` — mapping namespace -> list of template_id strings.
        When ``namespace`` is provided, only that key is populated.
    """
    if not _TEMPLATES_ROOT.is_dir():
        return {"namespaces": {}, "templates_root": str(_TEMPLATES_ROOT)}

    namespaces: dict[str, list[str]] = {}
    for ns_dir in sorted(_TEMPLATES_ROOT.iterdir()):
        if not ns_dir.is_dir():
            continue
        if namespace is not None and ns_dir.name != namespace:
            continue
        ids = sorted(p.stem for p in ns_dir.glob("*.md") if p.is_file())
        namespaces[ns_dir.name] = ids
    return {"namespaces": namespaces, "templates_root": str(_TEMPLATES_ROOT)}
