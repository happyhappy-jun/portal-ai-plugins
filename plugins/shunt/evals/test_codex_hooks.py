"""Behavior tests for the Codex pre-tool contract, using real files and hook stdin."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT/'hooks/check-codex-read.py'


class CodexHooks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='shunt hook ')
        self.addCleanup(self.temp.cleanup)
        self.cwd = Path(self.temp.name)
        (self.cwd/'large file.txt').write_text('large\n'*400)
        (self.cwd/'small.txt').write_text('small\n'*20)
        (self.cwd/'boundary.txt').write_text('edge\n'*350)
        (self.cwd/'unterminated.txt').write_text('line\n'*350+'last line')
        (self.cwd/'sub').mkdir()
        (self.cwd/'sub/large.txt').write_text('nested\n'*500)
        self.env = {k:v for k,v in os.environ.items() if not k.startswith('SHUNT_')}

    def invoke(self, data, tool='Bash', extra=None, env=None):
        payload = {'hook_event_name':'PreToolUse', 'tool_name':tool,
                   'cwd':str(self.cwd), 'tool_input':data}
        payload.update(extra or {})
        p = subprocess.run([sys.executable,str(HOOK)], input=json.dumps(payload),
                           capture_output=True,text=True,env=self.env | (env or {}), timeout=5)
        self.assertEqual(p.returncode,0,p.stderr)
        result = json.loads(p.stdout)
        self.assertNotIn('continue',result)
        self.assertNotIn('stopReason',result)
        if result:
            specific=result['hookSpecificOutput']
            self.assertEqual(specific['hookEventName'],'PreToolUse')
            self.assertEqual(specific['permissionDecision'],'deny')
            self.assertIn('--backend codex',specific['permissionDecisionReason'])
            self.assertIn('scripts/bulk-read',specific['permissionDecisionReason'])
        return bool(result)

    def test_bulk_shell_reads_denied(self):
        commands = [
            'cat "large file.txt"', '/bin/cat "large file.txt"',
            'cat -n small.txt "large file.txt"', 'less "large file.txt"', 'more "large file.txt"',
            'head -n 351 "large file.txt"', 'head -351 "large file.txt"',
            'tail --lines=400 "large file.txt"', 'tail -n +1 "large file.txt"',
            'head -n -1 "large file.txt"', 'head -c 50000 "large file.txt"',
            'tail -f -n 10 "large file.txt"', 'tail -n 10 -f "large file.txt"',
            "sed -n '1,400p' 'large file.txt'", "sed '1,5p' 'large file.txt'",
            "sed -n '1,$p' 'large file.txt'", "sed -n -e '1,400p' 'large file.txt'",
            'pwd && cat "large file.txt"', 'git status; cat "large file.txt"',
            'pwd\ncat "large file.txt"', 'cat "large file.txt" | cat',
            'cat "large file.txt" | head -n 10', 'cat < "large file.txt"',
            'cat "large file.txt" 2>/dev/null', 'LANG=C cat "large file.txt"',
            'env LANG=C cat "large file.txt"', 'command cat "large file.txt"',
            "bash -lc 'cat \"large file.txt\"'", 'cd sub && cat large.txt',
            'cat boundary.txt unterminated.txt',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertTrue(self.invoke({'command':command}),command)

    def test_targeted_and_non_read_commands_allowed(self):
        commands = [
            'cat small.txt', 'cat boundary.txt', 'cat missing.txt', 'git status',
            'rg UserService "large file.txt"', 'wc -l "large file.txt"',
            'head "large file.txt"', 'tail "large file.txt"', 'head -n 350 "large file.txt"',
            'head -20 "large file.txt"', 'tail --lines=20 "large file.txt"',
            "sed -n '100,120p' 'large file.txt'", "sed -n '12p' 'large file.txt'",
            "sed --quiet -e '1,20p' 'large file.txt'", 'cat "large file.txt" > copy.txt',
            'cat "large file.txt" 1> copy.txt',
            'echo "cat large file.txt"', 'python3 scripts/tool.py',
            str(ROOT/'scripts/bulk-read')+' --backend codex --question summary --paths "large file.txt"',
        ]
        for command in commands:
            with self.subTest(command=command):
                self.assertFalse(self.invoke({'command':command}),command)

    def test_codex_cmd_workdir_and_shell_argv(self):
        self.assertTrue(self.invoke({'cmd':'cat large.txt','workdir':'sub'},tool='exec_command'))
        self.assertTrue(self.invoke({'command':['bash','-lc','cat large.txt'],
                                     'workdir':str(self.cwd/'sub')},tool='shell'))
        self.assertFalse(self.invoke({'cmd':'head -n 5 large.txt','workdir':'sub'},tool='exec_command'))

    def test_direct_read_limit_and_offset(self):
        for tool in ('Read','read_file','read_text_file'):
            with self.subTest(tool=tool):
                self.assertTrue(self.invoke({'file_path':'large file.txt'},tool))
                self.assertTrue(self.invoke({'path':'large file.txt','offset':1},tool))
                self.assertTrue(self.invoke({'path':'large file.txt','limit':351},tool))
                self.assertTrue(self.invoke({'path':'large file.txt','limit':0},tool))
                self.assertFalse(self.invoke({'path':'large file.txt','offset':50,'limit':20},tool))

    def test_threshold_and_missing_final_newline(self):
        self.assertTrue(self.invoke({'command':'cat unterminated.txt'}))
        self.assertFalse(self.invoke({'command':'cat "large file.txt"'},env={'SHUNT_MIN_LINES':'500'}))
        self.assertTrue(self.invoke({'command':'cat small.txt'},env={'SHUNT_MIN_LINES':'10'}))
        self.assertTrue(self.invoke({'command':'cat "large file.txt"'},env={'SHUNT_MIN_LINES':'bad'}))

    def test_unrelated_inputs_do_not_grant_permissions(self):
        for data,tool,extra in [({},'Bash',{}),({'command':'cat "large file.txt"'},'apply_patch',{}),
                                ({'command':'cat "large file.txt"'},'Bash',{'hook_event_name':'PostToolUse'}),
                                ({'command':42},'Bash',{}),({'command':'cat "unterminated'},'Bash',{})]:
            self.assertFalse(self.invoke(data,tool,extra))

    def test_command_input_is_never_executed(self):
        self.assertFalse(self.invoke({'command':'touch SHUNT_SHOULD_NOT_EXIST'}))
        self.assertFalse((self.cwd/'SHUNT_SHOULD_NOT_EXIST').exists())
        (self.cwd/'fifo').touch()
        (self.cwd/'fifo').unlink()
        os.mkfifo(self.cwd/'fifo')
        self.assertFalse(self.invoke({'command':'cat fifo'}))

    def test_manifest_selects_only_codex_hooks(self):
        manifest=json.loads((ROOT/'.codex-plugin/plugin.json').read_text())
        self.assertEqual(manifest['hooks'],'./hooks/codex.json')
        hook=json.loads((ROOT/manifest['hooks']).read_text())['hooks']['PreToolUse'][0]
        import re
        for tool in ('Bash','exec_command','shell','Read'):
            self.assertIsNotNone(re.search(hook['matcher'],tool))
        self.assertIn('${PLUGIN_ROOT}',hook['hooks'][0]['command'])
        self.assertNotIn('async',hook['hooks'][0])
        claude=json.loads((ROOT/'hooks/hooks.json').read_text())
        self.assertNotIn('check-codex-read',json.dumps(claude))


if __name__=='__main__':
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(CodexHooks))
    failed=len(result.failures)+len(result.errors)
    print(f'## {result.testsRun-failed} {failed}')
    sys.exit(not result.wasSuccessful())
