const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const crypto = require('node:crypto');
const { execFileSync, spawnSync } = require('node:child_process');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'godot-installer-test-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'scripts'));
  fs.copyFileSync(path.join(__dirname, '../download-prebuilt.js'), path.join(root, 'scripts/download-prebuilt.js'));
  fs.mkdirSync(path.join(root, 'payload'));
  fs.writeFileSync(path.join(root, 'payload/engine'), 'verified engine bytes');
  const archive = path.join(root, 'engine.zip');
  execFileSync('zip', ['-q', archive, 'engine'], { cwd: path.join(root, 'payload') });
  const sha = crypto.createHash('sha256').update(fs.readFileSync(archive)).digest('hex');
  const entry = { name: 'libgodot', version: 'test', filename: 'engine.zip', shasum: sha,
    destination_base_dir: 'ios/libs', env: 'TEST_GODOT_ARCHIVE', no_unpack: 'false' };
  const profile = path.join(root, 'profile.json');
  const writeProfile = () => fs.writeFileSync(profile, JSON.stringify({ nativeArtifacts: [entry] }));
  writeProfile();
  const run = (platform = 'ios') => spawnSync(process.execPath, ['scripts/download-prebuilt.js', '--platform', platform, '--profile', profile], {
    cwd: root, encoding: 'utf8', env: { ...process.env, TEST_GODOT_ARCHIVE: archive, GODOT_ARTIFACT_CACHE: path.join(root, 'cache') },
  });
  return { root, archive, entry, writeProfile, run, installed: path.join(root, 'ios/libs/libgodot/test/engine') };
}

test('rejects a mismatched archive without activating it', (t) => {
  const f = fixture(t);
  f.entry.shasum = '0'.repeat(64);
  f.writeProfile();
  const result = f.run();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Checksum mismatch/);
  assert.equal(fs.existsSync(f.installed), false);
  assert.equal(fs.existsSync(path.join(f.root, '.godot-toolchain.json')), false);
});

test('verifies installed bytes, repairs tampering, and reuses the verified cache offline', (t) => {
  const f = fixture(t);
  assert.equal(f.run().status, 0);
  fs.unlinkSync(f.archive);
  assert.match(f.run().stdout, /Verified installed/);
  fs.writeFileSync(f.installed, 'tampered');
  const result = f.run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.readFileSync(f.installed, 'utf8'), 'verified engine bytes');
  assert.match(f.run().stdout, /Verified installed/);
});


test('installing Android preserves the verified iOS toolchain', (t) => {
  const f = fixture(t);
  assert.equal(f.run().status, 0);
  f.entry.name = 'libgodot-android';
  f.entry.destination_base_dir = 'android/libs';
  f.writeProfile();
  assert.equal(f.run('android').status, 0);
  const installed = JSON.parse(fs.readFileSync(path.join(f.root, '.godot-toolchain.json'), 'utf8'));
  assert.deepEqual(installed.prebuiltFiles.map(entry => entry.name).sort(), ['libgodot', 'libgodot-android']);
  assert.equal(fs.readFileSync(f.installed, 'utf8'), 'verified engine bytes');
  assert.equal(f.run('ios').status, 1);
});
