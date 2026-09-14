# Expo 57 bridge upgrade and Godot 4.7.2 assessment

This fork evaluates upstream PRs against an Expo 57 / React Native 0.86 iOS app.
The embedded engine is still **4.5.1.migeran.2**. This branch does not claim Godot 4.7 support.

## Open PR decisions (September 14, 2026)

- [PR #33](https://github.com/borndotcom/react-native-godot/pull/33), head
  `cbd1bfa08b23c3e938fbbedf0473c189548fa44b`: incorporated on the upgrade branch for
  integration testing. Its migration to `react-native-worklets` 0.10 matches Expo 57,
  removes the separate Worklets Core dependency, fixes callback-context comparison,
  uses byte-aware JS-to-Godot conversion, restores iOS background state, and respects
  the engine FPS cap when configuring CADisplayLink. It is a substantial native API
  change, not a drop-in upgrade for callers using Worklets Core callbacks. No upstream
  CI or review approvals were reported at inspection time. Its example test mocks the
  engine and cannot certify native lifetime behavior.
- [PR #34](https://github.com/borndotcom/react-native-godot/pull/34), head
  `8a490dc7804ebe617fb2eb9030d411beb588da4b`: cherry-picked with original author attribution.
  The Kotlin-extension guard is after Android plugin registration and preserves the
  old explicit-plugin path when Kotlin is absent. Useful for AGP 9; Android remains
  unverified in our iPhone prototype.
- Additional fix: Godot-to-JS string conversion now uses UTF-8 **byte length**, not
  Unicode code-point count. The old conversion can truncate Chinese text and emoji.

## Why the engine cannot simply be replaced

Official Godot 4.7.2 is checked at commit `ed1daf0bf001b61586d9930840f2f1394092c079`.
It includes upstream LibGodot support, but its supported platforms and API differ from
Migeran's fork:

1. `scons platform=ios target=template_debug arch=arm64 simulator=yes library_type=static_library --dry-run`
   exits with `ERROR: Library builds unsupported for ios`.
2. `platform/ios/detect.py` lists `metal` and `mono`, but not `library`, as supported;
   it also explicitly disables Metal on the iOS simulator.
3. Official `libgodot_create_godot_instance` takes three arguments. This bridge uses
   Migeran's extended function signature, including initialization/logging callbacks.
4. Official 4.7.2 does not expose Migeran's `DisplayServerEmbedded`,
   `RenderingNativeSurface`, or `RenderingNativeSurfaceApple` classes. The current
   iOS view and input integration depend on those classes and generated C++ bindings.

Sources: [library build guard](https://github.com/godotengine/godot/blob/4.7.2-stable/SConstruct),
[iOS build configuration](https://github.com/godotengine/godot/blob/4.7.2-stable/platform/ios/detect.py),
[official C API](https://github.com/godotengine/godot/blob/4.7.2-stable/core/extension/libgodot.h).
Migeran's 4.5 branch is 79 commits ahead of official 4.5.1; those changes include native
surfaces, restart handling, threading and simulator rendering. The newest published
[Migeran binaries](https://github.com/migeran/libgodot/releases) are 4.5.1.migeran.2.
The checked community forks did not supply a compatible newer iOS engine.

A real 4.7.2 upgrade needs an iOS embedding port: decide between porting Migeran's
native-surface/thread/lifecycle patches or rewriting the iOS bridge around a new
upstream-supported surface API. Then regenerate matching godot-cpp bindings, build
simulator/device XCFrameworks, and validate rendering, input, callback lifetime and
restart. Changing package version strings or linking the ordinary iOS export library
would not fulfill that work. Keep the known engine pin until that gate passes.

## Consumer migration

Use `react-native-worklets` >=0.10 <0.12 and its Babel integration. Replace Worklets Core
`createRunOnJS` wrappers with `scheduleOnRN` inside the Godot worklet. Pass semantic data
and keep all Godot object access inside `runOnGodotThread`. Rebuild native dependencies.

The downloaded engine assets retain upstream SHA-256 verification. No unverified 4.7
binary, credentials, app data or proprietary scene assets are included in this fork.
