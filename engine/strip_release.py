#!/usr/bin/env python3
"""Strip local symbols from a Release framework, retaining a verified symbol backup."""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inspect_binary(path):
    data = path.read_bytes()
    if len(data) < 32 or struct.unpack_from('<I', data)[0] != 0xFEEDFACF:
        raise ValueError('Expected a thin 64-bit little-endian Mach-O: ' + str(path))
    _, cpu, subtype, kind, commands, command_bytes, _, _ = struct.unpack_from('<8I', data)
    if kind != 6:
        raise ValueError('Only dynamic frameworks may be stripped; static bindings must retain symbols')
    offset = 32
    sections = {}
    uuid = None
    symbols = None
    for _ in range(commands):
        cmd, size = struct.unpack_from('<II', data, offset)
        if size < 8 or offset + size > 32 + command_bytes:
            raise ValueError('Invalid Mach-O load command')
        if cmd == 0x19:  # LC_SEGMENT_64
            count = struct.unpack_from('<I', data, offset + 64)[0]
            for index in range(count):
                name, segment, _, length, start, _, _, _, flags, _, _, _ = struct.unpack_from(
                    '<16s16sQQ8I', data, offset + 72 + index * 80)
                # These sections exist only in memory, including thread-local BSS.
                if flags & 0xff in (0x1, 0xc, 0x12):
                    continue
                if start + length > len(data):
                    raise ValueError('Section extends beyond the binary')
                key = segment.rstrip(b'\0').decode() + ',' + name.rstrip(b'\0').decode()
                sections[key] = {'bytes': length, 'sha256': digest(data[start:start + length])}
        elif cmd == 0x1b:  # LC_UUID: keep the original symbolication identity.
            uuid = data[offset + 8:offset + 24].hex()
        elif cmd == 2:  # LC_SYMTAB
            _, _, _, count, _, strings = struct.unpack_from('<6I', data, offset)
            symbols = {'entries': count, 'stringBytes': strings}
        offset += size
    if not uuid or not sections or symbols is None:
        raise ValueError('Missing framework identity, sections or symbol table')
    def output(*args):
        return subprocess.check_output(['xcrun', *args, str(path)], text=True)
    exports = output('nm', '-gU')
    imports = output('nm', '-u')
    dependencies = output('otool', '-L').splitlines()[1:]
    return {
        'bytes': len(data), 'sha256': digest(data), 'uuid': uuid,
        'architecture': [cpu, subtype], 'sections': sections,
        'symbols': symbols, 'exportCount': len(exports.splitlines()),
        'exportsSha256': digest(exports.encode()), 'importsSha256': digest(imports.encode()),
        'dependencies': dependencies,
    }


def verify_unchanged(before, after):
    for key in ('uuid', 'architecture', 'sections', 'exportsSha256', 'importsSha256', 'dependencies'):
        if before[key] != after[key]:
            raise ValueError('Symbol stripping changed runtime content: ' + key)
    if after['bytes'] > before['bytes']:
        raise ValueError('Symbol stripping increased the binary size')


def strip_framework(framework, symbols_directory):
    """Mutate only the build output, never the input archive or installed dependency."""
    framework = Path(framework)
    symbols_directory = Path(symbols_directory)
    binary = framework / framework.stem
    before = inspect_binary(binary)
    symbols_directory.mkdir(parents=True, exist_ok=True)
    backup = symbols_directory / (binary.name + '.unstripped')
    report_path = symbols_directory / 'strip-report.json'
    if backup.exists() and report_path.exists():
        previous = json.loads(report_path.read_text())
        if (previous['after'] == before and
                digest(backup.read_bytes()) == previous['before']['sha256']):
            return previous
    # Refuse to overwrite the only surviving unstripped copy on repeated packaging.
    if backup.exists() and digest(backup.read_bytes()) != before['sha256']:
        raise ValueError('Symbol backup already exists for a different input: ' + str(backup))
    shutil.copy2(binary, backup)
    dsym = framework.with_name(framework.name + '.dSYM')
    if dsym.exists():
        shutil.copytree(dsym, symbols_directory / dsym.name, dirs_exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='strip-', dir=binary.parent) as temporary:
        candidate = Path(temporary) / binary.name
        shutil.copy2(binary, candidate)
        subprocess.run(['xcrun', 'strip', '-S', '-x', str(candidate)], check=True, capture_output=True, text=True)
        after = inspect_binary(candidate)
        verify_unchanged(before, after)
        candidate.replace(binary)
    report = {'command': ['xcrun', 'strip', '-S', '-x'], 'before': before, 'after': after,
              'bytesSaved': before['bytes'] - after['bytes'], 'runtimeContentUnchanged': True,
              'symbolBackup': backup.name, 'dSYMAvailable': dsym.exists()}
    report_path.write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('framework', type=Path)
    parser.add_argument('--symbols-directory', required=True, type=Path)
    args = parser.parse_args()
    result = strip_framework(args.framework, args.symbols_directory)
    print(json.dumps({key: result[key] for key in ('bytesSaved', 'runtimeContentUnchanged', 'dSYMAvailable')}))
