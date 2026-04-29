#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
process_screenshots.py — Resize + compress screenshots + verify integrity.

Runs AFTER tdoc-test-runner completes. Transforms raw Playwright PNG outputs
into docx-embed-friendly files:

  - resize to max_width_px (preserve aspect ratio, no upscale)
  - convert large PNGs to JPEG (config threshold) with quality setting
  - PNG optimize for smaller (lossless) files
  - verify each file is a valid image (not blank/corrupt)
  - emit postprocess-report.json with per-file stats

Usage:
  python process_screenshots.py \
    --screenshots-dir {docs-path}/screenshots \
    --config {skill-dir}/engine/schemas/capture-profiles.yaml \
    --report {docs-path}/intel/postprocess-report.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
except ImportError:
    print("ERROR: PyYAML required", file=sys.stderr)
    sys.exit(2)

try:
    from PIL import Image, ImageStat
except ImportError:
    print("ERROR: Pillow required. Run: pip install Pillow", file=sys.stderr)
    sys.exit(2)


@dataclass
class FileReport:
    file: str
    original_kb: int
    final_kb: int
    original_size: tuple[int, int]
    final_size: tuple[int, int]
    format: str
    resized: bool = False
    converted_to_jpeg: bool = False
    png_optimized: bool = False
    is_blank: bool = False
    is_broken: bool = False
    warning: str = ""


@dataclass
class RunReport:
    total_files: int = 0
    processed: int = 0
    skipped: int = 0
    blank_detected: int = 0
    broken_detected: int = 0
    bytes_saved: int = 0
    files: list[FileReport] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "total_files": self.total_files,
            "processed": self.processed,
            "skipped": self.skipped,
            "blank_detected": self.blank_detected,
            "broken_detected": self.broken_detected,
            "bytes_saved_kb": self.bytes_saved // 1024,
            "files": [f.__dict__ for f in self.files],
        }


def is_blank_image(img: Image.Image, tolerance: float = 2.0) -> bool:
    """Detect effectively blank images — low stddev across all channels.

    Playwright can emit blank white/black frames when captured mid-transition.
    """
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    return stat.stddev[0] < tolerance


def process_one(path: Path, config: dict) -> FileReport:
    pp = config.get("postprocess", {})
    max_w = pp.get("resize_max_width_px", 1400)
    threshold_kb = pp.get("compress_threshold_kb", 150)
    jpeg_quality = pp.get("jpeg_quality", 85)
    png_optimize = pp.get("png_optimize", True)

    original_kb = path.stat().st_size // 1024

    try:
        img = Image.open(path)
        img.load()
    except Exception as e:
        return FileReport(
            file=path.name, original_kb=original_kb, final_kb=original_kb,
            original_size=(0, 0), final_size=(0, 0), format="unknown",
            is_broken=True, warning=f"Open failed: {e}",
        )

    original_size = img.size
    rep = FileReport(
        file=path.name, original_kb=original_kb, final_kb=original_kb,
        original_size=original_size, final_size=original_size,
        format=img.format or "unknown",
    )

    # Blank detection
    if is_blank_image(img):
        rep.is_blank = True
        rep.warning = "Blank/low-contrast image detected (stddev < 2.0)"
        # Don't process further — leave original for vision reviewer to flag

    # Resize if exceeds max width
    w, h = img.size
    if w > max_w:
        new_h = int(h * (max_w / w))
        img = img.resize((max_w, new_h), Image.LANCZOS)
        rep.resized = True
        rep.final_size = img.size

    # Decide format
    final_path = path
    if original_kb > threshold_kb and img.format != "JPEG":
        # Convert to JPEG (lossy but significantly smaller for screenshots)
        # Change extension
        final_path = path.with_suffix(".jpg")
        # JPEG cannot have alpha — paste onto white background
        if img.mode in ("RGBA", "LA"):
            bg = Image.new("RGB", img.size, (255, 255, 255))
            bg.paste(img, mask=img.split()[-1])
            img = bg
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(final_path, "JPEG", quality=jpeg_quality, optimize=True, progressive=True)
        rep.converted_to_jpeg = True
        rep.format = "JPEG"
        # Remove original PNG to avoid duplicate
        if final_path != path:
            path.unlink(missing_ok=True)
    else:
        # Save PNG with optimization
        if png_optimize and img.format == "PNG":
            img.save(path, "PNG", optimize=True)
            rep.png_optimized = True
        elif rep.resized:
            # resized but not compressed — save back at current extension
            img.save(path, img.format)

    rep.final_kb = final_path.stat().st_size // 1024
    rep.file = final_path.name  # reflect new extension if converted
    return rep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--screenshots-dir", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--pattern", default="*.png",
                    help="Glob pattern, default *.png (JPEGs from prior run also picked up via *.jpg)")
    args = ap.parse_args()

    sc_dir = Path(args.screenshots_dir)
    if not sc_dir.is_dir():
        print(f"ERROR: screenshots dir not found: {sc_dir}", file=sys.stderr)
        sys.exit(1)

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if not config.get("postprocess", {}).get("enabled", True):
        print("Postprocess disabled in config — skipping")
        return

    report = RunReport()
    files = list(sc_dir.glob(args.pattern)) + list(sc_dir.glob("*.jpg"))
    files = sorted(set(files))
    report.total_files = len(files)

    for f in files:
        fr = process_one(f, config)
        report.files.append(fr)
        if fr.is_broken:
            report.broken_detected += 1
            continue
        if fr.is_blank:
            report.blank_detected += 1
        report.processed += 1
        report.bytes_saved += (fr.original_kb - fr.final_kb) * 1024

    d = report.to_dict()
    print(f"Processed: {report.processed}/{report.total_files}")
    print(f"Blank detected: {report.blank_detected}")
    print(f"Broken detected: {report.broken_detected}")
    print(f"Bytes saved: {d['bytes_saved_kb']} KB")

    if args.report:
        Path(args.report).parent.mkdir(parents=True, exist_ok=True)
        Path(args.report).write_text(
            json.dumps(d, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
