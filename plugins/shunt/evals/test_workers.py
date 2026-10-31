"""Exercise the public scripts with fake CLI executables; no network or tokens."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
FAKE = r'''#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys, time
args = sys.argv[1:]
prompt = sys.stdin.read()
pathlib.Path(os.environ['CAPTURE']).write_text(json.dumps({
    'args': args, 'prompt': prompt, 'cwd': os.getcwd(),
    'nested': os.environ.get('CLAUDECODE'),
    'worker': os.environ.get('SHUNT_WORKER_ACTIVE')}))
behavior = os.environ.get('BEHAVIOR', 'ok')
if behavior == 'timeout':
    child = subprocess.Popen([sys.executable, '-c',
        "import os,time,pathlib;time.sleep(2);pathlib.Path(os.environ['MARKER']).touch()"])
    time.sleep(10)
if behavior == 'exit':
    print('worker failed', file=sys.stderr); sys.exit(7)
content = os.environ.get('CONTENT', '- UserService at file.ts:11')
result = {'content': content}
if behavior == 'empty': result = {'content': '   '}
if behavior == 'wrong-type': result = {'content': 123}
if behavior == 'missing': result = {}
if '--print' in args:
    envelope = {'type': 'result', 'subtype': 'success', 'is_error': False, 'structured_output': result}
    if behavior == 'error': envelope['is_error'] = True
    if behavior == 'limit': envelope['subtype'] = 'error_max_turns'
    print('not-json' if behavior == 'garbled' else json.dumps(envelope))
else:
    if behavior != 'no-final':
        pathlib.Path(args[args.index('--output-last-message')+1]).write_text(
            'not-json' if behavior == 'garbled' else json.dumps(result))
    print('event stream should never become code')
print('harmless stderr diagnostic', file=sys.stderr)
'''


class Workers(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.fake = self.root / 'fake cli'
        self.fake.write_text(FAKE)
        self.fake.chmod(0o755)
        self.reference = self.root / 'reference $(literal).ts'
        self.reference.write_text('export const café = `hello`;\n', encoding='utf-8')
        self.target = self.root / 'result.ts'
        self.target.write_text('ORIGINAL\n')
        self.env = {k: v for k, v in os.environ.items() if not k.startswith('SHUNT_')}
        self.env.update(SHUNT_CLAUDE_BIN=str(self.fake), SHUNT_CODEX_BIN=str(self.fake),
                        CAPTURE=str(self.root/'capture'), MARKER=str(self.root/'orphan'),
                        CLAUDECODE='1')

    def run_script(self, backend='claude', operation='bulk-read', extra=(), env=None):
        args = [str(PLUGIN/'scripts'/operation)]
        if backend is not None:
            args += ['--backend', backend]
        if operation == 'bulk-read':
            args += ['--question', 'List exports', '--paths', str(self.reference)]
        else:
            args += ['--spec', 'Generate a file', '--reference', str(self.reference),
                     '--target', str(self.target)]
        return subprocess.run(args+list(extra), env=self.env | (env or {}),
                              capture_output=True, text=True, timeout=10)

    def capture(self):
        return json.loads((self.root/'capture').read_text())

    def test_default_models_stdin_isolation_and_output(self):
        for backend, model in [('claude','sonnet'),('codex','gpt-6.1-terra')]:
            with self.subTest(backend=backend):
                result=self.run_script(backend)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout, '- UserService at file.ts:11')
                captured=self.capture(); args=captured['args']
                self.assertEqual(args[args.index('--model')+1], model)
                self.assertNotIn('café', ' '.join(args))
                self.assertIn('café', captured['prompt'])
                self.assertIsNone(captured['nested'])
                self.assertEqual(captured['worker'], '1')
                self.assertFalse(Path(captured['cwd']).exists())
                self.assertNotIn('harmless', result.stdout)
                if backend == 'claude':
                    self.assertEqual(args[args.index('--tools')+1], '')
                    self.assertIn('--safe-mode', args)
                else:
                    self.assertIn('--ignore-user-config', args)
                    self.assertIn('agents.enabled=false', args)
                    self.assertEqual(args[args.index('--sandbox')+1], 'read-only')

    def test_backend_and_model_overrides(self):
        for backend in ('claude', 'codex'):
            for extra, overrides, expected in [
                ((), {f'SHUNT_{backend.upper()}_MODEL':'custom'}, 'custom'),
                (('--model','explicit'), {f'SHUNT_{backend.upper()}_MODEL':'custom'}, 'explicit')]:
                with self.subTest(backend=backend, expected=expected):
                    r=self.run_script(None, extra=extra, env={'SHUNT_BACKEND':backend}|overrides)
                    self.assertEqual(r.returncode,0,r.stderr)
                    args=self.capture()['args']; self.assertEqual(args[args.index('--model')+1],expected)
        self.assertEqual(self.run_script('claude',env={'SHUNT_BACKEND':'codex'}).returncode,0)
        self.assertIn('--print',self.capture()['args'])

    def test_generation_preserves_fences_unicode_and_permissions(self):
        code='const doc = `\n```ts\n한글\n```\n`;\n'
        for backend in ('claude','codex'):
            with self.subTest(backend=backend):
                self.target.chmod(0o755)
                r=self.run_script(backend,'code-write',env={'CONTENT':code})
                self.assertEqual(r.returncode,0,r.stderr)
                self.assertEqual(r.stdout,'')
                self.assertEqual(self.target.read_text(),code)
                self.assertEqual(self.target.stat().st_mode & 0o777,0o755)

    def test_failures_never_replace_target(self):
        for backend in ('claude','codex'):
            failures=['exit','garbled','empty','wrong-type','missing']
            failures += ['error','limit'] if backend=='claude' else ['no-final']
            for behavior in failures:
                with self.subTest(backend=backend,behavior=behavior):
                    r=self.run_script(backend,'code-write',env={'BEHAVIOR':behavior})
                    self.assertNotEqual(r.returncode,0)
                    self.assertEqual(r.stdout,'')
                    self.assertEqual(self.target.read_text(),'ORIGINAL\n')

    def test_timeout_kills_child_and_preserves_target(self):
        import time
        for backend in ('claude','codex'):
            r=self.run_script(backend,'code-write',extra=('--timeout','1'),env={'BEHAVIOR':'timeout'})
            self.assertNotEqual(r.returncode,0)
            self.assertIn('timed out',r.stderr)
            self.assertEqual(self.target.read_text(),'ORIGINAL\n')
        time.sleep(2)
        self.assertFalse((self.root/'orphan').exists())

    def test_invalid_inputs_fail_before_launch(self):
        for extra, env in [(('--unknown','x'),{}),(('--model',),{}),
                           (('--timeout','0'),{}),((),{'SHUNT_TIMEOUT_SECONDS':'bad'}),
                           ((),{'SHUNT_MAX_PAYLOAD_BYTES':'2'}),
                           ((),{'SHUNT_MAX_PAYLOAD_BYTES':'bad'}),
                           ((),{'SHUNT_WORKER_ACTIVE':'1'}),
                           ((),{'SHUNT_CLAUDE_BIN':'nonexistent-shunt-cli'})]:
            with self.subTest(extra=extra,env=env):
                self.assertNotEqual(self.run_script(extra=extra,env=env).returncode,0)
                self.assertFalse((self.root/'capture').exists())
        for backend,env in [(None,{}),(None,{'SHUNT_BACKEND':'invalid'})]:
            self.assertNotEqual(self.run_script(backend,env=env).returncode,0)
        self.reference.unlink()
        self.assertNotEqual(self.run_script().returncode,0)
        self.assertFalse((self.root/'capture').exists())

    def test_symlink_target_rejected(self):
        real=self.root/'real'; real.write_text('KEEP')
        self.target.unlink(); self.target.symlink_to(real)
        r=self.run_script(operation='code-write')
        self.assertNotEqual(r.returncode,0)
        self.assertEqual(real.read_text(),'KEEP')
        self.assertFalse((self.root/'capture').exists())

    def test_multiple_references(self):
        other=self.root/'other'; other.write_text('other reference')
        r=self.run_script(operation='code-write',extra=('--reference',str(other)))
        self.assertEqual(r.returncode,0,r.stderr)
        task=json.loads(self.capture()['prompt'].split('\n')[-1])
        self.assertEqual(len(task['files']),2)
        self.assertEqual(task['files'][1]['content'],'other reference')

    def test_large_input_uses_stdin_not_argv(self):
        self.reference.write_text('x'*150000)
        r=self.run_script('codex')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertGreater(len(self.capture()['prompt']),150000)
        self.assertLess(len(str(self.capture()['args'])),5000)


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Workers))
    failed=len(result.failures)+len(result.errors)
    print(f'## {result.testsRun-failed} {failed}')
    sys.exit(not result.wasSuccessful())
