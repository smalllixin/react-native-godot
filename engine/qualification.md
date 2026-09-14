# Qualification ledger

Status: in progress. **Godot 4.7.2 is not promoted.** House of G keeps its
4.5.1 engine selection. No registry package or engine release has been published.

## Current Simulator evidence — 2026-09-14

Harness: Expo 57.0.20, React Native 0.86.3, Worklets 0.10.1, React 19.2.3.
Simulator: iPhone 17 Pro, iOS 26.4, Apple Silicon. Native builds use Xcode 26.4
(17E192). The final source revision must accompany subsequent acceptance runs.

Candidate 4.7.2:

- Blue and red fixtures render with Metal/Mobile beneath native controls.
- 100 consecutive alternating pack/engine restarts completed after the timing
  and autorelease-pool fixes. Each scene processed at least three frames.
- Twenty surface detach/attach cycles completed without losing the native draft.
- Twenty background/resume cycles returned to the same UI/engine; a scene event
  still reached React Native afterwards. These surface/background runs preceded
  the final autorelease-pool and initialization-error changes; repeat on final code.
- Three full JavaScript reloads recreated the scene promptly after clock reset.
- Native typing and sheet open/dismiss were exercised; input draft survived.
- Chinese and emoji round-trip through a GDScript signal and back to native UI.
- A memgraph after 40 restarts reported zero unreachable leaks. Debug RSS after
  20/40/60/80/100 restarts was 576176/585088/536816/547120/553376 KiB. This is
  preliminary Simulator evidence, not a physical memory or thermal certification.
- Matching Debug and Release device/Simulator engine and bindings XCFrameworks
  build, with checksums and actual API provenance. The full clean-cache Debug build also passed.
- Fresh source preparation downloads the pinned revisions and applies both patch
  sets. Its source diff hash exactly matches the development checkout.

Baseline 4.5.1.migeran.2 with the updated bridge:

- Harness native build/launch and 20 alternating pack/engine restarts pass.
- Three full JavaScript reloads and Chinese/emoji round trips pass.
- Earlier House of G testing completed Vivarium edit -> automatic validated
  export -> LAN download -> explicit Reload World without native rebuilding.
- Twenty application pack restarts and three JavaScript reloads passed earlier;
  repeat product regression after installing the pinned final bridge.

Automated checks: bridge/harness type checks, harness render test, installer
checksum rejection/tamper repair/offline-cache tests, and 114 application tests
passed during implementation. These do not establish native lifecycle acceptance.

## Physical baseline scope agreed with the user

A signed Release baseline installed and launched on iPhone 17 Pro, iOS 26.4.2.
The user confirmed the rooftop and G's animation, then returned after other phone
activities and confirmed the rooftop/idle animation remained healthy. The user
asked to consider real-device testing sufficient for now. Do not request more
phone recording in this round or promote 4.7.2 on this basis.

A short Game Performance Overview capture (11 sampling intervals) measured
baseline FPS mean 30.009, range 29.207–30.907, zero skipped frames, peak physical
footprint 403.267 MiB, and Fair thermal state. The original per-process Instruments
attachment deadlocked before samples. A later full capture did not start because
the device connection timed out. **The 20-minute comparison is unverified.**
Release Hermes inspection found no development-panel or pack-server controls.

## Remaining acceptance

- Finish and validate Debug/Release artifacts from the documented clean recipe.
- Final native coordinator/runtime cancellation and initialization-failure checks.
- Gesture picking after camera movement, bounds/cancellation, queued-work reload,
  duplicate-callback assertions, UI Fast Refresh, and deliberate startup failures.
- Product regression on the pinned bridge: navigation/drafts, reduced motion,
  VoiceOver, large text, English and Chinese layouts.
- Physical candidate qualification and matched 20-minute Release performance
  comparison remain deferred. Simulator success cannot satisfy this dependency.

## Reproduced issues fixed in the port

- iOS `disable_path_overrides` rejected the external main pack; library recipe
  explicitly permits the app-selected pack path.
- Apple Silicon Simulator needs Metal cube-array emulation and supported present
  calls; device rendering retains its native path.
- GDType class initialization and godot-cpp static method binds survived engine
  teardown; registration and bindings now reinitialize per session.
- Singleton/ObjectDB/audio/display registry cleanup, rendering globals, and ZIP
  archive ownership needed reset for repeatable startup/shutdown.
- Sky shader cleanup needs its renderer singleton until member destruction ends.
- `OS::target_ticks` retained a previous session's deadline and blocked new frames
  in `nanosleep`; frame deadlines and physics timing now reset between sessions.
- A native Callable held a JSI value after its runtime died. Runtime-owned callback
  storage and generation checks replaced that lifetime mismatch.

Evidence files are stored under House of G's `artifacts/rooftop` locally, along
with XcodeBuildMCP logs and `/tmp/hog-candidate-memgraph-40`. Keep exact commands,
source/artifact hashes, and final-build test results when promoting later.

## Clean-built product check

The clean-cache Debug artifacts were installed into House of G and the actual
Vivarium rooftop exported with that cache's matching 4.7.2 exporter. Native build
and launch passed; the rooftop rendered and its conversation camera responded.
Diagnostics reported `4.7.2-stable (custom_build)`, max FPS 30, Unicode round trips,
and the pinned bridge. Twenty actual rooftop reloads passed without Godot errors.
House of G's baseline selection and bundled pack were restored after this check.

The pinned 4.5.1 product build also passed chat/keyboard -> reading -> tarot ->
account -> home with a native draft preserved, 20 rooftop reloads, and automatic
validated export -> explicit downloaded pack reload. Temporary draft/source edits
were removed. A reproduced RN/Expo cache problem mixed Release binaries with Debug
markers; application setup now invalidates generated configuration markers after
CocoaPods, allowing the upstream build scripts to restore matching binaries.

No new physical-device installation or recording was performed after the user
paused phone testing. Physical qualification, the full performance comparison,
and the remaining acceptance cases above are still required before promotion.
