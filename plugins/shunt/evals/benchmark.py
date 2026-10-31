"""Optional live comparison of corpus/output size, not total billed tokens."""
import json
import os
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parent
backend = os.environ.get('SHUNT_BACKEND')
if backend not in ('claude', 'codex'):
    raise SystemExit('Set SHUNT_BACKEND=claude or codex for live benchmarks.')
print('Context-size estimates (UTF-8 characters / 4); worker usage is NOT included.')
for case in json.loads((ROOT/'benchmarks.json').read_text())['benchmarks']:
    script = ROOT.parent/'scripts'/case['type']
    with tempfile.TemporaryDirectory(prefix='shunt-benchmark-') as directory:
        if case['type'] == 'bulk-read':
            paths = [ROOT/p for p in case['paths']]
            command = [str(script), '--backend', backend, '--question', case['question'],
                       '--paths', *map(str, paths)]
        else:
            paths = [ROOT/p for p in case['context_files']]
            command = [str(script), '--backend', backend, '--spec', case['spec'],
                       '--reference', str(ROOT/case['reference']),
                       '--target', str(Path(directory)/'generated.ts')]
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(f"{case['name']} failed: {result.stderr}")
        source = sum(len(p.read_text()) for p in paths)
        print(f"{case['name']}: source ~{(source+3)//4} tokens; "
              f"returned content ~{(len(result.stdout)+3)//4} tokens "
              '(excludes instructions, status, review, and worker input/output).')
