"""Resolve bundled asset paths (templates, schemas) relative to package."""
from __future__ import annotations

from importlib import resources
from pathlib import Path


def assets_dir() -> Path:
    """Return path to bundled assets/ directory (templates + schemas)."""
    # Use importlib.resources for PEP 302 compliance
    with resources.as_file(resources.files("etc_platform") / "assets") as p:
        return Path(p)


def templates_dir() -> Path:
    """Bundled ETC templates (docx, xlsx)."""
    return assets_dir() / "templates"


def schemas_dir() -> Path:
    """Bundled YAML schemas (xlsx schema, capture profiles)."""
    return assets_dir() / "schemas"


def template(name: str) -> Path:
    """Resolve a bundled template by filename.

    Example: template("huong-dan-su-dung.docx")
    """
    path = templates_dir() / name
    if not path.exists():
        raise FileNotFoundError(
            f"Bundled template not found: {name}\n"
            f"Available: {[p.name for p in templates_dir().glob('*')]}"
        )
    return path


def schema(name: str) -> Path:
    """Resolve a bundled schema by filename.

    Example: schema("test-case.xlsx.schema.yaml")
    """
    path = schemas_dir() / name
    if not path.exists():
        raise FileNotFoundError(
            f"Bundled schema not found: {name}\n"
            f"Available: {[p.name for p in schemas_dir().glob('*')]}"
        )
    return path
