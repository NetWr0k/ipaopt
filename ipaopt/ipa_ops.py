"""
IPA is just a zip archive with a top-level "Payload/" directory containing a
single "*.app" bundle (plus optional Symbols/, SwiftSupport/, etc). These
helpers extract and repackage that structure while preserving symlinks and
executable permissions, which Python's zipfile module does not do reliably
for macOS app bundles (frameworks commonly contain symlinks under
Versions/Current). We shell out to the system `zip`/`unzip` (or `ditto` on
macOS) for that reason.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


class IPAError(RuntimeError):
    pass


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if result.returncode != 0:
        raise IPAError(
            f"Command failed ({' '.join(cmd)}):\n{result.stdout}\n{result.stderr}"
        )
    return result


def extract_ipa(ipa_path: Path, dest_dir: Path) -> Path:
    """Extract an IPA into dest_dir and return the path to the .app bundle."""
    if not ipa_path.is_file():
        raise IPAError(f"IPA not found: {ipa_path}")
    dest_dir.mkdir(parents=True, exist_ok=True)

    unzip = shutil.which("unzip")
    if unzip:
        _run([unzip, "-qq", "-o", str(ipa_path), "-d", str(dest_dir)])
    else:
        # Fallback: Python zipfile (does not preserve symlinks perfectly,
        # but is good enough for read-only inspection / non-macOS hosts).
        import zipfile

        with zipfile.ZipFile(ipa_path) as zf:
            zf.extractall(dest_dir)

    payload_dir = dest_dir / "Payload"
    if not payload_dir.is_dir():
        raise IPAError("Invalid IPA: no Payload/ directory found")

    app_dirs = [p for p in payload_dir.iterdir() if p.suffix == ".app"]
    if not app_dirs:
        raise IPAError("Invalid IPA: no .app bundle found inside Payload/")
    if len(app_dirs) > 1:
        raise IPAError(f"Unexpected: multiple .app bundles found: {app_dirs}")

    return app_dirs[0]


def repackage_ipa(extracted_root: Path, output_ipa: Path) -> None:
    """Zip extracted_root/Payload (and any siblings) back into output_ipa."""
    payload_dir = extracted_root / "Payload"
    if not payload_dir.is_dir():
        raise IPAError(f"No Payload/ directory in {extracted_root}")

    output_ipa = output_ipa.resolve()
    if output_ipa.exists():
        output_ipa.unlink()
    output_ipa.parent.mkdir(parents=True, exist_ok=True)

    zip_bin = shutil.which("zip")
    to_zip = [p.name for p in extracted_root.iterdir()]

    if zip_bin:
        # -y : store symlinks as symlinks, not resolved targets
        # -r : recurse
        # -q : quiet
        cmd = [zip_bin, "-qry", str(output_ipa)] + to_zip
        _run(cmd, cwd=str(extracted_root))
    else:
        import zipfile

        with zipfile.ZipFile(output_ipa, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, _dirs, files in os.walk(extracted_root):
                for f in files:
                    full = Path(root) / f
                    arcname = full.relative_to(extracted_root)
                    zf.write(full, arcname)
        print(
            "warning: `zip` command not found; used Python zipfile fallback "
            "which does not preserve symlinks. Install `zip` for correct "
            "repackaging of .app bundles containing symlinked frameworks.",
            file=sys.stderr,
        )


def dir_size_bytes(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            fp = Path(root) / f
            if fp.is_symlink():
                continue
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total
