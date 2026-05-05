"""YAML frontmatter parse/serialize for Markdown files.

Used by update_state_impl + verify(schemas) for `_state.md`/`_feature.md`
modifications. Preserves body text verbatim; only frontmatter mutated.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from etc_platform.sdlc.concurrency import atomic_write_text

_DELIM = "---\n"


def read_frontmatter(path: Path) -> tuple[dict[str, Any], str]:
    """Parse Markdown file with leading YAML frontmatter.

    Returns:
        (frontmatter_dict, body_text). If no frontmatter, returns ({}, full_text).
    """
    text = path.read_text(encoding="utf-8")
    return _parse(text)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Same as read_frontmatter but accepts string input."""
    return _parse(text)


def write_frontmatter(path: Path, frontmatter: dict[str, Any], body: str) -> None:
    """Atomic write Markdown file with frontmatter + body."""
    content = serialize(frontmatter, body)
    atomic_write_text(path, content)


def serialize(frontmatter: dict[str, Any], body: str) -> str:
    """Serialize frontmatter + body to Markdown text."""
    fm_yaml = yaml.safe_dump(
        frontmatter,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )
    if not body.startswith("\n") and body:
        body = "\n" + body
    return f"---\n{fm_yaml}---{body}"


def set_dotpath(data: dict[str, Any], dotpath: str, value: Any) -> tuple[Any, Any]:
    """Set data.a.b.c = value via dot-path. Returns (old_value, new_value).

    Creates intermediate dicts if missing. Caller responsible for
    locked_fields enforcement before calling.
    """
    parts = dotpath.split(".")
    target = data
    for p in parts[:-1]:
        if p not in target or not isinstance(target[p], dict):
            target[p] = {}
        target = target[p]
    last = parts[-1]
    old = target.get(last)
    target[last] = value
    return (old, value)


def get_dotpath(data: dict[str, Any], dotpath: str, default: Any = None) -> Any:
    """Read data.a.b.c via dot-path, returning default if missing."""
    parts = dotpath.split(".")
    target: Any = data
    for p in parts:
        if not isinstance(target, dict) or p not in target:
            return default
        target = target[p]
    return target


def _parse(text: str) -> tuple[dict[str, Any], str]:
    """Internal frontmatter parser."""
    if not text.startswith("---"):
        return ({}, text)
    # Find closing delimiter
    rest = text[4:] if text.startswith("---\n") else text[3:]
    end_idx = rest.find("\n---\n")
    if end_idx == -1:
        # Try CRLF or end-of-file delimiter
        end_idx = rest.find("\n---\r\n")
        if end_idx == -1:
            return ({}, text)
    fm_yaml = rest[:end_idx]
    body = rest[end_idx + 5:]  # skip past \n---\n
    try:
        fm = yaml.safe_load(fm_yaml) or {}
    except yaml.YAMLError:
        return ({}, text)
    if not isinstance(fm, dict):
        return ({}, text)
    return (fm, body)
