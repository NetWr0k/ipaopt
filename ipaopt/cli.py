from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from . import catalog_filter, catalog_report, loose_assets, report
from .binary_thin import thin_app
from .ipa_ops import IPAError, dir_size_bytes, extract_ipa, repackage_ipa
from .rules import ALL_ARCHS, ALL_IDIOMS, FilterRules


def _add_common_filter_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--remove-idiom", default="",
        help=(
            "Comma-separated device idioms whose resources should be removed. "
            f"Choices: {','.join(sorted(ALL_IDIOMS))}. "
            "Example: --remove-idiom ipad,mac,tv,watch"
        ),
    )
    p.add_argument(
        "--keep-scales", default="2x,3x",
        help="Comma-separated display scales to KEEP (others are removed). Default: 2x,3x",
    )
    p.add_argument(
        "--remove-appearance", default="",
        help="Comma-separated appearance variants to remove, e.g. dark,tinted",
    )


def _build_rules(args) -> FilterRules:
    return FilterRules(
        remove_idioms=FilterRules.parse_csv(args.remove_idiom),
        keep_scales=FilterRules.parse_csv(args.keep_scales) or {"1x", "2x", "3x"},
        remove_appearances=FilterRules.parse_csv(args.remove_appearance),
    )


def cmd_strip(args) -> int:
    ipa_path = Path(args.ipa).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    rules = _build_rules(args)
    keep_archs = FilterRules.parse_csv(args.keep_arch) or {"arm64", "arm64e"}
    bad = keep_archs - ALL_ARCHS
    if bad:
        print(f"error: unknown arch(es) {sorted(bad)}", file=sys.stderr)
        return 2

    with tempfile.TemporaryDirectory(prefix="ipaopt-") as tmp:
        tmp_dir = Path(tmp)
        try:
            print(f"Extracting {ipa_path.name} ...")
            app_dir = extract_ipa(ipa_path, tmp_dir)
        except IPAError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

        size_before = dir_size_bytes(tmp_dir)

        # 1. Loose resource stripping.
        matches = loose_assets.plan_removals(app_dir, rules)
        freed = loose_assets.apply_removals(matches, dry_run=args.dry_run)
        report.print_loose_asset_plan(matches, freed, args.dry_run)

        # 2. Architecture thinning.
        thin_results = thin_app(app_dir, keep_archs, dry_run=args.dry_run)
        report.print_thin_results(thin_results)

        # 3. Report on compiled catalogs (informational; see catalog-filter
        #    subcommand for actually rebuilding them from source).
        car_report = catalog_report.report_car_files(app_dir)
        report.print_car_report(car_report)

        size_after = dir_size_bytes(tmp_dir)

        report.print_header("Summary")
        print(f"  App size before: {report.human_size(size_before)}")
        print(f"  App size after:  {report.human_size(size_after)}")
        print(f"  Saved:           {report.human_size(size_before - size_after)}")

        if args.dry_run:
            print("\nDry run: no files were modified, no output IPA was written.")
            return 0

        print(f"\nRepackaging to {output_path} ...")
        repackage_ipa(tmp_dir, output_path)
        print("Done.")
        print(
            "\nNOTE: modifying binary contents invalidates the original code "
            "signature. Re-sign the IPA (codesign / Xcode / fastlane resign) "
            "before installing on a device or uploading to the App Store / TestFlight."
        )
    return 0


def cmd_report(args) -> int:
    ipa_path = Path(args.ipa).expanduser().resolve()
    with tempfile.TemporaryDirectory(prefix="ipaopt-report-") as tmp:
        tmp_dir = Path(tmp)
        try:
            app_dir = extract_ipa(ipa_path, tmp_dir)
        except IPAError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

        size = dir_size_bytes(tmp_dir)
        report.print_header(f"{ipa_path.name}")
        print(f"  Total size: {report.human_size(size)}")

        thin_results = thin_app(app_dir, keep_archs={"arm64", "arm64e"}, dry_run=True)
        report.print_thin_results(thin_results)

        loose = loose_assets.find_loose_assets(app_dir)
        report.print_header("Loose (non-catalog) image resources found")
        print(f"  {len(loose)} files matched Apple's idiom/scale naming convention")

        car_report = catalog_report.report_car_files(app_dir)
        report.print_car_report(car_report)
    return 0


