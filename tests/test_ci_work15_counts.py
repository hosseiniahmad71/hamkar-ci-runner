"""Public numeric-summary boundary tests; no private ERP source or credentials."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
import yaml

WF = Path(__file__).resolve().parents[1] / '.github/workflows/phase3-final-exact-sha-hardened-proxy.yml'
GOOD = dict(tests=81, failures=0, errors=0, skipped=0, provenance_blobs=65, unchanged_runtime_trees=4)
SENTINEL = 'SYNTHETIC_PRIVATE_OUTPUT_MUST_NOT_APPEAR'


class Work15NumericCountsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = yaml.safe_load(WF.read_text())
        steps = config['jobs']['ui-d-specialist-605']['steps']
        step = next(s for s in steps if s.get('name') == 'Report actual Work15 numeric counts only')
        cls.source = re.search(r"<<'WORK15COUNTS'\n(.*?)\nWORK15COUNTS", step['run'], re.S).group(1)
        compile(cls.source, 'work15_counts_fixture', 'exec')

    def run_fixture(self, raw=None, mode=0o600, symlink=False):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / 'hamkar-work15-counts.json'
            if raw is not None:
                target.write_text(raw); target.chmod(mode)
            if symlink:
                hidden = root / 'private'; hidden.write_text(SENTINEL)
                target.symlink_to(hidden)
            result = subprocess.run([sys.executable, '-c', self.source],
                                    env={**os.environ, 'RUNNER_TEMP': tmp},
                                    capture_output=True, text=True, timeout=5)
            self.assertNotIn(SENTINEL, result.stdout + result.stderr)
            return result

    def test_actual_integer_counts_reported(self):
        result = self.run_fixture(json.dumps(GOOD))
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = json.loads(result.stdout.split('=', 1)[1])
        self.assertEqual(parsed, GOOD)

    def test_unknown_failed_skipped_boolean_and_wrong_count_refused(self):
        for data in ({**GOOD, 'secret': SENTINEL}, {**GOOD, 'failures': 1},
                     {**GOOD, 'skipped': 1}, {**GOOD, 'errors': 1},
                     {**GOOD, 'tests': 80}, {**GOOD, 'failures': False}):
            result = self.run_fixture(json.dumps(data))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_missing_symlink_and_world_readable_refused(self):
        for args in ({}, {'symlink': True}, {'raw': json.dumps(GOOD), 'mode': 0o644}):
            result = self.run_fixture(**args)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')

    def test_duplicate_oversized_and_malformed_refused(self):
        for raw in ('{"tests":81,"tests":81}', ' ' * 2049, SENTINEL,
                    json.dumps([SENTINEL]), json.dumps({**GOOD, 'tests': 81.0})):
            result = self.run_fixture(raw)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
