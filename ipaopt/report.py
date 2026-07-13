from __future__ import annotations


def human_size(n: int) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024.0:
            return f"{n:3.1f}{unit}"
        n /= 1024.0
    return f"{n:.1f}TB"


def print_header(title: str) -> None:
    print()
    print(title)
    print("-" * len(title))


def print_thin_results(results) -> None:
    print_header("Architecture thinning")
    if not results:
        print("  No Mach-O binaries found.")
        return
    total_before = total_after = 0
    for r in results:
        total_before += r.bytes_before
        total_after += r.bytes_after
        rel = r.path.name
        if r.skipped_reason:
            print(f"  [skip] {rel}: {r.skipped_reason} ({', '.join(r.before_archs) or '?'})")
        else:
            saved = r.bytes_before - r.bytes_after
            print(
                f"  {rel}: {','.join(r.before_archs)} -> {','.join(r.after_archs)} "
                f"({human_size(r.bytes_before)} -> {human_size(r.bytes_after)}, "
                f"saved {human_size(saved)})"
            )
    print(f"  Total: {human_size(total_before)} -> {human_size(total_after)} "
          f"(saved {human_size(total_before - total_after)})")


def print_loose_asset_plan(matches, freed_bytes: int, dry_run: bool) -> None:
    print_header("Loose (non-catalog) image resources")
    if not matches:
        print("  No matching loose resources found to remove.")
        return
    verb = "Would remove" if dry_run else "Removed"
    for m in matches[:50]:
        print(f"  {verb}: {m.path} (idiom={m.idiom or 'universal'}, scale={m.scale})")
    if len(matches) > 50:
        print(f"  ... and {len(matches) - 50} more")
    print(f"  {verb} {len(matches)} files, {human_size(freed_bytes)}")


def print_car_report(car_report: dict) -> None:
    print_header("Compiled asset catalogs (Assets.car)")
    if not car_report:
        print("  No Assets.car files found.")
        return
    for path, summary in car_report.items():
        print(f"  {path}")
        if "error" in summary:
            print(f"    ! {summary['error']}")
            continue
        print(f"    total assets: {summary['total_assets']}")
        print(f"    by idiom:      {summary['by_idiom']}")
        print(f"    by scale:      {summary['by_scale']}")
        print(f"    by appearance: {summary['by_appearance']}")
        print("    (to actually strip entries, filter+recompile from .xcassets "
              "source with `ipaopt catalog-filter`)")


def print_catalog_filter_stats(stats, dry_run: bool) -> None:
    print_header(".xcassets catalog filter")
    verb = "Would remove" if dry_run else "Removed"
    print(f"  Imagesets scanned: {stats.imagesets_scanned}")
    print(f"  Entries {verb.lower()}: {stats.entries_removed}")
    print(f"  Files {verb.lower()}: {stats.files_removed}")
    print(f"  Bytes freed: {human_size(stats.bytes_freed)}")
