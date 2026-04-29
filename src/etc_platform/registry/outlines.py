"""Outline registry tools for etc-platform MCP server.

Stores immutable VN administrative-document outlines (TKCS, TKCT, dự toán,
HSMT, HSDT, NCKT, thuyết minh, báo cáo chủ trương). Per CLAUDE.md G1, outlines
are BẤT BIẾN — content never mutates after publish; new legal bases get a new
version filename.

Layout
------
``$ETC_PLATFORM_DATA_DIR/outlines/{doc_type}/{version}.md``

``doc_type`` is the canonical document slug (e.g. ``tkcs``, ``hsmt``).
``version`` encodes legal basis (``nd73-2019``, ``tt04-2020``, ``ldt2023``)
or ``v1`` when no legal-version qualifier applies.

When ``version="latest"`` is requested, the most recent outline is selected
by lexicographic sort of basenames (consumers should pin explicit versions
in production).
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any

_DATA_DIR: Path = Path(
    os.environ.get("ETC_PLATFORM_DATA_DIR")
    or os.environ.get("ETC_DOCGEN_DATA_DIR")  # back-compat
    or "/data"
)
_OUTLINES_ROOT: Path = _DATA_DIR / "outlines"


def _safe_join(doc_type: str, leaf: str) -> Path:
    """Resolve ``doc_type/leaf`` under outlines root, blocking traversal."""
    if ".." in doc_type.split("/") or ".." in leaf.split("/"):
        raise ValueError("Path traversal not allowed")
    candidate = (_OUTLINES_ROOT / doc_type / leaf).resolve()
    root = _OUTLINES_ROOT.resolve()
    if root not in candidate.parents and candidate != root:
        raise ValueError("Resolved outline path escapes outlines root")
    return candidate


def _list_versions(doc_type: str) -> list[str]:
    """Return sorted list of available version strings for a doc_type."""
    dir_path = _safe_join(doc_type, "")
    if not dir_path.is_dir():
        return []
    return sorted(p.stem for p in dir_path.glob("*.md") if p.is_file())


def outline_load_impl(doc_type: str, version: str = "latest") -> dict[str, Any]:
    """Load outline content for ``doc_type`` at ``version``.

    Parameters
    ----------
    doc_type
        Canonical slug: ``tkcs``, ``tkct``, ``du-toan``, ``hsmt``, ``hsdt``,
        ``nghien-cuu-kha-thi``, ``thuyet-minh``, ``bao-cao-chu-truong``.
    version
        Either a specific version (``nd73-2019``, ``tt04-2020``, ``v1``)
        or ``"latest"`` (selects most recent by lexicographic sort).

    Returns
    -------
    dict
        ``content`` (str), ``sha256`` (str), ``size_bytes`` (int),
        ``doc_type`` (str), ``version_used`` (str — explicit version
        actually loaded; differs from request when ``"latest"``),
        ``available_versions`` (list[str]).
    """
    versions = _list_versions(doc_type)
    if not versions:
        raise FileNotFoundError(
            f"No outlines registered for doc_type={doc_type!r}. "
            f"Use outlines_list() to discover available types."
        )

    if version == "latest":
        version_used = versions[-1]
    elif version in versions:
        version_used = version
    else:
        raise FileNotFoundError(
            f"Outline {doc_type}/{version}.md not found. "
            f"Available versions: {versions}"
        )

    path = _safe_join(doc_type, f"{version_used}.md")
    content = path.read_text(encoding="utf-8")
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return {
        "doc_type": doc_type,
        "version_used": version_used,
        "available_versions": versions,
        "content": content,
        "size_bytes": len(content.encode("utf-8")),
        "sha256": digest,
    }


def outlines_list_impl() -> dict[str, Any]:
    """Return mapping of ``doc_type`` -> list of available versions."""
    if not _OUTLINES_ROOT.is_dir():
        return {"doc_types": {}, "outlines_root": str(_OUTLINES_ROOT)}

    doc_types: dict[str, list[str]] = {}
    for type_dir in sorted(_OUTLINES_ROOT.iterdir()):
        if not type_dir.is_dir():
            continue
        versions = sorted(p.stem for p in type_dir.glob("*.md") if p.is_file())
        if versions:
            doc_types[type_dir.name] = versions
    return {"doc_types": doc_types, "outlines_root": str(_OUTLINES_ROOT)}
