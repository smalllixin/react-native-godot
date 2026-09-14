#!/usr/bin/env python3
"""Build the pinned embedding candidate. Outputs are unqualified until device tests pass."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent


def run(args, cwd=None):
    print('+', ' '.join(map(str, args)), flush=True)
    subprocess.run(list(map(str, args)), cwd=cwd, check=True)


def checkout(repository, revision, destination):
    if not destination.exists():
        destination.mkdir(parents=True)
        run(['git', 'init', destination])
        run(['git', 'fetch', '--depth', '1', repository, revision], destination)
        run(['git', 'checkout', '--detach', 'FETCH_HEAD'], destination)
    actual = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=destination, text=True).strip()
    if actual != revision:
        raise RuntimeError(f'{destination} has unexpected revision {actual}; choose an empty cache directory')


def source_diff_sha256(source):
    """Identify the actual development patch, including newly added source files."""
    digest = hashlib.sha256()
    digest.update(subprocess.check_output(['git', 'diff', 'HEAD', '--binary'], cwd=source))
    files = subprocess.check_output(['git', 'ls-files', '--others', '--exclude-standard'], cwd=source, text=True)
    for name in files.splitlines():
        diff = subprocess.run(['git', 'diff', '--no-index', '--binary', '/dev/null', name], cwd=source, capture_output=True)
        if diff.returncode not in (0, 1):
            raise RuntimeError('Cannot fingerprint source file: ' + name)
        digest.update(diff.stdout)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cache', type=Path, default=Path.home()/'Library/Caches/hog-godot/candidate')
    parser.add_argument('--source', type=Path, help='Use an existing patched checkout for port development')
    parser.add_argument('--scons', type=Path)
    parser.add_argument('--stage', choices=['prepare', 'editor', 'ios', 'bindings', 'package', 'all'], default='all')
    parser.add_argument('--configuration', choices=['Debug','Release'], default='Debug')
    parser.add_argument('--sdk', choices=['simulator','device','both'], default='both')
    parser.add_argument('--jobs', type=int, default=8)
    args = parser.parse_args()
    cache = args.cache.expanduser().resolve(); cache.mkdir(parents=True, exist_ok=True)
    series = json.loads((ROOT/'patches/series.json').read_text())
    engine_ref = series['base']
    cpp_ref = series['bindingsBase']
    source = args.source.resolve() if args.source else cache/'godot'
    checkout('https://github.com/godotengine/godot.git', engine_ref, source)
    if not args.source:
        marker = cache/'applied-series.json'
        if marker.exists() and json.loads(marker.read_text()) != series:
            raise RuntimeError('Patch series changed; select a fresh cache directory')
        if not marker.exists():
            for patch in series['patches']:
                path = ROOT/'patches'/patch['file']
                if hashlib.sha256(path.read_bytes()).hexdigest() != patch['sha256']:
                    raise RuntimeError('Patch checksum mismatch: '+str(path))
                run(['git', 'apply', '--check', path], source)
                run(['git', 'apply', path], source)
            marker.write_text(json.dumps(series, indent=2)+'\n')
    cpp = cache/'godot-cpp'
    checkout('https://github.com/godotengine/godot-cpp.git', cpp_ref, cpp)
    for patch in series.get('bindingsPatches', []):
        path = ROOT/'patches'/patch['file']
        if hashlib.sha256(path.read_bytes()).hexdigest() != patch['sha256']:
            raise RuntimeError('Bindings patch checksum mismatch: '+str(path))
        applied = subprocess.run(['git', 'apply', '--reverse', '--check', str(path)], cwd=cpp, capture_output=True)
        if applied.returncode:
            run(['git', 'apply', '--check', path], cpp)
            run(['git', 'apply', path], cpp)
    if args.stage == 'prepare': return
    if args.scons:
        scons = args.scons.resolve()
    else:
        tools = cache/'tools'
        scons = tools/'bin/scons'
        if not scons.exists():
            run([sys.executable, '-m', 'venv', tools])
            run([tools/'bin/python', '-m', 'pip', 'install', 'scons==4.11.1'])
    target = 'template_debug' if args.configuration == 'Debug' else 'template_release'
    output = cache/'artifacts'/args.configuration; output.mkdir(parents=True, exist_ok=True)
    api = cache/'api'; api.mkdir(exist_ok=True)
    sdks = ['device','simulator'] if args.sdk == 'both' else [args.sdk]
    if args.stage in ('editor','all'):
        run([scons, 'platform=macos', 'target=editor', 'arch=arm64', 'opengl3=no', 'vulkan=no', f'-j{args.jobs}'], source)
        editor = source/'bin/godot.macos.editor.arm64'
        run([editor, '--headless', '--dump-extension-api'], api)
        shutil.copyfile(source/'core/extension/gdextension_interface.gen.h', api/'gdextension_interface.h')
    if args.stage in ('ios','all'):
        for sdk in sdks:
            run([scons, 'platform=ios', f'target={target}', 'arch=arm64', f'simulator={"yes" if sdk == "simulator" else "no"}', 'library_type=static_library', 'disable_path_overrides=no', 'opengl3=no', 'vulkan=no', 'sdl=no', f'-j{args.jobs}'], source)
    if args.stage in ('bindings','all'):
        if not (api/'extension_api.json').exists(): raise RuntimeError('Build the patched editor and dump its API first')
        for sdk in sdks:
            run([scons, 'platform=ios', f'target={target}', 'arch=arm64', f'ios_simulator={"yes" if sdk == "simulator" else "no"}', f'custom_api_file={api/"extension_api.json"}', 'api_version=4.7', f'-j{args.jobs}'], cpp)
    if args.stage in ('package','all'):
        frameworks = []; bindings = []
        headers = cache/'headers'; headers.mkdir(exist_ok=True)
        shutil.copytree(cpp/'include', headers, dirs_exist_ok=True)
        shutil.copytree(cpp/'gen/include', headers, dirs_exist_ok=True)
        # Both XCFrameworks expose this C ABI header. A shared include guard is
        # needed because upstream's pragma once sees them as different files.
        interface = '#ifndef HOG_GDEXTENSION_INTERFACE_H\n#define HOG_GDEXTENSION_INTERFACE_H\n' + (api/'gdextension_interface.h').read_text() + '\n#endif\n'
        (headers/'gdextension_interface.h').write_text(interface)
        for sdk in sdks:
            wrapper = cache/f'framework-{sdk}'
            shutil.copytree(ROOT/'framework', wrapper, dirs_exist_ok=True)
            (wrapper/'libgodot').mkdir(exist_ok=True)
            suffix = '.simulator' if sdk == 'simulator' else ''
            shutil.copyfile(source/f'bin/libgodot.ios.{target}.arm64{suffix}.a', wrapper/'libgodot/libgodot.a')
            (wrapper/'libgodot/gdextension_interface.h').write_text(interface)
            header = re.sub(r'"(?:core/extension/)?gdextension_interface.gen.h"', '<libgodot/gdextension_interface.h>', (source/'core/extension/libgodot.h').read_text())
            (wrapper/'libgodot/libgodot.h').write_text(header)
            build = output/sdk
            run(['xcodebuild', '-project', wrapper/'libgodot.xcodeproj', '-scheme', 'libgodot', '-configuration', args.configuration,
                 '-destination', 'generic/platform=iOS Simulator' if sdk == 'simulator' else 'generic/platform=iOS',
                 'ARCHS=arm64', 'ONLY_ACTIVE_ARCH=YES', 'CODE_SIGNING_ALLOWED=NO', 'ENABLE_MODULE_VERIFIER=NO',
                 f'CONFIGURATION_BUILD_DIR={build}', 'build'])
            frameworks += ['-framework', build/'libgodot.framework']
            library = cpp/f'bin/libgodot-cpp.ios.{target}.arm64{suffix}.a'
            # CocoaPods needs the same library basename in every SDK slice.
            packaged_library = build/'libgodot-cpp.a'
            shutil.copyfile(library, packaged_library)
            bindings += ['-library', packaged_library, '-headers', headers]
        for name, inputs in [('libgodot', frameworks), ('libgodot-cpp', bindings)]:
            target_path = output/f'{name}.xcframework'
            if target_path.exists(): shutil.rmtree(target_path)
            run(['xcodebuild', '-create-xcframework', *inputs, '-output', target_path])
            archive = output/f'{name}.xcframework.zip'
            run(['ditto', '-c', '-k', '--sequesterRsrc', '--keepParent', target_path, archive])
        provenance = {'qualification':'unqualified', 'engineRevision':engine_ref, 'bindingsRevision':cpp_ref, 'patches':series,
                      'apiSha256':hashlib.sha256((api/'extension_api.json').read_bytes()).hexdigest(),
                      'sourceDiffSha256': source_diff_sha256(source),
                      'bridgeRevision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
                      'bridgeDirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT)),
                      'configuration':args.configuration, 'sdks':sdks, 'sourceMode':'development-checkout' if args.source else 'pinned-source-and-patches', 'sourceDirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=source)),
                      'xcode':subprocess.check_output(['xcodebuild','-version'],text=True).strip(),
                      'artifacts':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.glob('*.zip')}}
        (output/'provenance.json').write_text(json.dumps(provenance, indent=2)+'\n')

if __name__ == '__main__': main()
