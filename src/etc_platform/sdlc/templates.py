"""Jinja2 template rendering helper for SDLC scaffolding tools.

Templates baked into MCP image at ``assets/scaffolds/{namespace}/``.
This helper loads + renders them with caller-provided context.

Caller passes a context dict; renderer expands ``{{ variable }}`` and
``{% block %}`` tags. ``tojson`` filter included for safe JSON embedding.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, Template

from etc_platform.paths import assets_dir
from etc_platform.sdlc.errors import TemplateNotFoundError


def scaffolds_dir() -> Path:
    """Root for Jinja2 scaffold templates."""
    return assets_dir() / "scaffolds"


@lru_cache(maxsize=1)
def _env() -> Environment:
    """Cached Jinja2 environment (loads once per server lifetime)."""
    env = Environment(
        loader=FileSystemLoader(str(scaffolds_dir())),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    # tojson filter: safe JSON embedding (handles strings, lists, dicts)
    env.filters["tojson"] = lambda obj: json.dumps(obj, ensure_ascii=False)
    return env


def render_template(template_path: str, context: dict[str, Any]) -> str:
    """Render template at ``namespace/filename.j2`` with context.

    Args:
        template_path: Relative to scaffolds_dir(), e.g. "module/_state.md.j2"
        context: Variable bindings.

    Raises:
        TemplateNotFoundError: template missing in image.
    """
    try:
        tmpl: Template = _env().get_template(template_path)
    except Exception as exc:
        raise TemplateNotFoundError(
            f"Template not found: {template_path}",
            details={"template_path": template_path, "scaffolds_dir": str(scaffolds_dir())},
        ) from exc
    return tmpl.render(**context)


def list_templates(namespace: str) -> list[dict[str, Any]]:
    """List all templates under ``scaffolds/{namespace}/`` with metadata."""
    ns_dir = scaffolds_dir() / namespace
    if not ns_dir.exists():
        return []

    out: list[dict[str, Any]] = []
    for p in sorted(ns_dir.rglob("*.j2")):
        rel = p.relative_to(scaffolds_dir())
        stat = p.stat()
        out.append(
            {
                "id": str(rel).replace("\\", "/"),
                "type": "jinja2",
                "size": stat.st_size,
                "last_updated": datetime.fromtimestamp(stat.st_mtime, tz=UTC).isoformat(),
            }
        )
    return out


def utc_iso_now() -> str:
    """Convenience timestamp for template contexts."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
