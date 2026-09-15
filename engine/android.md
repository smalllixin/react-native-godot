# Android 4.7.2 embedding

Android uses the same TurboModule/Fabric and Worklets bridge as iOS. The Android
patch series adds JNI host services and an Android native rendering surface to
Godot 4.7.2. It also resets engine registries at shutdown: Android's Java library
keeps the shared object loaded across engine generations.

## Build locally

Use Apple Silicon, JDK 17, Python 3, Git, Xcode (for the matching macOS exporter),
and Android SDK with NDK 29.0.14206865. Install that NDK with
`sdkmanager "ndk;29.0.14206865"`. Export `ANDROID_HOME` for a nonstandard SDK location.

```sh
python3 engine/build_android.py --cache "$HOME/Library/Caches/hog-godot/android-472"
```

The ordered inputs are in `patches/android-series.json`; the iOS series is unchanged.
The script builds ARM64 Release engine and bindings artifacts, a matching exporter,
and `artifacts/Release/provenance.json` with source/API/patch and archive checksums.
Stages: `prepare`, `engine`, `editor`, `bindings`, `package`. Use a fresh cache after
changing the patch series. `--source` is for development, not a clean qualification run.
No artifacts are automatically published. The application records the resulting
checksums in its platform-specific profile before installation.

Install into this fork for the harness (set the two archive paths to your output):

```sh
LIBGODOT_ANDROID_PATH="$HOME/Library/Caches/hog-godot/android-472/artifacts/Release/libgodot-android.zip" \
LIBGODOT_CPP_ANDROID_PATH="$HOME/Library/Caches/hog-godot/android-472/artifacts/Release/godot-cpp-android.zip" \
node scripts/download-prebuilt.js --platform android \
  --profile "$HOME/Library/Caches/hog-godot/android-472/artifacts/Release/provenance.json"
python3 example/export-harness.py --platform android \
  --godot "$HOME/Library/Caches/hog-godot/android-472/godot/bin/godot.macos.editor.arm64"
cd example
npx expo prebuild --platform android --no-install
npx expo run:android
```

The harness starts the blue pack and exposes a second red pack, 20 restart/pack
cycles, surface detach/attach cycles, JavaScript reload, a native text field and
sheet, and a Chinese/emoji event round trip. For repeatable engine-only runs,
set `EXPO_PUBLIC_GODOT_HARNESS_CYCLES=20` when starting its Metro server. This does
not substitute for manual keyboard, gestures, accessibility, or background tests.

For a separate Metro port (for example 8082), use `adb reverse tcp:8082 tcp:8082`
and set the development server address to `localhost:8082` in React Native's
Dev Settings. Android emulator defaults otherwise use `10.0.2.2:8081`.

## Renderer and qualification

Vulkan/Mobile is selected explicitly. The Pixel 8 API 34 emulator on this Mac
reports Vulkan 1.3 with `llvmpipe`; this is a software renderer. A successful
emulator run is not physical GPU performance evidence. House of G also defines
an explicit emulator-only OpenGL Compatibility profile; it is not an automatic
fallback and requires a matching exported pack.

Android qualification is recorded separately from iOS in House of G's Android
integration report. Physical Android and production qualification remain pending.

## C++ thread-local storage compatibility

The bindings archive targets Android API 24 and uses emulated TLS. The bridge
explicitly uses `-femulated-tls` too, including when its app targets API 29+.
Mixing ELF TLS and emulated TLS creates two copies of Godot 4.7 construction
state and aborts when allocating a touch event. Do not remove that consumer flag
without rebuilding the bindings with the same TLS model.

When checking the unstripped `librtngodot.so`, `llvm-nm -C` should show only
`__emutls_v._ZZN5godot7Wrapped19_get_construct_infoEvE4info` storage, not a second
`godot::Wrapped::_get_construct_info()::info` ELF TLS symbol.
