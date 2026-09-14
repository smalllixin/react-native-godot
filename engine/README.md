# House of G embedding engine

This fork retains TurboModule/Fabric and Worklets. It ports the iOS embedding
surface to upstream Godot 4.7.2; it does not replace upstream LibGodot's creation
API. The candidate remains **unqualified** until both Simulator and physical
Apple-device acceptance pass. The published 4.5.1.migeran.2 artifacts remain the
baseline.

## Build

Use Apple Silicon, Xcode 26.4 with its iOS/Simulator SDKs and Metal toolchain,
Python 3, Git, and network access. Select Xcode with `xcode-select` if needed.

```
python3 engine/build.py --configuration Debug
python3 engine/build.py --configuration Release
```

The script pins engine and godot-cpp revisions, verifies the ordered patch
checksums, creates its own pinned SCons environment, builds a matching macOS
exporter, dumps the patched API, builds arm64 iPhone and Simulator libraries,
and packages engine and bindings XCFrameworks. Outputs and downloads live in
`~/Library/Caches/hog-godot/candidate`, overridable with `--cache`. No temporary
files from an earlier session are build inputs. A changed patch series requires
a fresh cache directory. `--source` is for local port development only.

Each stage can be run independently with `--stage prepare|editor|ios|bindings|package`.
`--sdk simulator|device` limits a development build to one slice; only `both`
produces the complete milestone artifact. Debug and Release outputs are separate.
`artifacts/<configuration>/provenance.json` records source revisions, patches,
Xcode, available slices, and archive SHA-256 values. They are not promotion evidence.
The manually dispatched workflow builds artifacts; it never publishes a package
or changes the application's engine selection.

## Native contract

The bridge detects `libgodot_embedding_api_version` and calls upstream
`libgodot_create_godot_instance(argc, argv, initialize)`. The separate
`libgodot_set_log_callback` extension forwards logs. Without the extension marker,
the bridge uses the baseline Migeran ABI. An engine change requires new bindings,
frameworks, CocoaPods setup, a native app build, and a matching scene export.

Godot operations execute on its thread; UIKit surface mutations execute on main.
One engine survives normal React view unmount/remount. A pack reload destroys
and recreates it. Full JavaScript reload invalidates the old worklet context and
restarts the engine. Callbacks are owned by their worklet runtime, not a persistent
native JSI value, and carry an engine generation. **Create callbacks and access engine objects inside
`runOnGodotThread`; use Worklets `scheduleOnRN` to notify the native UI.** Calling
into the RN runtime synchronously from Godot is unsupported.

The initial port targets Metal/Mobile, native touch input, and one main surface.
SDL controllers, standalone iOS application startup, and engine-owned iOS plugins
are excluded from library mode. Android remains on its existing baseline.
`migeran-audit.json` records what was ported, already upstream, or left to runtime
parity review. Unreviewed parity items are not presumed unnecessary.

The framework wrapper derives from Migeran's MIT-licensed `libgodot` repository,
branch `libgodot_migeran_45`. Engine patch files preserve original license headers.

## Run the harness with local artifacts

```
corepack yarn install --immutable
python3 engine/install-local.py --artifacts ~/Library/Caches/hog-godot/candidate/artifacts/Debug
python3 example/export-harness.py --godot ~/Library/Caches/hog-godot/candidate/godot/bin/godot.macos.editor.arm64
(cd example/ios && pod install)
corepack yarn workspace GodotTest start
corepack yarn workspace GodotTest ios
```

`install-local.py` verifies archives against build provenance, records an ignored
local artifact selection, and installs under checksum-specific paths. It does
not change the application's active profile or publish artifacts. To return the
example to baseline, run `node scripts/download-prebuilt.js --platform ios` after
removing the local selection file, then run CocoaPods and rebuild. Existing
baseline framework directories are retained.

The hosted workflow selects macOS 26 arm64 and Xcode 26.4.1 explicitly instead
of inheriting the runner's changing default. Local evidence currently uses
Xcode 26.4 (17E192); hosted artifacts remain separate and unqualified. Runner
availability is documented in [GitHub's image inventory](https://github.com/actions/runner-images/blob/main/images/macos/macos-26-arm64-Readme.md).
