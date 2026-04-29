#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
render_mermaid.py — Render Mermaid diagram source code to PNG files.

Input: JSON with `diagrams` block, e.g.:
  {
    "diagrams": {
      "component":    "graph TB\\n  api[API] --> db[(Postgres)]",
      "erd":          "erDiagram\\n  USER ||--o{ ORDER : places",
      "deployment":   "graph LR\\n  ...",
      "sequence":     "sequenceDiagram\\n  ...",
      "integration":  "graph LR\\n  ..."
    }
  }

Output: PNG files in --output-dir, plus updated JSON with diagram_*_path fields
pointing to rendered PNGs (for docxtpl InlineImage resolution).

Dependencies: npx + @mermaid-js/mermaid-cli (invoked via subprocess).
Fallback: if mmdc unavailable, emit diagrams as .txt code blocks + warning.

Usage:
  python render_mermaid.py \\
    --data       content-data.json \\
    --output-dir {docs-path}/diagrams \\
    --report     mermaid-report.json
"""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def check_mmdc() -> str | None:
    """Return path to mmdc invoker if available, else None."""
    # Prefer local npx invocation
    for cmd in ("mmdc", "npx"):
        if shutil.which(cmd):
            return cmd
    return None


def render_one(mmdc_cmd: str, source: str, out_png: Path, theme: str = "default") -> tuple[bool, str]:
    """Render Mermaid source → PNG. Returns (success, error_msg)."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False, encoding="utf-8") as tmp:
        tmp.write(source)
        tmp_path = tmp.name

    # Puppeteer config — Chromium in Docker (non-root) needs --no-sandbox.
    puppeteer_cfg_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as cfg:
            cfg.write('{"args":["--no-sandbox","--disable-setuid-sandbox"]}')
            puppeteer_cfg_path = cfg.name
    except OSError:
        pass

    try:
        base_args = ["-i", tmp_path, "-o", str(out_png),
                     "-t", theme, "-b", "white", "-w", "1400"]
        if puppeteer_cfg_path:
            base_args += ["-p", puppeteer_cfg_path]
        if mmdc_cmd == "npx":
            cmd = ["npx", "-y", "@mermaid-js/mermaid-cli"] + base_args
        else:
            cmd = [mmdc_cmd] + base_args
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60,
                                shell=(sys.platform == "win32"))
        if result.returncode == 0 and out_png.exists():
            return True, ""
        return False, result.stderr[:500] or result.stdout[:500]
    except subprocess.TimeoutExpired:
        return False, "Timeout 60s"
    except Exception as e:
        return False, str(e)
    finally:
        try:
            Path(tmp_path).unlink()
        except OSError:
            pass
        if puppeteer_cfg_path:
            try:
                Path(puppeteer_cfg_path).unlink()
            except OSError:
                pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True, help="content-data.json path")
    ap.add_argument("--output-dir", required=True, help="Directory to write PNG files")
    ap.add_argument("--report", required=True, help="Report JSON path")
    ap.add_argument("--theme", default="default", choices=["default", "neutral", "dark", "forest"])
    args = ap.parse_args()

    data_path = Path(args.data)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    data = json.loads(data_path.read_text(encoding="utf-8"))
    diagrams = data.get("diagrams", {})

    report = {"status": "ok", "rendered": [], "failed": [], "warnings": []}

    if not diagrams:
        report["warnings"].append("No 'diagrams' block in content-data.json")
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print("No diagrams to render")
        return

    mmdc = check_mmdc()
    if mmdc is None:
        report["status"] = "degraded"
        report["warnings"].append("Mermaid CLI (mmdc/npx) not found — diagrams skipped")
        for key in diagrams:
            # Emit .mmd source file as fallback artifact
            mmd_path = out_dir / f"{key}.mmd"
            mmd_path.write_text(diagrams[key], encoding="utf-8")
            report["failed"].append({"key": key, "reason": "no-mmdc", "mmd": str(mmd_path)})
        Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"DEGRADED: mmdc not found. Wrote {len(diagrams)} .mmd sources to {out_dir}")
        return

    # Render each diagram
    for key, source in diagrams.items():
        if not source or not isinstance(source, str) or not source.strip():
            report["warnings"].append(f"Empty diagram source: {key}")
            continue
        out_png = out_dir / f"{key}.png"
        ok, err = render_one(mmdc, source, out_png)
        if ok:
            report["rendered"].append({"key": key, "path": str(out_png),
                                        "size_kb": out_png.stat().st_size // 1024})
            print(f"  OK: {key} → {out_png.name}")
        else:
            report["failed"].append({"key": key, "error": err})
            # Save source for debugging
            (out_dir / f"{key}.mmd").write_text(source, encoding="utf-8")
            print(f"  FAIL: {key} — {err[:100]}")

    if report["failed"]:
        report["status"] = "partial"

    Path(args.report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRendered: {len(report['rendered'])}/{len(diagrams)} diagrams")


if __name__ == "__main__":
    main()
