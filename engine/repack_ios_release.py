#!/usr/bin/env python3
"""Recover and strip receipt-verified installed Release artifacts without recompiling."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

from strip_release import digest, strip_framework


def inventory(root):
    result = {}
    for path in sorted(root.rglob('*')):
        if path.name == '.godot-receipt.json':
            continue
        if path.is_symlink():
            result[path.relative_to(root).as_posix()] = 'symlink:' + str(path.readlink())
        elif path.is_file():
            result[path.relative_to(root).as_posix()] = digest(path.read_bytes())
    return result


def archive(directory, destination):
    # Stable ordering and timestamps make recovery repeatable from the same inputs.
    with zipfile.ZipFile(destination, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        for path in sorted(directory.rglob('*')):
            if path.is_dir() and not path.is_symlink():
                continue
            info = zipfile.ZipInfo(path.relative_to(directory.parent).as_posix(), (1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.external_attr = path.lstat().st_mode << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            bundle.writestr(info, str(path.readlink()).encode() if path.is_symlink() else path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--installed-libs', required=True, type=Path)
    parser.add_argument('--profile', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    profile = json.loads(args.profile.read_text())
    if profile.get('artifactConfiguration') != 'Release':
        raise ValueError('Only Release profiles can be repackaged')
    output = args.output.resolve()
    if output.exists():
        raise ValueError('Choose a new output directory to preserve previous artifacts')
    inputs = {}
    for entry in profile['nativeArtifacts']:
        if entry['name'] not in ('libgodot', 'libgodot-cpp') or entry['destination_base_dir'] != 'ios/libs':
            raise ValueError('Expected iOS engine and binding artifacts only')
        source = args.installed_libs/entry['name']/entry['version']
        receipt = json.loads((source/'.godot-receipt.json').read_text())
        if receipt['archive'] != entry['shasum'] or receipt['files'] != inventory(source):
            raise ValueError('Installed artifact failed receipt verification: ' + entry['name'])
        inputs[entry['name']] = (source, receipt)
    if set(inputs) != {'libgodot', 'libgodot-cpp'}:
        raise ValueError('Both engine and bindings are required')
    output.mkdir(parents=True)
    symbols = output/'symbols'
    symbols.mkdir()
    (symbols/'input-profile.json').write_text(json.dumps(profile, indent=2) + '\n')
    reports = {}
    artifacts = {}
    for entry in profile['nativeArtifacts']:
        source, receipt = inputs[entry['name']]
        name = entry['name'] + '.xcframework'
        target = output/name
        shutil.copytree(source/name, target, symlinks=True)
        (symbols/(entry['name'] + '-input-receipt.json')).write_text(json.dumps(receipt, indent=2) + '\n')
        if entry['name'] == 'libgodot':
            for sdk, slice_name in [('device', 'ios-arm64'), ('simulator', 'ios-arm64-simulator')]:
                reports[sdk] = strip_framework(target/slice_name/'libgodot.framework', symbols/sdk)
        archive(target, output/entry['filename'])
        checksum = digest((output/entry['filename']).read_bytes())
        artifacts[entry['filename']] = checksum
        entry.update(version=profile['engine']['version'] + '-release-strip-' + checksum[:12], shasum=checksum, base_url='')
    archive(symbols, output/'libgodot.symbols.zip')
    provenance = {
        'qualification': 'unqualified', 'sourceMode': 'receipt-verified-installed-repack',
        'engineRevision': profile['engine']['ref'], 'sourceDiffSha256': profile['engine']['patchSha256'],
        'apiSha256': profile['bindings']['apiSha256'], 'configuration': 'Release', 'sdks': ['device', 'simulator'],
        'compatibilityMetadataSource': 'input-profile.json; this operation does not rebuild engine or bindings',
        'inputArchives': {name: receipt['archive'] for name, (_, receipt) in inputs.items()},
        'symbolStripping': reports, 'artifacts': artifacts,
        'symbolArchiveSha256': digest((output/'libgodot.symbols.zip').read_bytes()),
        'packagingRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=Path(__file__).parent, text=True).strip(),
        'packagingDirty': bool(subprocess.check_output(['git', 'status', '--porcelain'], cwd=Path(__file__).parent)),
        'packagingScriptSha256': {p.name: digest(p.read_bytes()) for p in (Path(__file__), Path(__file__).with_name('strip_release.py'))},
        'xcode': subprocess.check_output(['xcodebuild', '-version'], text=True).strip(),
    }
    (output/'provenance.json').write_text(json.dumps(provenance, indent=2) + '\n')
    (output/'profile.json').write_text(json.dumps(profile, indent=2) + '\n')
    print(json.dumps({'artifacts': artifacts, 'bytesSaved': {sdk: report['bytesSaved'] for sdk, report in reports.items()}}, indent=2))


if __name__ == '__main__':
    main()
