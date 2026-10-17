#!/usr/bin/env node
// Verified, content-addressed native artifacts. No shell interpolation or checksum bypass.
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const crypto = require('node:crypto');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const args = process.argv.slice(2);
const value = (flag) => args.includes(flag) ? args[args.indexOf(flag) + 1] : undefined;
const profilePath = value('--profile') || process.env.GODOT_TOOLCHAIN_PROFILE;
const profile = profilePath ? JSON.parse(fs.readFileSync(profilePath, 'utf8')) : null;
const entries = profile ? profile.nativeArtifacts : JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf8')).prebuiltFiles;
const platform = value('--platform') || 'all';
const cache = process.env.GODOT_ARTIFACT_CACHE || path.join(os.homedir(), 'Library', 'Caches', 'react-native-godot');
const digest = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function inventory(directory, prefix = '') {
  const result = {};
  for (const entry of fs.readdirSync(path.join(directory, prefix), { withFileTypes: true })) {
    if (entry.name === '.godot-receipt.json') continue;
    const name = path.join(prefix, entry.name);
    if (entry.isSymbolicLink()) result[name] = 'symlink:' + fs.readlinkSync(path.join(directory, name));
    else if (entry.isDirectory()) Object.assign(result, inventory(directory, name));
    else result[name] = digest(path.join(directory, name));
  }
  return Object.fromEntries(Object.entries(result).sort());
}
try {
  if (!entries?.length) throw new Error('No native artifacts available for this profile. Build and record candidate checksums first.');
  fs.mkdirSync(cache, { recursive: true });
  const selected = entries.filter((entry) => platform === 'all' || entry.destination_base_dir.startsWith(platform + '/'));
  if (!selected.length) throw new Error('No native artifacts for platform: ' + platform);
  for (const entry of selected) {
    if (!/^[a-f0-9]{64}$/.test(entry.shasum)) throw new Error('Missing SHA-256 for ' + entry.name);
    const destination = path.join(root, entry.destination_base_dir, entry.name, entry.version);
    const receiptPath = path.join(destination, '.godot-receipt.json');
    if (fs.existsSync(receiptPath)) {
      const receipt = JSON.parse(fs.readFileSync(receiptPath, 'utf8'));
      if (receipt.archive === entry.shasum && JSON.stringify(receipt.files) === JSON.stringify(inventory(destination))) {
        console.log('Verified installed ' + entry.name + ' ' + entry.version);
        continue;
      }
    }
    const archive = path.join(cache, entry.shasum + '.zip');
    if (!fs.existsSync(archive) || digest(archive) !== entry.shasum) {
      const temporary = archive + '.download';
      const local = entry.env && process.env[entry.env];
      if (local) fs.copyFileSync(local, temporary);
      else if (!entry.base_url) throw new Error(`Build ${entry.name} with engine/build_android.py and set ${entry.env} to its verified archive`);
      else execFileSync('curl', ['--fail', '--location', '--silent', '--show-error', '--output', temporary, `${entry.base_url}${entry.version}/${entry.filename}`], { stdio: 'inherit' });
      if (digest(temporary) !== entry.shasum) { fs.unlinkSync(temporary); throw new Error('Checksum mismatch: ' + entry.name); }
      fs.renameSync(temporary, archive);
    }
    const staging = fs.mkdtempSync(path.join(cache, 'extract-'));
    try {
      if (entry.no_unpack === 'false') execFileSync('unzip', ['-q', archive, '-d', staging]);
      else fs.copyFileSync(archive, path.join(staging, entry.filename));
      fs.writeFileSync(path.join(staging, '.godot-receipt.json'), JSON.stringify({ archive: entry.shasum, files: inventory(staging) }));
      fs.mkdirSync(path.dirname(destination), { recursive: true });
      fs.rmSync(destination, { recursive: true, force: true });
      fs.cpSync(staging, destination, { recursive: true, verbatimSymlinks: true });
    } finally { fs.rmSync(staging, { recursive: true, force: true }); }
    console.log('Installed verified ' + entry.name + ' ' + entry.version);
  }
  if (profile) {
    const file = path.join(root, '.godot-toolchain.json');
    const previous = fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')).prebuiltFiles : [];
    const merged = new Map(previous.map(entry => [entry.name, entry]));
    for (const entry of selected) merged.set(entry.name, entry);
    fs.writeFileSync(file, JSON.stringify({ prebuiltFiles: [...merged.values()] }, null, 2));
  }
} catch (error) {
  console.error(error.message);
  process.exitCode = 1;
}
