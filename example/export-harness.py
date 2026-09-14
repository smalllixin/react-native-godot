#!/usr/bin/env python3
"""Export and clean-load the two repository-owned embedding fixtures."""
import argparse
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parent
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--godot', required=True)
parser.add_argument('--platform', choices=['ios','android'], default='ios')
args = parser.parse_args()
for variant, name in [('a', 'GodotTest'), ('b', 'GodotTest2')]:
    source = root/'harness'/variant
    subprocess.run([args.godot, '--headless', '--editor', '--path', str(source), '--import'], check=True, timeout=60)
    with tempfile.TemporaryDirectory() as temporary:
        stage = pathlib.Path(temporary)
        script = stage/'pack.gd'
        pack = stage/(name+'.pck')
        script.write_text('extends SceneTree\nfunc _initialize():\n var p = PCKPacker.new()\n assert(ProjectSettings.save_custom("res://project.binary") == OK)\n assert(p.pck_start(OS.get_cmdline_user_args()[0]) == OK)\n for f in ["project.godot", "project.binary", "main.tscn", "main.gd", ".godot/global_script_class_cache.cfg"]:\n  assert(p.add_file("res://"+f, "res://"+f) == OK)\n assert(p.flush() == OK)\n quit()\n')
        subprocess.run([args.godot, '--headless', '--path', str(source), '--script', str(script), '--', str(pack)], check=True)
        check = subprocess.run([args.godot, '--headless', '--path', str(stage), '--main-pack', str(pack), '--quit-after', '5'], capture_output=True, text=True, timeout=30)
        if check.returncode or 'ERROR:' in check.stdout+check.stderr:
            raise RuntimeError('Fixture clean-load failed: '+check.stdout+check.stderr)
        destination = root/'ios' if args.platform == 'ios' else root/'packs/android'
        destination.mkdir(parents=True, exist_ok=True)
        (destination/pack.name).write_bytes(pack.read_bytes())
        if args.platform == 'android':
            native = root/'android/app/src/main/assets'
            if native.exists(): (native/pack.name).write_bytes(pack.read_bytes())
        print('Validated fixture:', variant)
