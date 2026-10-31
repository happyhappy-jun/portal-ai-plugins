---
name: code-writer
description: Delegate repetitive code generation to a separate Claude Sonnet or Codex Terra worker. Use for tests, configs, docstrings, and type stubs predictable from reference files. No AiKA required.
---

Call the bundled `scripts/code-write`; do not copy reference files into your own context first.
Resolve the script relative to this skill file: `../../scripts/code-write` (an absolute path).
In Claude Code, `${CLAUDE_PLUGIN_ROOT}/scripts/code-write` also resolves it.
Do not assume the current working directory is the plugin directory.

Choose `--backend claude` when running in Claude Code and `--backend codex` when running in Codex.
Honor an explicitly configured `SHUNT_BACKEND` by omitting `--backend` instead.

```bash
"<absolute-plugin-root>/scripts/code-write" --backend claude --spec "<spec>" --reference <reference-file> --target <output-file>
"<absolute-plugin-root>/scripts/code-write" --backend codex --spec "<spec>" --reference <reference-file> --target <output-file>
```

Defaults are `sonnet` and `gpt-6.1-terra`; `--model` overrides the model.
Repeat `--reference` to include both an existing example and the source under test.
Use `--target` so generated code goes to disk rather than through your context.
Create the target's parent directory first if needed. Existing regular files are replaced
only after a successful, non-empty structured response. Symlink targets are rejected.
Without `--target`, the script prints the complete generated file to stdout.

The worker is an isolated, one-shot CLI process using the selected CLI's authentication,
not a native Agent/spawn_agent call. It does not inherit this conversation or project instructions;
put necessary conventions in the spec and reference files. Worker usage is still billed/counts.
If invocation fails, report the error; do not silently change models or providers.
Review the diff and run relevant checks before accepting generated code.
Keep ambiguous implementation, architecture, and debugging in the main agent.