def cmd_catalog_filter(args) -> int:
    src = Path(args.xcassets).expanduser().resolve()
    if not src.is_dir() or src.suffix != ".xcassets":
        print(f"error: {src} is not a .xcassets directory", file=sys.stderr)
        return 2
    dest = Path(args.output).expanduser().resolve()
    rules = _build_rules(args)

    stats = catalog_filter.filter_xcassets(src, dest, rules, dry_run=args.dry_run)
    report.print_catalog_filter_stats(stats, args.dry_run)

    if args.dry_run:
        print("\nDry run: no files were written.")
        return 0

    print(f"\nFiltered catalog written to {dest}")

    if args.compile:
        try:
            car_dir = Path(args.compile_output or (dest.parent / "compiled"))
            car_path = catalog_filter.compile_car(
                dest, car_dir,
                platform=args.platform,
                deployment_target=args.deployment_target,
                app_icon_name=args.app_icon_name,
            )
            print(f"Compiled Assets.car written to {car_path}")
        except RuntimeError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ipaopt",
        description=(
            "Optimize IPA asset catalogs: strip legacy device resources, "
            "unsupported idioms (iPad, Mac Catalyst, tvOS, watchOS, CarPlay), "
            "unused display scales, appearance variants, and unused CPU "
            "architectures to reduce IPA size."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_strip = sub.add_parser(
        "strip", help="Strip resources from a built .ipa and write an optimized copy"
    )
    p_strip.add_argument("ipa", help="Path to the input .ipa file")
    p_strip.add_argument("-o", "--output", required=True, help="Path to write the optimized .ipa")
    p_strip.add_argument(
        "--keep-arch", default="arm64,arm64e",
        help=f"Comma-separated architectures to KEEP in Mach-O binaries. Choices: {','.join(sorted(ALL_ARCHS))}. Default: arm64,arm64e",
    )
    _add_common_filter_args(p_strip)
    p_strip.add_argument("--dry-run", action="store_true", help="Report what would change without modifying anything")
    p_strip.set_defaults(func=cmd_strip)

    p_report = sub.add_parser(
        "report", help="Inspect a built .ipa: architectures, loose assets, compiled catalog contents"
    )
    p_report.add_argument("ipa", help="Path to the input .ipa file")
    p_report.set_defaults(func=cmd_report)

    p_cat = sub.add_parser(
        "catalog-filter",
        help="Filter an .xcassets SOURCE folder by idiom/scale/appearance, optionally recompiling to Assets.car",
    )
    p_cat.add_argument("xcassets", help="Path to the input .xcassets directory")
    p_cat.add_argument("-o", "--output", required=True, help="Path to write the filtered .xcassets directory")
    _add_common_filter_args(p_cat)
    p_cat.add_argument("--dry-run", action="store_true", help="Report what would change without writing anything")
    p_cat.add_argument("--compile", action="store_true", help="Recompile the filtered catalog into Assets.car (macOS + Xcode required)")
    p_cat.add_argument("--compile-output", default=None, help="Directory to write compiled Assets.car into")
    p_cat.add_argument("--platform", default="iphoneos", help="Target platform for actool (default: iphoneos)")
    p_cat.add_argument("--deployment-target", default="13.0", help="Minimum deployment target for actool (default: 13.0)")
    p_cat.add_argument("--app-icon-name", default=None, help="App icon set name, if compiling an AppIcon")
    p_cat.set_defaults(func=cmd_catalog_filter)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
