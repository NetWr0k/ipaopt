"""
Assets.car is a compiled, binary CoreUI archive. There is no supported way to
selectively delete entries from it in place -- Apple's tooling only supports
rebuilding it wholesale from .xcassets source via `actool` (see
catalog_filter.py). What we *can* do without the source is inspect it, using
the private-but-widely-used `assetutil -I` tool that ships with Xcode, and
report which idioms/scales/appearances are present so you know what a
rebuild-from-source pass would remove.

`assetutil` is macOS-only (part of Xcode's CoreUI framework tooling).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path


class AssetutilUnavailable(RuntimeError):
    pass


def find_car_files(app_dir: Path) -> list[Path]:
    return list(app_dir.rglob("*.car"))


def inspect_car(car_path: Path) -> list[dict]:
    assetutil = shutil.which("assetutil")
    if not assetutil:
        raise AssetutilUnavailable(
            "`assetutil` not found. It ships with Xcode command line tools "
            "on macOS (part of CoreUI) and has no equivalent elsewhere, so "
            "compiled Assets.car files can only be reported on, on macOS."
        )
    result = subprocess.run(
        [assetutil, "-I", str(car_path)], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"assetutil failed on {car_path}: {result.stderr.strip()}")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Could not parse assetutil output for {car_path}: {e}")
    # First entry is usually catalog-level metadata, not an asset -- keep
    # only dict entries that describe individual assets (they have a Name).
    return [entry for entry in data if isinstance(entry, dict) and "AssetType" in entry]


def summarize_car(entries: list[dict]) -> dict:
    idioms = Counter(e.get("Idiom", "unknown") for e in entries)
    scales = Counter(str(e.get("Scale", "unknown")) for e in entries)
    appearances = Counter()
    for e in entries:
        for a in e.get("Appearances", []) or []:
            appearances[a.get("Value", "unknown")] += 1
    if not appearances:
        appearances["none"] = len(entries)
    return {
        "total_assets": len(entries),
        "by_idiom": dict(idioms),
        "by_scale": dict(scales),
        "by_appearance": dict(appearances),
    }


def report_car_files(app_dir: Path) -> dict:
    """Returns {car_path_str: summary_dict_or_error_str}."""
    out = {}
    for car in find_car_files(app_dir):
        try:
            entries = inspect_car(car)
            out[str(car)] = summarize_car(entries)
        except (AssetutilUnavailable, RuntimeError) as e:
            out[str(car)] = {"error": str(e)}
    return out
