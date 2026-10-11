"""Synthetic CI helper integration tests. No private ERP code, keys or live providers."""
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/hamkar-private-exact-sha-ci.yml'
JOBS = ('postgres-orm-smoke', 'phase3-external-monitoring-e2e',
        'phase3-11task-synthetic-convergence')
PROBE = 'SYNTHETIC_NON_SECRET_PROBE_b44e17'


class SyntheticRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = yaml.safe_load(WORKFLOW.read_text(encoding='utf-8'))

    def runner_source(self, name):
        steps = self.workflow['jobs'][name]['steps']
        wrapper = next(s['run'] for s in steps if
                       'HAMKAR_PROXY_JOB_DONE' in s.get('run', ''))
        found = re.search(r"<<'PY'\n(.*?)\nPY(?:\n|$)", wrapper, re.DOTALL)
        self.assertIsNotNone(found)
        compile(found.group(1), 'synthetic_nested_runner.py', 'exec')
        return found.group(1)

    def run_case(self, name, steps, *, setup=None, job_env=None, token_probe=False):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / 'hamkar/.github/workflows').mkdir(parents=True)
            (home / 'runner_temp').mkdir()
            outer_env = home / 'github_env_from_real_runner'
            original = 'OUTER_VARIABLE=untouched\n'
            outer_env.write_text(original)
            (home / 'hamkar/.github/workflows/postgres-orm-safety.yml').write_text(
                yaml.safe_dump({'jobs': {name: {'steps': steps,
                                               'env': job_env or {}}}}))
            script = home / 'proxy.py'
            script.write_text(self.runner_source(name))
            if setup:
                setup(home)
            env = {**os.environ, 'GITHUB_ENV': str(outer_env),
                   'RUNNER_TEMP': str(home / 'runner_temp'),
                   'HAMKAR_PROXY_JOB': name}
            if token_probe:
                env['ACTIONS_RUNTIME_TOKEN'] = PROBE
                env['GITHUB_TOKEN'] = PROBE
                env['GH_TOKEN'] = PROBE
            proc = subprocess.run([sys.executable, str(script)], cwd=home, env=env,
                                  capture_output=True, text=True, timeout=12)
            return proc, (home / 'next_step').exists(), outer_env.read_text()

    def test_step_stdout_stderr_and_untrusted_names_never_reach_public_log(self):
        for name in JOBS:
            with self.subTest(job=name):
                result, next_step, host_env = self.run_case(name, [
                    {'name': PROBE + '\n::error::FORGED_ANNOTATION',
                     'run': 'echo ' + PROBE + '; echo ' + PROBE + ' >&2'},
                    {'run': 'touch ../next_step'},
                ])
                self.assertEqual(result.returncode, 0)
                self.assertTrue(next_step)
                self.assertNotIn(PROBE, result.stdout + result.stderr)
                self.assertNotIn('FORGED_ANNOTATION', result.stdout + result.stderr)
                self.assertEqual(host_env, 'OUTER_VARIABLE=untouched\n')

    def test_failing_private_script_does_not_dump_output(self):
        for name in JOBS:
            with self.subTest(job=name):
                result, ran, host_env = self.run_case(name, [
                    {'run': 'echo ' + PROBE + '; echo ' + PROBE + ' >&2; exit 7'},
                    {'run': 'touch ../next_step'},
                ])
                self.assertEqual(result.returncode, 7)
                self.assertFalse(ran)
                self.assertNotIn(PROBE, result.stdout + result.stderr)
                self.assertEqual(host_env, 'OUTER_VARIABLE=untouched\n')

    def test_env_isolation_and_two_sequential_exports(self):
        for name in JOBS:
            with self.subTest(job=name):
                result, ran, outer = self.run_case(name, [
                    {'run': 'echo "HAMKAR_PG_DUMP_BIN=$RUNNER_TEMP/dump" >> "$GITHUB_ENV"'},
                    {'run': 'test "$HAMKAR_PG_DUMP_BIN" = "$RUNNER_TEMP/dump" && echo "HAMKAR_PG_RESTORE_BIN=$RUNNER_TEMP/restore" >> "$GITHUB_ENV"'},
                    {'run': 'test "$HAMKAR_PG_RESTORE_BIN" = "$RUNNER_TEMP/restore" && touch ../next_step'},
                ])
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertTrue(ran)
                self.assertEqual(outer, 'OUTER_VARIABLE=untouched\n')

    def test_nested_runtime_tokens_stripped(self):
        for name in JOBS:
            with self.subTest(job=name):
                result, ran, outer = self.run_case(name, [
                    {'run': 'test -z "${ACTIONS_RUNTIME_TOKEN:-}" && test -z "${GITHUB_TOKEN:-}" && test -z "${GH_TOKEN:-}" && touch ../next_step'},
                ], token_probe=True)
                self.assertEqual(result.returncode, 0)
                self.assertTrue(ran)
                self.assertEqual(outer, 'OUTER_VARIABLE=untouched\n')

    def test_multiline_traversal_and_unknown_env_exports_refused(self):
        bad = ['HAMKAR_PG_DUMP_BIN<<END\n/private/data\nEND',
               'BASH_ENV=/tmp/inject',
               'HAMKAR_PG_DUMP_BIN=/etc/passwd',
               'HAMKAR_PG_DUMP_BIN=relative',
               'HAMKAR_PG_DUMP_BIN=$(touch ../next_step)',
               'HAMKAR_TEST_BROWSER=/bin/sh']
        for name in JOBS:
            for value in bad:
                with self.subTest(job=name, value=value):
                    # A synthetic producer writes hostile bytes to the isolated env.
                    result, ran, outer = self.run_case(name, [
                        {'run': 'printf "%s\n" ' + "'" + value.replace("'", "'\\''") + "'" + ' >> "$GITHUB_ENV"'},
                        {'run': 'touch ../next_step'},
                    ])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(ran)
                    self.assertEqual(outer, 'OUTER_VARIABLE=untouched\n')

    def test_symlink_inside_runner_temp_refused(self):
        def setup(home):
            (home / 'runner_temp/destination').mkdir()
            (home / 'runner_temp/link').symlink_to(home / 'runner_temp/destination')
        for name in JOBS:
            with self.subTest(job=name):
                result, ran, _ = self.run_case(name, [
                    {'run': 'echo "HAMKAR_PG_DUMP_BIN=$RUNNER_TEMP/link/pg_dump" >> "$GITHUB_ENV"'},
                    {'run': 'touch ../next_step'},
                ], setup=setup)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(ran)

    def test_yaml_unsupported_semantics_and_hostile_job_env_refused(self):
        cases = [{'uses': 'hostile/unknown@v1'},
                 {'run': 'touch ../next_step', 'if': 'success()'},
                 {'run': 'touch ../next_step', 'shell': 'python'},
                 {'run': 'touch ../next_step', 'working-directory': '/tmp'},
                 {'run': 'touch ../next_step', 'continue-on-error': True},
                 {'run': 'touch ../next_step', 'timeout-minutes': 0}]
        for name in JOBS:
            for bad in cases:
                with self.subTest(job=name, bad=bad):
                    result, ran, _ = self.run_case(name, [bad, {'run': 'touch ../next_step'}])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse(ran)
            result, ran, _ = self.run_case(name, [{'run': 'touch ../next_step'}],
                                            job_env={'BASH_ENV': '/tmp/inject'})
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(ran)
            result, ran, _ = self.run_case(name, [
                {'run': 'touch ../next_step', 'env': {'BASH_ENV': '/tmp/inject'}}])
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(ran)

    def test_supported_uses_are_skipped_with_explicit_parity_gap(self):
        for name in JOBS:
            with self.subTest(job=name):
                result, ran, _ = self.run_case(name, [
                    {'uses': 'actions/checkout@mock'},
                    {'uses': 'actions/upload-artifact@v4'},
                    {'run': 'touch ../next_step'},
                ])
                self.assertEqual(result.returncode, 0)
                self.assertTrue(ran)
                self.assertIn('skipped_non_run_steps=2', result.stdout)

    def test_synthetic_recovery_evidence_0700_and_filename_refusal(self):
        name = JOBS[0]
        result, ran, _ = self.run_case(name, [
            {'env': {'HAMKAR_CI_EVIDENCE_OUTPUT':
                     '${{ runner.temp }}/hamkar-phase3-synthetic-drill-evidence.json'},
             'run': 'test "$(stat -c %a "$(dirname "$HAMKAR_CI_EVIDENCE_OUTPUT")")" = 700 && touch ../next_step'},
        ])
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(ran)
        result, ran, _ = self.run_case(name, [
            {'env': {'HAMKAR_CI_EVIDENCE_OUTPUT': '/tmp/private-data.zip'},
             'run': 'touch ../next_step'},
        ])
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(ran)

    def test_ref_and_label_injection_precheckout_refused(self):
        cases = [('f'*40, 'UID-4', 0), ('f'*39, 'UID-4', 2),
                 ('F'*40, 'UID-4', 2), ('$(touch INJECTED)', 'UID-4', 2),
                 ('f'*40, '$(touch INJECTED)', 2), ('f'*40, 'a\nb', 2)]
        for name in JOBS:
            guard = self.workflow['jobs'][name]['steps'][0]['run']
            for sha, label, expected in cases:
                with tempfile.TemporaryDirectory() as td:
                    result = subprocess.run(['bash', '-c', guard], cwd=td,
                                            capture_output=True, text=True, timeout=4,
                                            env={**os.environ, 'TARGET_SHA_INPUT': sha,
                                                 'TARGET_LABEL_INPUT': label})
                    self.assertEqual(result.returncode, expected)
                    self.assertFalse((Path(td) / 'INJECTED').exists())

    def test_exact_checked_out_sha_and_residual_auth_header_refused(self):
        # No network, no private checkout, synthetic git repository only.
        script = self.workflow['jobs'][JOBS[0]]['steps'][2]['run']
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'hamkar'
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture',
                            '-c', 'user.email=fixture@example.invalid', 'commit',
                            '--allow-empty', '-qm', 'synthetic'], check=True)
            head = subprocess.check_output(['git', '-C', str(repo),
                                            'rev-parse', 'HEAD'], text=True).strip()
            good = subprocess.run(['bash', '-c', script], cwd=tmp,
                                  env={**os.environ, 'TARGET_SHA_INPUT': head},
                                  text=True, capture_output=True, timeout=4)
            self.assertEqual(good.returncode, 0, good.stdout + good.stderr)
            wrong = subprocess.run(['bash', '-c', script], cwd=tmp,
                                   env={**os.environ, 'TARGET_SHA_INPUT': 'f' * 40},
                                   text=True, capture_output=True, timeout=4)
            self.assertNotEqual(wrong.returncode, 0)
            subprocess.run(['git', '-C', str(repo), 'config', '--local',
                            'http.https://github.com/.extraheader',
                            'Authorization: synthetic-only-value'], check=True)
            contaminated = subprocess.run(
                ['bash', '-c', script], cwd=tmp,
                env={**os.environ, 'TARGET_SHA_INPUT': head},
                text=True, capture_output=True, timeout=4)
            self.assertNotEqual(contaminated.returncode, 0)
            self.assertNotIn('synthetic-only-value',
                             contaminated.stdout + contaminated.stderr)

    def test_symlink_at_internal_github_env_target_refused(self):
        def setup(home):
            (home / 'runner_temp/hamkar-proxy-internal-env').symlink_to(
                home / 'github_env_from_real_runner')
        for name in JOBS:
            result, ran, outer = self.run_case(
                name, [{'run': 'touch ../next_step'}], setup=setup)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse(ran)
            self.assertEqual(outer, 'OUTER_VARIABLE=untouched\n')

    def test_public_artefact_and_checkout_contract(self):
        source = WORKFLOW.read_text()
        self.assertNotIn('actions/upload-artifact@', source)
        self.assertEqual(self.workflow['permissions'], {'contents': 'read'})
        self.assertEqual(self.workflow['jobs'][JOBS[0]]['services']['postgres']['image'],
                         'public.ecr.aws/docker/library/postgres:18')
        for name in JOBS:
            self.assertIs(self.workflow['jobs'][name]['steps'][1]['with']['persist-credentials'], False)


if __name__ == '__main__':
    unittest.main()
