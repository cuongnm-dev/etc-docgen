"""template_registry — consolidated list+load tool for scaffold templates.

Per p0 §3.11 + ADR-003 D11. Replaces 2 separate tools with single one
using ``action`` discriminator.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from etc_platform.sdlc.errors import (
    InvalidInputError,
    TemplateNotFoundError,
    success_response,
)
from etc_platform.sdlc.templates import list_templates, scaffolds_dir

_VALID_ACTIONS = ("list", "load")


def template_registry_impl(
    namespace: str,
    action: str,
    template_id: str | None = None,
) -> dict[str, Any]:
    """List or load templates from MCP image's assets/scaffolds/{namespace}/.

    Args:
        namespace: subdir of scaffolds, e.g. 'module', 'feature', 'hotfix', 'intel'.
        action: 'list' returns metadata for all templates in namespace;
                'load' returns single template content + sha256.
        template_id: required for action='load'; relative path under namespace
                     (e.g. '_state.md.j2' OR 'subdir/file.j2').

    Returns:
        Per p0 §3.11 spec.
    """
    if action not in _VALID_ACTIONS:
        raise InvalidInputError(
            f"Invalid action: {action!r} (expected list or load)",
            details={"action": action, "valid": list(_VALID_ACTIONS)},
        )

    if not namespace or not namespace.replace("-", "").replace("_", "").isalnum():
        raise InvalidInputError(
            f"Invalid namespace: {namespace!r}",
            details={"namespace": namespace},
        )

    if action == "list":
        return _list(namespace)

    # action == 'load'
    if not template_id:
        raise InvalidInputError(
            "action=load requires template_id",
            details={"missing": ["template_id"]},
        )
    return _load(namespace, template_id)


def _list(namespace: str) -> dict[str, Any]:
    templates = list_templates(namespace)
    return success_response(
        {
            "namespace": namespace,
            "templates": templates,
            "count": len(templates),
        }
    )


def _load(namespace: str, template_id: str) -> dict[str, Any]:
    # Sanitize template_id (no path traversal)
    if ".." in template_id or template_id.startswith("/") or template_id.startswith("\\"):
        raise InvalidInputError(
            f"Invalid template_id: {template_id!r} (path traversal not allowed)",
            details={"template_id": template_id},
        )

    target = scaffolds_dir() / namespace / template_id
    # Ensure target is within namespace dir
    try:
        target.resolve().relative_to((scaffolds_dir() / namespace).resolve())
    except ValueError as exc:
        raise InvalidInputError(
            f"Template path escapes namespace: {template_id}",
            details={"namespace": namespace, "template_id": template_id},
        ) from exc

    if not target.exists():
        raise TemplateNotFoundError(
            f"Template not found: {namespace}/{template_id}",
            details={"namespace": namespace, "template_id": template_id},
        )

    content = target.read_text(encoding="utf-8")
    sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

    return success_response(
        {
            "namespace": namespace,
            "template_id": template_id,
            "content": content,
            "sha256": f"sha256:{sha256}",
            "type": "jinja2",
            "size": len(content),
        }
    )
