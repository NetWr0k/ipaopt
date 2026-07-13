"""
Operates on .xcassets *source* folders (as found in an app's Xcode project,
not inside a built IPA). Each image set / app icon set / etc. has a
Contents.json describing its "images" array, where each entry may carry:

    "idiom": "universal" | "iphone" | "ipad" | "mac" | "tv" | "watch" | "car"
    "scale": "1x" | "2x" | "3x"
    "appearances": [{"appearance": "luminosity", "value": "dark"}]
                    [{"appearance": "contrast", "value": "high"}]

This module copies the catalog, deletes the on-disk image files for entries
that match the removal rules, rewrites Contents.json to drop those entries,
and (optionally, on macOS with Xcode installed) recompiles the filtered
catalog into a new Assets.car via `actool`.
"""

from __future__ import annotations

import json
import plistlib
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .rules import FilterRules


@dataclass
class CatalogFilterStats:
    imagesets_scanned: int = 0
    entries_removed: int = 0
    files_removed: int = 0
    bytes_freed: int = 0


def _entry_matches_removal(entry: dict, rules: FilterRules) -> bool:
    idiom = entry.get("idiom")
    scale = entry.get("scale")
    if rules.should_drop_idiom(idiom):
        return True
    if rules.should_drop_scale(scale):
        return True
    for appearance in entry.get("appearances", []) or []:
        value = appearance.get("value")
        if rules.should_drop_appearance(value):
            return True
    return False


def filter_xcassets(src: Path, dest: Path, rules: FilterRules, dry_run: bool = False) -> CatalogFilterStats:
    """Copy src .xcassets to dest, dropping entries per rules. Returns stats."""
    if dest.exists():
        if dry_run:
            pass
        else:
            shutil.rmtree(dest)
    if not dry_run:
        shutil.copytree(src, dest)
    else:
        dest = src  # read-only inspection pass

    stats = CatalogFilterStats()

    for contents_json in dest.rglob("Contents.json"):
        parent = contents_json.parent
        if parent.suffix not in {".imageset", ".appiconset", ".imagestack", ".stickersequence"}:
            continue
        stats.imagesets_scanned += 1

        try:
            data = json.loads(contents_json.read_text())
        except (json.JSONDecodeError, OSError):
            continue

        images = data.get("images")
        if not isinstance(images, list):
            continue

        kept = []
        for entry in images:
            if _entry_matches_removal(entry, rules):
                stats.entries_removed += 1
                filename = entry.get("filename")
                if filename:
                    file_path = parent / filename
                    if file_path.is_file():
                        size = file_path.stat().st_size
                        stats.bytes_freed += size
                        stats.files_removed += 1
                        if not dry_run:
                            file_path.unlink()
            else:
                kept.append(entry)

        if not dry_run and len(kept) != len(images):
            data["images"] = kept
            contents_json.write_text(json.dumps(data, indent=2))

    return stats


def compile_car(xcassets_dir: Path, output_dir: Path, platform: str = "iphoneos",
                 deployment_target: str = "13.0", app_icon_name: str | None = None) -> Path:
    """Recompile a filtered .xcassets folder into Assets.car via actool.

    Requires macOS + Xcode command line tools. Returns the path to the
    generated Assets.car.
    """
    actool = shutil.which("actool")
    if not actool:
        raise RuntimeError(
            "`actool` not found. Recompiling Assets.car requires macOS with "
            "Xcode installed (actool ships as part of Xcode, not the "
            "standalone command line tools package in all cases -- run "
            "`xcode-select -p` to confirm your active developer directory)."
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    plist_out = output_dir / "actool_output.plist"

    cmd = [
        actool,
        "--output-format", "human-readable-text",
        "--notices",
        "--warnings",
        "--platform", platform,
        "--minimum-deployment-target", deployment_target,
        "--compress-pngs",
        "--compile", str(output_dir),
    ]
    if app_icon_name:
        cmd += ["--app-icon", app_icon_name]
    cmd += [str(xcassets_dir)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"actool failed:\n{result.stdout}\n{result.stderr}")

    car_path = output_dir / "Assets.car"
    if not car_path.is_file():
        raise RuntimeError(
            f"actool reported success but no Assets.car was produced in {output_dir}"
        )
    return car_path
