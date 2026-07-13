"""
Many apps (especially ones using older asset pipelines, CocoaPods resource
bundles, or hand-copied images) ship loose PNG/JPG/PDF resources directly in
the .app bundle rather than inside a compiled Assets.car. Apple's naming
convention encodes idiom and scale directly in the filename:

    Icon.png            -> universal, 1x
    Icon@2x.png          -> universal, 2x
    Icon@3x.png          -> universal, 3x
    Icon~ipad.png        -> ipad idiom, 1x
    Icon@2x~ipad.png      -> ipad idiom, 2x
    Icon~iphone.png       -> iphone idiom, 1x

This module finds and (optionally) deletes such files that match rules the
caller doesn't want to keep. It does not touch files inside .car archives or
.xcassets source folders (see catalog_filter.py for that).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .rules import FilterRules

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".pdf", ".tiff", ".gif"}

# Matches: name[@2x][~idiom].ext  (idiom and scale both optional, any order
# is not actually valid Apple convention -- scale always precedes idiom --
# but we accept both to be permissive.)
_PATTERN = re.compile(
    r"^(?P<base>.+?)"
    r"(?:@(?P<scale>[123]x))?"
    r"(?:~(?P<idiom>[a-zA-Z]+))?"
    r"(?P<ext>\.[A-Za-z0-9]+)$"
)

_IDIOM_ALIASES = {
    "ipad": "ipad",
    "iphone": "iphone",
    "marketing": "watch-marketing",
    "tv": "tv",
    "watch": "watch",
}


@dataclass
class MatchInfo:
    path: Path
    base_name: str
    scale: str | None
    idiom: str | None


def parse_filename(path: Path) -> MatchInfo | None:
    if path.suffix.lower() not in IMAGE_EXTS:
        return None
    m = _PATTERN.match(path.name)
    if not m:
        return None
    scale = m.group("scale")
    idiom_raw = m.group("idiom")
    idiom = _IDIOM_ALIASES.get(idiom_raw.lower()) if idiom_raw else None
    scale_str = f"{scale}" if scale else "1x"
    return MatchInfo(path=path, base_name=m.group("base"), scale=scale_str, idiom=idiom)


def find_loose_assets(app_dir: Path) -> list[MatchInfo]:
    results = []
    for path in app_dir.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        # Skip anything inside a compiled catalog or xcassets source.
        if ".car" in {p.suffix for p in path.parents} or "xcassets" in str(path):
            continue
        info = parse_filename(path)
        if info:
            results.append(info)
    return results


def plan_removals(app_dir: Path, rules: FilterRules) -> list[MatchInfo]:
    """Return the list of loose-asset files that should be removed."""
    to_remove = []
    for info in find_loose_assets(app_dir):
        if rules.should_drop_idiom(info.idiom) or rules.should_drop_scale(info.scale):
            to_remove.append(info)
    return to_remove


def apply_removals(matches: list[MatchInfo], dry_run: bool = False) -> int:
    """Delete the given files; returns total bytes freed."""
    freed = 0
    for m in matches:
        try:
            freed += m.path.stat().st_size
        except OSError:
            continue
        if not dry_run:
            m.path.unlink(missing_ok=True)
    return freed
