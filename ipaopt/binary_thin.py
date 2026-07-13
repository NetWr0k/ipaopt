"""
Strips unused CPU architecture slices from Mach-O binaries (the main
executable, embedded frameworks, plugins/appex, and Swift dylibs) using the
system `lipo` tool. This is the "architectures" half of the optimizer.

Requires macOS with Xcode command line tools (`lipo`, `file`). On other
platforms this module degrades to a reporting-only mode: it will tell you
what it *would* do but cannot perform the thinning, since `lipo` has no
portable equivalent.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


MACHO_MAGICS = {
    b"\xfe\xed\xfa\xce",  # MH_MAGIC (32-bit BE)
    b"\xce\xfa\xed\xfe",  # MH_CIGAM (32-bit LE)
    b"\xfe\xed\xfa\xcf",  # MH_MAGIC_64 (BE)
    b"\xcf\xfa\xed\xfe",  # MH_MAGIC_64 (LE)
    b"\xca\xfe\xba\xbe",  # FAT_MAGIC (BE) - universal binary
    b"\xbe\xba\xfe\xca",  # FAT_CIGAM (LE)
}


@dataclass
class ThinResult:
    path: Path
    before_archs: list
    after_archs: list
    bytes_before: int
    bytes_after: int
    skipped_reason: str | None = None


def _is_macho(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        return head in MACHO_MAGICS
    except OSError:
        return False


def find_macho_binaries(app_dir: Path) -> list[Path]:
    """Find likely Mach-O binaries: main executable, frameworks, plugins."""
    candidates: list[Path] = []
    for pattern in (
        "**/*.framework/*",
        "**/*.dylib",
        "**/PlugIns/**/*",
        "**/Frameworks/**/*",
        "**/*.appex/*",
    ):
        for p in app_dir.glob(pattern):
            if p.is_file() and not p.is_symlink():
                candidates.append(p)

    # The main executable: same name as the .app, no extension, at bundle root.
    exe_name = app_dir.stem
    main_exe = app_dir / exe_name
    if main_exe.is_file():
        candidates.append(main_exe)

    # De-dupe, keep only real Mach-O files.
    seen = set()
    result = []
    for c in candidates:
        rc = c.resolve()
        if rc in seen:
            continue
        seen.add(rc)
        if _is_macho(c):
            result.append(c)
    return result


def lipo_archs(path: Path) -> list[str]:
    lipo = shutil.which("lipo")
    if not lipo:
        raise RuntimeError("`lipo` not found (requires macOS + Xcode command line tools)")
    result = subprocess.run([lipo, "-info", str(path)], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"lipo -info failed for {path}: {result.stderr.strip()}")
    out = result.stdout.strip()
    # Two possible formats:
    #   "Non-fat file: X is architecture: arm64"
    #   "Architectures in the fat file: X are: arm64 x86_64"
    if "Non-fat file" in out:
        return [out.rsplit(":", 1)[-1].strip()]
    if "are:" in out:
        return out.split("are:", 1)[-1].strip().split()
    return []


def thin_binary(path: Path, keep_archs: set, dry_run: bool = False) -> ThinResult:
    before = lipo_archs(path)
    size_before = path.stat().st_size

    archs_to_keep = [a for a in before if a in keep_archs]
    if len(before) <= 1:
        return ThinResult(path, before, before, size_before, size_before,
                           skipped_reason="already single-architecture")
    if not archs_to_keep:
        return ThinResult(path, before, before, size_before, size_before,
                           skipped_reason=f"none of {sorted(keep_archs)} present, leaving untouched")
    if set(archs_to_keep) == set(before):
        return ThinResult(path, before, before, size_before, size_before,
                           skipped_reason="no removable architectures")

    if dry_run:
        return ThinResult(path, before, archs_to_keep, size_before, size_before)

    lipo = shutil.which("lipo")
    if not lipo:
        raise RuntimeError("`lipo` not found (requires macOS + Xcode command line tools)")

    tmp_out = path.with_suffix(path.suffix + ".thin.tmp")
    cmd = [lipo, str(path)]
    for arch in archs_to_keep:
        cmd += ["-extract", arch]
    cmd += ["-output", str(tmp_out)]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        # Fall back to -thin when only one arch is being kept (some lipo
        # versions prefer -thin for single-arch extraction).
        if len(archs_to_keep) == 1:
            cmd = [lipo, str(path), "-thin", archs_to_keep[0], "-output", str(tmp_out)]
            result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"lipo extraction failed for {path}: {result.stderr.strip()}")

    tmp_out.replace(path)
    size_after = path.stat().st_size
    after = lipo_archs(path)
    return ThinResult(path, before, after, size_before, size_after)


def thin_app(app_dir: Path, keep_archs: set, dry_run: bool = False) -> list[ThinResult]:
    results = []
    for binary in find_macho_binaries(app_dir):
        try:
            results.append(thin_binary(binary, keep_archs, dry_run=dry_run))
        except RuntimeError as e:
            results.append(ThinResult(binary, [], [], binary.stat().st_size,
                                       binary.stat().st_size, skipped_reason=str(e)))
    return results
