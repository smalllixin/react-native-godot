#!/usr/bin/env python3
"""Build ARM64 Android embedding artifacts without modifying iOS caches or profiles."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from build import ROOT, checkout, run, source_diff_sha256


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive(directory, target):
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as out:
        for file in sorted(directory.rglob('*')):
            if file.is_file():
                info = zipfile.ZipInfo(file.relative_to(directory).as_posix(), (2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                out.writestr(info, file.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path.home()/'Library/Caches/hog-godot/android-472')
    parser.add_argument('--source', type=Path, help='Existing patched development checkout')
    parser.add_argument('--stage', choices=['prepare', 'engine', 'editor', 'bindings', 'package', 'all'], default='all')
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    cache = args.cache.expanduser().resolve(); cache.mkdir(parents=True, exist_ok=True)
    series = json.loads((ROOT/'patches/android-series.json').read_text())
    source = args.source.resolve() if args.source else cache/'godot'
    checkout('https://github.com/godotengine/godot.git', series['base'], source)
    if not args.source:
        marker = cache/'applied-android-series.json'
        if marker.exists() and json.loads(marker.read_text()) != series:
            raise RuntimeError('Patch series changed; choose a fresh --cache directory')
        if not marker.exists():
            for patch in series['patches']:
                file = ROOT/'patches'/patch['file']
                if sha(file) != patch['sha256']: raise RuntimeError('Patch checksum mismatch: '+str(file))
                run(['git', 'apply', '--check', file], source)
                run(['git', 'apply', file], source)
            marker.write_text(json.dumps(series, indent=2)+'\n')
    cpp = cache/'godot-cpp'
    checkout('https://github.com/godotengine/godot-cpp.git', series['bindingsBase'], cpp)
    for patch in series['bindingsPatches']:
        file = ROOT/'patches'/patch['file']
        if sha(file) != patch['sha256']: raise RuntimeError('Bindings checksum mismatch')
        if subprocess.run(['git', 'apply', '--reverse', '--check', file], cwd=cpp, capture_output=True).returncode:
            run(['git', 'apply', file], cpp)
    if args.stage == 'prepare': return
    sdk = Path(os.environ.get('ANDROID_HOME', str(Path.home()/'Library/Android/sdk')))
    ndk = sdk/'ndk/29.0.14206865'
    if not (ndk/'source.properties').exists():
        raise RuntimeError('Install Android NDK: sdkmanager "ndk;29.0.14206865"')
    os.environ['ANDROID_HOME'] = str(sdk)
    os.environ['ANDROID_NDK_ROOT'] = str(ndk)
    scons = cache/'tools/bin/scons'
    if not scons.exists():
        run([sys.executable, '-m', 'venv', cache/'tools'])
        run([cache/'tools/bin/python', '-m', 'pip', 'install', 'scons==4.11.1'])
    os.environ['PATH'] = str(scons.parent)+os.pathsep+os.environ['PATH']
    api = cache/'api'; api.mkdir(exist_ok=True)
    if args.stage in ('engine', 'all'):
        run([scons, 'platform=android', 'target=template_release', 'arch=arm64', 'library_type=shared_library',
             'disable_path_overrides=no', 'vulkan=yes', 'opengl3=yes', f'-j{args.jobs}'], source)
    if args.stage in ('editor', 'all'):
        run([scons, 'platform=macos', 'target=editor', 'arch=arm64', 'opengl3=no', 'vulkan=no', f'-j{args.jobs}'], source)
        run([source/'bin/godot.macos.editor.arm64', '--headless', '--dump-extension-api'], api)
        shutil.copyfile(source/'core/extension/gdextension_interface.gen.h', api/'gdextension_interface.h')
    if args.stage in ('bindings', 'all'):
        if not (api/'extension_api.json').exists(): raise RuntimeError('Run --stage editor first')
        run([scons, 'platform=android', 'target=template_release', 'arch=arm64', f'custom_api_file={api/"extension_api.json"}',
             'api_version=4.7', 'ndk_version=29.0.14206865', 'android_api_level=24', f'-j{args.jobs}'], cpp)
    if args.stage in ('package', 'all'):
        java = source/'platform/android/java'
        run([java/'gradlew', ':lib:assembleTemplateRelease', '-x', ':lib:compileGodotNativeLibsTemplateReleaseArm64', '--console=plain'], java)
        output = cache/'artifacts/Release'; output.mkdir(parents=True, exist_ok=True)
        stage = cache/'package'; shutil.rmtree(stage, ignore_errors=True); stage.mkdir()
        version = '4.7.2.hog.android.1'
        artifact = stage/'engine/com/migeran/libgodot/godot'/f'{version}-SNAPSHOT'; artifact.mkdir(parents=True)
        name = f'godot-{version}-SNAPSHOT'
        shutil.copyfile(java/'lib/build/outputs/aar/godot-lib.template_release.aar', artifact/(name+'.aar'))
        (artifact/(name+'.pom')).write_text(f'''<project><modelVersion>4.0.0</modelVersion><groupId>com.migeran.libgodot</groupId><artifactId>godot</artifactId><version>{version}-SNAPSHOT</version><packaging>aar</packaging><dependencies>
<dependency><groupId>androidx.fragment</groupId><artifactId>fragment</artifactId><version>1.8.6</version></dependency>
<dependency><groupId>androidx.documentfile</groupId><artifactId>documentfile</artifactId><version>1.1.0</version></dependency>
</dependencies></project>''')
        archive(stage/'engine', output/'libgodot-android.zip')
        bindings = stage/'bindings/godot-cpp-android'; (bindings/'arm64-v8a').mkdir(parents=True)
        shutil.copyfile(cpp/'bin/libgodot-cpp.android.template_release.arm64.a', bindings/'arm64-v8a/libgodot-cpp.a')
        shutil.copytree(cpp/'include', bindings/'include', dirs_exist_ok=True)
        shutil.copytree(cpp/'gen/include', bindings/'include', dirs_exist_ok=True)
        (bindings/'include/gdextension_interface.h').write_text('#ifndef HOG_GDEXTENSION_INTERFACE_H\n#define HOG_GDEXTENSION_INTERFACE_H\n'+(api/'gdextension_interface.h').read_text()+'\n#endif\n')
        archive(stage/'bindings', output/'godot-cpp-android.zip')
        entries = []
        for lib, filename, env in [('libgodot-android','libgodot-android.zip','LIBGODOT_ANDROID_PATH'),('libgodot-cpp-android','godot-cpp-android.zip','LIBGODOT_CPP_ANDROID_PATH')]:
            entries.append({'name':lib,'filename':filename,'version':version,'base_url':'','shasum':sha(output/filename),
                'destination_base_dir':'android/libs','env':env,'no_unpack':'false','mavenArtifact':'godot'})
        provenance = {'qualification':'unqualified','engineRevision':series['base'],'bindingsRevision':series['bindingsBase'],
            'patches':series,'apiSha256':sha(api/'extension_api.json'),'sourceDiffSha256':source_diff_sha256(source),
            'exporterSha256':sha(source/'bin/godot.macos.editor.arm64'), 'sconsVersion':'4.11.1',
            'sourceMode':'development-checkout' if args.source else 'pinned-source-and-patches',
            'configuration':'Release','abis':['arm64-v8a'],'ndkVersion':'29.0.14206865',
            'bridgeRevision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'bridgeDirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)), 'nativeArtifacts':entries,
            'artifacts':{entry['filename']:entry['shasum'] for entry in entries}}
        (output/'provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
        print(output)

if __name__ == '__main__': main()
