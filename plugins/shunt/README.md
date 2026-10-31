# shunt

Route bulk reads and boilerplate generation from Claude Code or Codex to a
separate CLI worker. No AiKA, Portal CLI, Portal account, or hosted mode setup.

| Host / backend | Default worker model | Invocation |
|---|---|---|
| Claude Code / `claude` | `sonnet` | `claude --print` |
| Codex / `codex` | `gpt-6.1-terra` | `codex exec` |

These are independent CLI processes, not native `Agent` / `spawn_agent` calls.
The main conversation stays on its current model. Files go straight from the
script to the worker through stdin; only the answer or a file-write status comes
back to the main agent. Each call starts fresh and does not inherit conversation
history, project instructions, installed skills, or MCP tools. Supply all relevant
conventions through the specification and reference files.

## Requirements

- macOS or Linux, Bash, Python 3.9+, and `jq` for Claude hooks/evals.
- An authenticated `claude` or `codex` CLI with access to the selected model.
- Recent CLIs supporting the flags below. Tested with Claude Code 2.1.316 and
  Codex CLI 0.166.0. Claude uses `--safe-mode` and structured output; Codex uses
  `--ignore-user-config`, `--ephemeral`, and `--output-schema`.

The worker uses that CLI's existing authentication. Usage counts against the
selected account/plan or API billing; this is not free inference. In particular,
`ANTHROPIC_API_KEY` can select API billing even when Claude also has a subscription
login. See authentication troubleshooting below.

## Install

From this fork's marketplace:

```bash
# Claude Code
claude plugin marketplace add happyhappy-jun/portal-ai-plugins
claude plugin install shunt@portal

# Codex
codex plugin marketplace add happyhappy-jun/portal-ai-plugins
codex plugin add shunt@portal
```

If a marketplace named `portal` already points at Spotify's upstream repository,
update that source to this fork or use a local checkout for testing. Restart the
host after installation. The two skills select the backend matching their host;
a configured `SHUNT_BACKEND` takes precedence in the skill workflow.

For a local Claude test:

```bash
claude --plugin-dir ./plugins/shunt
```

For a local Codex test, add the checkout as a marketplace, then install `shunt@portal`.
The repository includes `.agents/plugins/marketplace.json` and Shunt has its own
`.codex-plugin/plugin.json`. Portal's root plugin and pi skills remain independent.

## Usage

Run from your project directory; input and output paths are relative to that directory.
Use an absolute path to the installed script when the plugin lives elsewhere.

```bash
plugins/shunt/scripts/bulk-read --backend claude \
  --question "Which methods write to the database?" --paths src/Service.ts src/Handler.ts

plugins/shunt/scripts/bulk-read --backend codex \
  --question "What does this module export?" --paths src/module.ts

plugins/shunt/scripts/code-write --backend claude \
  --spec "Write tests for UserService" \
  --reference tests/OrderTest.ts --reference src/UserService.ts \
  --target tests/UserTest.ts

plugins/shunt/scripts/code-write --backend codex \
  --spec "Generate a config stub following this reference" \
  --reference config/existing.yaml --target config/new.yaml
```

`--reference` is required and repeatable. Without `--target`, generated content goes
to stdout. With `--target`, the parent script atomically replaces the file only
after a successful non-empty structured result. Errors, missing responses, and
timeouts leave the existing target untouched. Its parent directory must exist;
symlink targets are rejected. Generated content, including embedded Markdown
fences, is preserved. Review the diff and run appropriate checks afterward.

## Configuration

| Setting | Default | Meaning |
|---|---|---|
| `--backend` / `SHUNT_BACKEND` | Required outside the host skill | `claude` or `codex`; no binary-based guessing |
| `--model` | Backend model below | Per-call model override |
| `SHUNT_CLAUDE_MODEL` | `sonnet` | Claude worker model |
| `SHUNT_CODEX_MODEL` | `gpt-6.1-terra` | Codex worker model |
| `SHUNT_CLAUDE_BIN` / `SHUNT_CODEX_BIN` | `claude` / `codex` | Executable path (not shell arguments) |
| `--timeout` / `SHUNT_TIMEOUT_SECONDS` | `180` | Maximum seconds per worker, including startup |
| `SHUNT_MAX_PAYLOAD_BYTES` | `400000` | UTF-8 request size ceiling; split larger batches |
| `SHUNT_MIN_LINES` | `350` | Claude large-read hook threshold |

Model precedence: `--model`, then the backend-specific environment variable, then
the default. No automatic model/provider fallback. Payloads travel through stdin,
so they do not depend on the command-line argument size limit.

Claude workers disable tools, customizations, MCP loading and persistence. Codex
workers use a temporary working directory, a read-only sandbox, disabled shell,
apps/plugins/memory/subagents/web search, and ignore user config while retaining
CLI authentication. Managed policies still apply. A custom Codex provider from
user config is therefore not loaded by this adapter.

Timeouts terminate the worker process group. A recursion marker prevents a worker
from invoking Shunt again. The main agent retains responsibility for debugging,
architecture, checking exact values, and reviewing generated code.

## Host differences

Claude includes the existing large-file `Read`/`Bash` hooks, redirecting to
`/shunt:bulk-reader`. Targeted reads are permitted by the Read hook. The Bash hook
is a heuristic, not a security boundary. Code generation uses skill guidance.

Codex uses the shared skills and scripts. The Claude-specific hooks do not enforce
Codex tool routing; do not assume the same automatic interception on both hosts.

## Authentication troubleshooting

`claude auth status` shows which authentication source is selected. An API credit
error does not imply your Claude subscription is exhausted. To test subscription
authentication without changing global settings, omit API credentials only for
that child process:

```bash
env -u ANTHROPIC_API_KEY -u ANTHROPIC_AUTH_TOKEN \
  plugins/shunt/scripts/bulk-read --backend claude \
  --question "List exports" --paths src/module.ts
```

For Codex, check `codex login status`. If a requested model is unavailable, choose
an accessible model with `--model`; Shunt does not silently substitute one.

## Validation

```bash
bash plugins/shunt/evals/run.sh
claude plugin validate --strict plugins/shunt
claude plugin validate --strict .

# Optional live context-size measurements; consumes account usage
SHUNT_BACKEND=codex bash plugins/shunt/evals/run.sh --benchmark
```

The offline suite exercises both CLIs through stubs, including model selection,
stdin delivery, structured responses, failures, process timeouts, and safe writes.
Live benchmarks stop on invocation errors. They estimate source/returned context
size only, excluding worker usage and main-agent review. The old AiKA benchmark
percentages do not establish savings for these backends; measure your workload.
