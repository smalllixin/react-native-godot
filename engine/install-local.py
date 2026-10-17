#!/usr/bin/env python3
"""Install a locally built candidate into this bridge checkout, never promote it."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess

root = Path(__file__).resolve().parent.parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--artifacts', type=Path, required=True)
args = parser.parse_args()
artifacts = args.artifacts.expanduser().resolve()
provenance = json.loads((artifacts/'provenance.json').read_text())
entries = []
env = os.environ.copy()
for name, variable in [('libgodot', 'LIBGODOT_XCFRAMEWORK_PATH'), ('libgodot-cpp', 'LIBGODOT_CPP_XCFRAMEWORK_PATH')]:
    filename = name+'.xcframework.zip'
    archive = artifacts/filename
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    if checksum != provenance['artifacts'][filename]:
        raise RuntimeError('Artifact differs from build provenance: '+filename)
    env[variable] = str(archive)
    entries.append({'name': name, 'filename': filename,
        'version': '4.7.2.hog.1-'+provenance['configuration'].lower()+'-'+checksum[:12],
        'base_url': '', 'shasum': checksum, 'destination_base_dir': 'ios/libs',
        'env': variable, 'no_unpack': 'false'})
profile = artifacts/'local-profile.json'
profile.write_text(json.dumps({'qualification':'unqualified', 'nativeArtifacts':entries}, indent=2)+'\n')
subprocess.run(['node', 'scripts/download-prebuilt.js', '--platform', 'ios', '--profile', str(profile)], cwd=root, env=env, check=True)
print('Installed unqualified candidate. Next run pod install in example/ios, then rebuild the harness.')
