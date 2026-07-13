## How ipaopt Works 

---

##  Architectural Overview

Apple's asset catalog pipeline is a one-way system. Once raw `.xcassets` source folders are compiled into a binary `Assets.car` file, they become an opaque, optimized image blob.

```text
  [ Raw Source Assets ] ───( Xcode / actool )───► [ Compiled Assets.car ]
  (Editable Json/PNGs)                              (Opaque Binary Blob)
                                                             │
                                                    ❌ CANNOT SELECTIVELY
                                                       DELETE FROM CAR
Because Assets.car files cannot be mutated after compilation, ipaopt intercepts the pipeline at two completely different stages depending on your needs.

Mode 1: ipaopt strip (Post-Build Pipeline)
This mode targets an already built .ipa file. It focuses on removing loose, non-cataloged assets and thinning fat binaries.

Execution Flow:
Plaintext
      ┌────────────────────────────────────────┐
      │               Target IPA               │
      └───────────────────┬────────────────────┘
                          │
             [1] Extract & Inspect Bundle
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
   [Loose Resources]               [Mach-O Binaries]
         │                                 │
   [2] Match filename patterns       [3] Thin architectures
       (e.g., `@2x~ipad.png`)            via `lipo` tool
         │                                 │
   [4] Purge matching files          [5] Replace fat binary
         │                                 │
         └────────────────┬────────────────┘
                          │
           [6] Repackage into `.ipa`
                          │
                          ▼
      ┌────────────────────────────────────────┐
      │         ⚠️ INVALIDATED SIGNATURE        │
      │    Must re-sign before installation!   │
      └────────────────────────────────────────┘
Breakdown of Steps:
Extraction: ipaopt unzips the .ipa container to inspect its contents.

Loose Resource Stripping: It scans the bundle directory structure for loose image assets. Using Apple's old-school naming conventions (eg ; ~ipad, @1x), it deletes files matching your --remove-idiom and --keep-scales rules.

Binary Thinning: It looks for compiled Mach-O executables and dynamic frameworks. It invokes the macOS lipo tool to strip out unneeded CPU architecture slices (like legacy 32-bit slices or simulator targets), keeping only what you specified (eg ; arm64).

Re-zipping: It bundles the modified payload back into a new .ipa.

🛑 Note: Modifying the contents of a compiled application bundle instantly breaks the cryptographic signature. The final .ipa must be re-signed before it can be side-loaded or submitted to Apple.

Mode 2: ipaopt catalog-filter (Pre-Build Pipeline)
This mode targets the raw .xcassets source directory before Xcode compiles the project. It allows you to actually reduce the size of the final Assets.car binary.

Execution Flow:
Plaintext
      ┌────────────────────────────────────────┐
      │         Raw .xcassets Folder           │
      └───────────────────┬────────────────────┘
                          │
             [1] Deep-scan Directory Tree
                          │
         ┌────────────────┴────────────────┐
         ▼                                 ▼
   [Contents.JSON Files]            [Raw Asset Files]
         │                                 │
   [2] Parse and strip metadata      [3] Delete physical image
       entries matching rules            files dropped from JSON
         │                                 │
         └────────────────┬────────────────┘
                          │
            [4] Write Filtered .xcassets
                          │
             Is `--compile` flag set?
                    ├───► NO  ──► Stop (Output modified source)
                    │
                    └───► YES ──► [5] Invoke `actool` (macOS Only)
                                         │
                                         ▼
                                ┌─────────────────┐
                                │ Lean Assets.car │
                                └─────────────────┘
Breakdown of Steps:
Metadata Parsing: ipaopt crawls your asset catalog directory. Every image set or data set has a Contents.Json file defining its variants (idioms, scales, appearances).

JSON Pruning: The tool parses these JSON structures and removes array entries that conflict with your rules (eg ; dropping the dark mode dictionary entry or removing the iPad device target).

File Cleanup: It compares the updated Contents.json files against the physical assets inside the folders, deleting any raw .png, .jpg, or .pdf files that are no longer referenced.

Compilation (Optional): If --compile is enabled, ipaopt acts as a wrapper for Apple's actool. It passes the freshly optimized, lightweight .xcassets structure into the official compiler to output a pristine, space saving Assets.car binary.
