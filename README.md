# ipaopt

A CLI tool for optimizing IPA asset catalogs: strips legacy device resources,
unsupported device idioms (iPad, Mac Catalyst, tvOS, watchOS, CarPlay),
unused display scales (1x/2x/3x), light/dark/tinted appearance variants, and
unnecessary CPU architecture slices, to reduce final IPA size.

## Important: what this can and can't do to compiled `Assets.car`

Xcode compiles `.xcassets` source folders into a binary `Assets.car` archive
at build time. There is no supported way to selectively delete entries from
an already compiled `Assets.car` Apple's own tooling (`actool`) only
rebuilds it wholesale from the original `.xcassets` source. Because of that,
`ipaopt` works in two complementary modes:

1. **`ipaopt strip`** / **`ipaopt report`** — operate directly on a built
   `.ipa`. They strip *loose* (non-catalog) image resources that follow
   Apple's `name@2x~ipad.png` naming convention, thin Mach-O binaries down to
   the architectures you want to keep (via `lipo`), and print a report of
   what's inside any `Assets.car` files found (via `assetutil`, macOS-only)
   so you know what a source-level rebuild would remove.

2. **`ipaopt catalog-filter`** operates on your project's `.xcassets`
   *source* folder (before compilation). It removes entries matching your
   idiom/scale/appearance rules and rewrites `Contents.json` accordingly,
   and can optionally recompile the result into a new `Assets.car` via
   `actool` (requires macOS + Xcode). This is the right tool when you have
   access to the source project and want the compiled catalog itself
   reduced  plug it into your build phase before `actool` normally runs,
   or use it standalone and swap in the generated `Assets.car`.

`lipo` and `actool`/`assetutil` are macOS/Xcode-only tools with no portable
equivalent, so architecture thinning and catalog recompilation require
running `ipaopt` on macOS with Xcode command line tools installed. Loose
resource stripping and reporting work on any platform.

## Install

```bash
cd ipaopt
pip install -e .
```

This installs the `ipaopt` command. (Or run without installing:
`python -m ipaopt.cli ...` from the project root.)

## Usage

### Inspect an IPA

```bash
ipaopt report MyApp.ipa
```

Shows total size, current CPU architectures per binary, count of loose
idiom/scale-suffixed image files, and a breakdown of any compiled
`Assets.car` by idiom/scale/appearance.

### Strip a built IPA

```bash
ipaopt strip MyApp.ipa \
  --output MyApp.optimized.ipa \
  --remove-idiom ipad,mac,tv,watch,car \
  --keep-scales 2x,3x \
  --remove-appearance dark,tinted \
  --keep-arch arm64,arm64e
```

- `--remove-idiom` — comma-separated idioms to drop resources for. Choices:
  `universal,iphone,ipad,mac,tv,watch,watch-marketing,car`.
- `--keep-scales` — comma-separated scales to *keep*; anything else is
  removed. Default `2x,3x` (drops legacy 1x/non-Retina images).
- `--remove-appearance` — appearance variants to drop, e.g. `dark,tinted`
  (only affects loose files if your project encodes appearance in filenames;
  for catalog-based dark/tinted variants use `catalog-filter`).
- `--keep-arch` — CPU architectures to keep in Mach-O binaries. Choices:
  `arm64,arm64e,armv7,armv7s,x86_64,i386`. Default `arm64,arm64e`.
- `--dry-run` — print what would be removed without changing/writing
  anything.

Add `--dry-run` first to review the plan before committing to it.

**After stripping, the IPA's code signature is invalidated.** Re-sign it
(`codesign`, Xcode, or a tool like `fastlane resign`) before installing on a
device or uploading to App Store Connect / TestFlight.

### Filter and recompile an `.xcassets` source folder

```bash
ipaopt catalog-filter MyApp/Assets.xcassets \
  --output MyApp/Assets.filtered.xcassets \
  --remove-idiom ipad,mac,tv,watch \
  --keep-scales 2x,3x \
  --remove-appearance dark,tinted \
  --compile --platform iphoneos --deployment-target 15.0
```

Without `--compile`, this just writes the filtered `.xcassets` folder (for
inspection or feeding into your own build pipeline). With `--compile`, it
also invokes `actool` to produce a new `Assets.car` in `--compile-output`
(default: `<output>/../compiled/Assets.car`). Use `--app-icon-name` if
compiling an app icon set.

## Naming convention reference (loose resources)

| Filename                | Idiom     | Scale |
|--------------------------|-----------|-------|
| `Icon.png`               | universal | 1x    |
| `Icon@2x.png`            | universal | 2x    |
| `Icon@3x.png`            | universal | 3x    |
| `Icon~ipad.png`          | ipad      | 1x    |
| `Icon@2x~ipad.png`       | ipad      | 2x    |
| `Icon~iphone.png`        | iphone    | 1x    |

## Limitations

- `lipo`, `actool`, and `assetutil` are macOS/Xcode-only; on other platforms
  `ipaopt strip` will still remove loose resources but will skip
  architecture thinning and catalog inspection with a clear message.
- `catalog-filter` requires access to your `.xcassets` source; it cannot
  operate on an already-compiled `Assets.car`.
- Removing resources an app actually looks up at runtime (e.g. dynamically
  constructed asset names, or a Catalyst/iPad build target that legitimately
  needs those idioms) will break the app at runtime. Always test the
  resulting build. `--dry-run` and `ipaopt report` are there to help you
  verify the plan before applying it.
