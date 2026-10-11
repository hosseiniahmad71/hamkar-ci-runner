"""Local-only regression tests for HamKar public CI proxy; no ERP source or tokens."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / '.github/workflows/hamkar-private-exact-sha-ci.yml'
JOBS = ('postgres-orm-smoke', 'phase3-external-monitoring-e2e',
        'phase3-11task-synthetic-convergence')


class ProxySecurityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = FILE.read_text(encoding='utf-8')
        cls.config = yaml.safe_load(cls.source)

    def test_workflow_surface(self):
        self.assertEqual(self.config['permissions'], {'contents': 'read'})
        self.assertEqual(set(self.config.get('on', self.config.get(True))),
                         {'workflow_dispatch'})
        self.assertNotIn('actions/upload-artifact@', self.source)
        for name in JOBS:
            steps = self.config['jobs'][name]['steps']
            self.assertIn('Validate dispatch inputs', steps[0]['name'])
            self.assertEqual(steps[1]['uses'],
                             'actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683')
            self.assertIs(steps[1]['with']['persist-credentials'], False)
            self.assertEqual(steps[1]['with']['repository'],
                             'hosseiniahmad71/Hamkar-erp')
            self.assertEqual(steps[3]['uses'],
                             'actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065')
            for step in steps:
                self.assertNotIn('inputs.target_ref', step.get('run', ''))
                self.assertNotIn('inputs.target_label', step.get('run', ''))

    def test_input_injection_negative_cases(self):
        examples = [('a' * 40, 'UI-D', 0),
                    ('a' * 39, 'UI-D', 2),
                    ('A' * 40, 'UI-D', 2),
                    ('not-sha', 'UI-D', 2),
                    ('$(touch INJECTED)', 'UI-D', 2),
                    ('a' * 40 + ';touch INJECTED', 'UI-D', 2),
                    ('a' * 40, '$(touch INJECTED)', 2),
                    ('a' * 40, 'x' * 65, 2)]
        for name in JOBS:
            guard = self.config['jobs'][name]['steps'][0]['run']
            with tempfile.TemporaryDirectory() as td:
                for sha, label, expected in examples:
                    with self.subTest(job=name, sha=sha, label=label):
                        env = {**os.environ, 'TARGET_SHA_INPUT': sha,
                               'TARGET_LABEL_INPUT': label}
                        p = subprocess.run(['bash', '-c', guard], cwd=td, env=env,
                                           capture_output=True, text=True, timeout=5)
                        self.assertEqual(p.returncode, expected, p.stdout + p.stderr)
                        self.assertFalse((Path(td) / 'INJECTED').exists())

    def runner(self, name):
        steps = self.config['jobs'][name]['steps']
        entry = next(s['run'] for s in steps if
                     'HAMKAR_PROXY_JOB_DONE' in s.get('run', ''))
        m = re.search(r"<<'PY'\n(.*?)\nPY(?:\n|$)", entry, re.DOTALL)
        self.assertIsNotNone(m)
        compile(m.group(1), 'proxy_runner.py', 'exec')
        return m.group(1)

    def simulate(self, name, steps):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'hamkar/.github/workflows').mkdir(parents=True)
            (root / 'runner_temp').mkdir()
            gh_env = root / 'github_env'
            gh_env.write_text('EXTERNAL_ACTION_VAR=unchanged\n')
            (root / 'hamkar/.github/workflows/postgres-orm-safety.yml').write_text(
                yaml.safe_dump({'jobs': {name: {'steps': steps}}}))
            script = root / 'nested_proxy.py'
            script.write_text(self.runner(name))
            env = {**os.environ, 'GITHUB_ENV': str(gh_env),
                   'RUNNER_TEMP': str(root / 'runner_temp'),
                   'HAMKAR_PROXY_JOB': name}
            p = subprocess.run([sys.executable, str(script)], cwd=root, env=env,
                               capture_output=True, text=True, timeout=10)
            return p, (root / 'second').exists()

    def test_export_propagation_and_unauthorized_values(self):
        for name in JOBS:
            with self.subTest(name=name):
                steps = [
                    {'run': 'echo "HAMKAR_PG_DUMP_BIN=$RUNNER_TEMP/pgdump" >> "$GITHUB_ENV"'},
                    {'run': 'test "$HAMKAR_PG_DUMP_BIN" = "$RUNNER_TEMP/pgdump" && touch ../second'},
                ]
                p, marker = self.simulate(name, steps)
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertTrue(marker)
            for line in ('BASH_ENV=/tmp/hijack',
                         'HAMKAR_PG_DUMP_BIN=/etc/passwd',
                         'HAMKAR_PG_DUMP_BIN=relative/file',
                         'HAMKAR_TEST_BROWSER=/bin/bash',
                         'HAMKAR_PG_DUMP_BIN=$(touch INJECTED)',
                         'HAMKAR_PG_DUMP_BIN'):
                with self.subTest(name=name, rejected=line):
                    command = "printf '%s\\n' " + repr(line) + ' >> "$GITHUB_ENV"'
                    p, marker = self.simulate(name, [
                        {'run': command}, {'run': 'touch ../second'}])
                    self.assertNotEqual(p.returncode, 0)
                    self.assertFalse(marker)

    def test_native_uses_parity_gaps(self):
        for name in JOBS:
            with self.subTest(name=name):
                p, marker = self.simulate(name, [
                    {'uses': 'unexpected/action@v1'}, {'run': 'touch ../second'}])
                self.assertNotEqual(p.returncode, 0)
                self.assertFalse(marker)
                p, marker = self.simulate(name, [
                    {'uses': 'actions/upload-artifact@v4'},
                    {'run': 'touch ../second'}])
                self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
                self.assertTrue(marker)
                self.assertIn('skipped_non_run_steps=1', p.stdout)

    def test_synthetic_evidence_dir_mode_and_bad_filename(self):
        name = 'postgres-orm-smoke'
        valid = [{
            'env': {'HAMKAR_CI_EVIDENCE_OUTPUT':
                    '${{ runner.temp }}/hamkar-phase3-synthetic-drill-evidence.json'},
            'run': 'test "$(stat -c %a "$(dirname "$HAMKAR_CI_EVIDENCE_OUTPUT")")" = 700 && touch ../second',
        }]
        p, marker = self.simulate(name, valid)
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertTrue(marker)
        invalid = [{
            'env': {'HAMKAR_CI_EVIDENCE_OUTPUT': '/tmp/unsafe-private-backup.json'},
            'run': 'touch ../second',
        }]
        p, marker = self.simulate(name, invalid)
        self.assertNotEqual(p.returncode, 0)
        self.assertFalse(marker)

    def test_expected_pg18_service(self):
        pg = self.config['jobs']['postgres-orm-smoke']
        self.assertEqual(pg['services']['postgres']['image'],
                         'public.ecr.aws/docker/library/postgres:18')


if __name__ == '__main__':
    unittest.main()
