---
name: bulk-reader
description: Delegate bulk file reading to a separate Claude Sonnet or Codex Terra worker. Use for files over 350 lines, questions across 3+ files, or large diffs. No AiKA required.
---

Call the bundled `scripts/bulk-read`; do not read the corpus into your own context first.
Resolve the script relative to this skill file: `../../scripts/bulk-read` (an absolute path).
In Claude Code, `${CLAUDE_PLUGIN_ROOT}/scripts/bulk-read` also resolves it.
Do not assume the current working directory is the plugin directory.

Choose `--backend claude` when running in Claude Code and `--backend codex` when running in Codex.
Honor an explicitly configured `SHUNT_BACKEND` by omitting `--backend` instead.
Never select a backend merely because its binary is installed.

```bash
"<absolute-plugin-root>/scripts/bulk-read" --backend claude --question "<question>" --paths <file1> <file2>
"<absolute-plugin-root>/scripts/bulk-read" --backend codex --question "<question>" --paths <file1> <file2>
```

Defaults are `sonnet` and `gpt-6.1-terra`; `--model` overrides the model.
Each invocation uses a fresh, isolated CLI session with the selected CLI's authentication.
Files are sent directly to that worker through stdin; only the answer enters your context.
Worker tokens still count toward that account's usage. Do not claim total-token savings.
Verify exact values and line numbers with targeted reads before editing.
If invocation fails, report the error. Do not silently switch providers or models.
Keep debugging, architectural decisions, and small targeted reads in the main agent.
