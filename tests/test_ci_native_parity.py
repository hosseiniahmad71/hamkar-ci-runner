"""Synthetic native/parity tests: no private ERP files or credentials."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / '.github/workflows/phase3-final-exact-sha-hardened-proxy.yml'
TARGET = 'e947a60afda84149187ba35b836583fa89eb8f3d'
JOBS = ('postgres-orm-smoke', 'phase3-external-monitoring-e2e',
        'ui-d-specialist-605', 'ui-d-pg18-chromium', 'ui-d-static')
MARK = 'SYNTHETIC_LOG_SENTINEL_92940_NOT_SECRET'


class NativeParityFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = yaml.safe_load(WF.read_text(encoding='utf-8'))

    def source(self, job):
        step = next(s for s in cls_steps(self.config, job)
                    if 'HAMKAR_PROXY_JOB_DONE' in s.get('run', ''))
        m = re.search(r"<<'PY'\n(.*?)\nPY(?:\n|$)", step['run'], re.S)
        self.assertIsNotNone(m)
        compile(m.group(1), 'nested_synthetic.py', 'exec')
        return m.group(1)

    def simulate(self, job, steps, *, fast=False, sleep_after=False):
        with tempfile.TemporaryDirectory() as tmp:
            wd = Path(tmp)
            (wd / 'hamkar/.github/workflows').mkdir(parents=True)
            (wd / 'runner_temp').mkdir()
            source = self.source(job)
            fname = ('ui-d-csv-safety.yml' if 'ui-d-csv-safety.yml' in source
                     else 'postgres-orm-safety.yml')
            (wd / 'hamkar/.github/workflows' / fname).write_text(
                yaml.safe_dump({'jobs': {job: {'steps': steps}}}))
            if fast:
                self.assertIn('limit * 60 if limit is not None else None', source)
                source = source.replace('limit * 60 if limit is not None else None',
                                        '0.2 if limit is not None else None')
            script = wd / 'runner.py'
            script.write_text(source)
            host_env = wd / 'host_env'
            host_env.write_text('KEEP=original\n')
            env = {**os.environ, 'RUNNER_TEMP': str(wd / 'runner_temp'),
                   'GITHUB_ENV': str(host_env), 'HAMKAR_PROXY_JOB': job,
                   'ACTIONS_RUNTIME_TOKEN': MARK, 'GITHUB_TOKEN': MARK,
                   'GH_TOKEN': MARK, 'GITHUB_SHA': 'a' * 40}
            proc = subprocess.run([sys.executable, str(script)], cwd=wd, env=env,
                                  capture_output=True, text=True, timeout=10)
            if sleep_after:
                time.sleep(1.0)
            return (proc, host_env.read_text(),
                    (wd / 'marker').exists(), (wd / 'orphan').exists())

    def test_all_five_compile_exact_sha_and_safe_native_surface(self):
        self.assertEqual(len(self.config['jobs']), 5)
        self.assertEqual(self.config['permissions'], {'contents': 'read'})
        self.assertEqual(set(self.config.get('on', self.config.get(True))), {'push'})
        for job in JOBS:
            steps = cls_steps(self.config, job)
            checkout = next(s for s in steps if s.get('uses', '').startswith('actions/checkout@'))
            self.assertEqual(checkout['with']['ref'], TARGET)
            self.assertEqual(checkout['with']['repository'], 'hosseiniahmad71/Hamkar-erp')
            self.assertIs(checkout['with']['persist-credentials'], False)
            self.assertEqual(steps[0]['env']['TARGET_SHA_INPUT'], TARGET)
            self.assertFalse(any('upload-artifact' in s.get('uses', '') for s in steps))
            self.assertIn('os.killpg(proc.pid, signal.SIGKILL)', self.source(job))
            self.assertIn('stdout=subprocess.DEVNULL', self.source(job))

    def test_synthetic_private_output_and_step_label_not_logged(self):
        for job in JOBS:
            p, host, marker, _ = self.simulate(job, [
                {'name': MARK + '\n::error::FAKE_ANNOTATION',
                 'run': 'echo ' + MARK + '; echo ' + MARK + ' >&2; touch ../marker'}])
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertTrue(marker)
            self.assertNotIn(MARK, p.stdout + p.stderr)
            self.assertNotIn('FAKE_ANNOTATION', p.stdout + p.stderr)
            self.assertEqual(host, 'KEEP=original\n')

    def test_runtime_tokens_removed(self):
        for job in JOBS:
            p, _, marker, _ = self.simulate(job, [{
                'run': 'test -z "${ACTIONS_RUNTIME_TOKEN:-}" && test -z "${GITHUB_TOKEN:-}" && test -z "${GH_TOKEN:-}" && touch ../marker'
            }])
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertTrue(marker)

    def test_unknown_uses_and_yaml_features_fail_closed(self):
        for job in JOBS:
            for bad in ({'uses': 'rogue/action@v1'},
                        {'run': 'touch ../marker', 'shell': 'pwsh'},
                        {'run': 'touch ../marker', 'env': {'BASH_ENV': '/tmp/rogue'}},
                        {'run': 'touch ../marker', 'if': 'success()'}):
                p, host, marker, _ = self.simulate(job, [bad])
                self.assertNotEqual(p.returncode, 0)
                self.assertFalse(marker)
                self.assertEqual(host, 'KEEP=original\n')

    def test_native_uses_explicitly_skipped(self):
        for job in JOBS:
            p, _, marker, _ = self.simulate(job, [
                {'uses': 'actions/checkout@fixture'},
                {'uses': 'actions/setup-python@fixture'},
                {'run': 'touch ../marker'}])
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertTrue(marker)
            self.assertIn('skipped_non_run_steps=2', p.stdout)

    def test_private_sha_override_only_for_ui_d_jobs(self):
        for job in JOBS[2:]:
            p, _, marker, _ = self.simulate(job, [
                {'run': 'test "$GITHUB_SHA" = "' + TARGET + '" && touch ../marker'}])
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            self.assertTrue(marker)
        for job in JOBS[:2]:
            self.assertNotIn("env['GITHUB_SHA'] =", self.source(job))

    def test_timeout_kills_child_process_groups(self):
        command = "python -c 'import time; time.sleep(0.75); open(\"../orphan\", \"w\").write(\"x\")' & sleep 5"
        for job in ('postgres-orm-smoke', 'ui-d-static'):
            p, host, marker, orphan = self.simulate(job, [
                {'run': command, 'timeout-minutes': 1},
                {'run': 'touch ../marker'}], fast=True, sleep_after=True)
            self.assertNotEqual(p.returncode, 0)
            self.assertFalse(marker)
            self.assertFalse(orphan)
            self.assertEqual(host, 'KEEP=original\n')
            self.assertNotIn(MARK, p.stdout + p.stderr)


def cls_steps(config, job):
    return config['jobs'][job]['steps']


if __name__ == '__main__':
    unittest.main()

