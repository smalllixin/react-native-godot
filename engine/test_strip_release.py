import copy
from pathlib import Path
import subprocess
import tempfile
import unittest

from strip_release import inspect_binary, strip_framework, verify_unchanged


class ReleaseSymbolTests(unittest.TestCase):
    def test_preserves_executable_sections_exports_imports_uuid_and_backup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'fixture.c'
            source.write_text('''
                #include <stdio.h>
                static __thread int local_counter;
                __attribute__((noinline)) static int internal_work(int n) { return n + ++local_counter; }
                __attribute__((visibility("default"))) int entry(int n) { puts("fixture"); return internal_work(n); }
            ''')
            framework = root/'fixture.framework'
            framework.mkdir()
            binary = framework/'fixture'
            subprocess.run(['xcrun', 'clang', '-dynamiclib', '-g', '-O0', '-o', str(binary), str(source)], check=True)
            original = binary.read_bytes()
            report = strip_framework(framework, root/'symbols')
            self.assertLess(report['after']['bytes'], report['before']['bytes'])
            self.assertEqual((root/'symbols/fixture.unstripped').read_bytes(), original)
            self.assertTrue(report['runtimeContentUnchanged'])
            self.assertEqual(report['before']['uuid'], inspect_binary(binary)['uuid'])
            self.assertEqual(report['before']['exportCount'], report['after']['exportCount'])
            for key in ('sections', 'exportsSha256', 'importsSha256', 'uuid'):
                damaged = copy.deepcopy(report['after'])
                damaged[key] = None
                with self.assertRaisesRegex(ValueError, key):
                    verify_unchanged(report['before'], damaged)
            self.assertEqual(strip_framework(framework, root/'symbols'), report)
            self.assertEqual((root/'symbols/fixture.unstripped').read_bytes(), original)

    def test_rejects_non_macho(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'invalid'
            path.write_bytes(b'not a Mach-O')
            with self.assertRaises(ValueError):
                inspect_binary(path)


if __name__ == '__main__':
    unittest.main()
