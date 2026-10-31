# Portal AI Plugins — Shunt for Claude Code and Codex

This fork of [spotify/portal-ai-plugins](https://github.com/spotify/portal-ai-plugins)
provides **Shunt**, which delegates bulk file reads and repetitive code generation
to separate Claude Code or Codex CLI workers. It also retains the original
**Portal** workflows for Spotify Portal users.

| Plugin | Purpose | Hosts | Requirements |
| --- | --- | --- | --- |
| **[shunt](plugins/shunt/README.md)** | Bulk reading and boilerplate generation in a separate model context | Claude Code, Codex | Authenticated host CLI; no AiKA or Portal account |
| **portal** | Software catalog search, service briefings, Portal actions, and Fleetshift | Claude Code, Codex, Cursor, pi | Portal CLI and a Portal account |

The marketplace name remains `portal`; install `shunt@portal` to use Shunt.
Installing the `portal` plugin is optional and is not a prerequisite for Shunt.

## How Shunt works

```text
Main agent — planning, debugging, decisions, and review
  │
  ├── bulk-read  ── source files + question ── worker ── concise answer
  └── code-write ── references + spec ─────── worker ── generated file
```

| Running host | Backend | Default worker model |
| --- | --- | --- |
| Claude Code | `claude --print` | `sonnet` |
| Codex | `codex exec` | `gpt-6.1-terra` |

The main agent keeps its current model. The scripts read the supplied files and
send their content directly to the worker through stdin. With `--target`, generated
code is saved to disk and the main agent receives a short status message.

Workers run as **isolated CLI processes**, not native `Agent` / `spawn_agent`
subagents. They do not inherit the main conversation or project instructions;
provide necessary conventions in the spec and reference files. Worker usage still
counts against the selected account or API billing. Reducing the main agent's
context does not guarantee lower total token usage or cost.

Both hosts have synchronous pre-tool hooks that deny recognized bulk reads
(over 350 lines by default) and direct the main agent to `bulk-reader`. Codex's
hook covers shell reads through `exec_command` / `Bash` and supported direct read
tools; it allows bounded `head`, `tail`, and `sed -n` ranges. Code generation still
uses skill guidance. Both hosts keep debugging, architecture, and review in the main agent.

## Install and enable Shunt

Use **this fork** to get the Claude/Codex worker implementation.
Requirements: macOS or Linux, Bash, Python 3.9+, `jq` for Claude hooks, and a
signed-in CLI with access to the selected model. Tested with Claude Code 2.1.316
and Codex CLI 0.166.0.

### Claude Code

```bash
claude plugin marketplace add happyhappy-jun/portal-ai-plugins
claude plugin install shunt@portal --scope user
claude plugin list --json
```

Verify `shunt@portal` is version `0.4.0` or later and enabled. If it is disabled,
run `claude plugin enable shunt@portal --scope user`. Start a **new Claude Code
session**, then ask, for example:

```text
Use /shunt:bulk-reader to summarize the exported APIs in these large files.
Use /shunt:code-writer to generate tests following an existing test file.
```

### Codex

```bash
codex plugin marketplace add happyhappy-jun/portal-ai-plugins
codex plugin add shunt@portal
codex plugin list --json --marketplace portal
```

Verify `shunt@portal` is version `0.4.0` or later and `enabled: true`. If a previous
installation was disabled, enable Shunt in `/plugins` or set the existing
`[plugins."shunt@portal"]` entry to `enabled = true` in `~/.codex/config.toml`.
Start a **new Codex chat/session**. In Codex CLI, open `/hooks`, review the
Shunt hook from `hooks/codex.json`, and trust that exact definition. Installation
and `enabled: true` alone do not activate untrusted hooks; updated definitions
require review again. Then ask Codex to use Shunt's bulk-reader or code-writer
skill. The skills select the backend matching the host.

The Codex hook denies the original call before it executes and supplies a
`bulk-read --backend codex` command. It is a routing guardrail for recognized
readers, not a sandbox: arbitrary Python/Node scripts, dynamic shell expansion,
MCP readers, and writes to an already-running shell are not inspected. See
[hook coverage](plugins/shunt/README.md#host-differences).

### Migrating an existing Spotify marketplace

If `portal` already points to `spotify/portal-ai-plugins`, adding this fork under
the same marketplace name can fail. Inspect the registered source first:

```bash
claude plugin marketplace list --json
codex plugin marketplace list --json
```

To replace the source, remove the old marketplace in the relevant host, then run
that host's install commands above:

```bash
claude plugin marketplace remove portal --scope user
# or, for Codex:
codex plugin marketplace remove portal
```

**Claude marketplace removal also uninstalls its plugins and can delete their
saved options and data.** Preserve any needed plugin settings first. Reinstall
`portal@portal` too if you were using the Portal workflows, and verify enabled
states after reinstalling. CLI authentication is managed separately.

### Updating this fork later

```bash
# Claude Code
claude plugin marketplace update portal
claude plugin update shunt@portal --scope user

# Codex
codex plugin marketplace upgrade portal
codex plugin add shunt@portal
```

Restart the host session after updates. Existing chats may still have older skill
instructions loaded.

## Script usage and model overrides

From a checkout, run the following in your project directory. Replace the script
path with an absolute path if the plugin is installed elsewhere.

```bash
plugins/shunt/scripts/bulk-read --backend claude \
  --question "Which functions write to the database?" --paths src/service.ts src/db.ts

plugins/shunt/scripts/code-write --backend codex \
  --spec "Write unit tests following this example" \
  --reference tests/existing.test.ts --reference src/service.ts \
  --target tests/service.test.ts
```

Use `--model` per call, or set `SHUNT_CLAUDE_MODEL` / `SHUNT_CODEX_MODEL` to override
`sonnet` / `gpt-6.1-terra`. `SHUNT_BACKEND` can select a backend explicitly.
`--reference` is repeatable. Targets are replaced only after a successful,
non-empty structured result; failures and timeouts preserve existing files.
Review generated changes and run appropriate checks.

The workers use existing CLI authentication. In Claude, `ANTHROPIC_API_KEY` can
select API billing even when a subscription login is available. An API credit
error is not evidence that your subscription quota is exhausted. See the
[authentication troubleshooting and full configuration](plugins/shunt/README.md#authentication-troubleshooting).

## Optional Portal workflows

The original [Spotify Portal](https://portal.spotify.com) integration is independent
of Shunt. Install it only when you want catalog search, operational service context,
Portal actions, or Fleetshift repository transformations.

```bash
# Claude Code
claude plugin install portal@portal
# In a new session: /portal:setup

# Codex
codex plugin add portal@portal
# In a new chat: "Set up Spotify Portal for me."
```

| Workflow | Purpose |
| --- | --- |
| `setup` | Configure Portal CLI authentication |
| `doctor` | Run read-only readiness diagnostics |
| `search` | Search the software catalog and technical documentation |
| `service` | Produce an operational service briefing |
| `actions` | Discover, inspect, preview, and invoke Portal actions |
| `feedback` | Submit Portal CLI feedback |
| `fleetshift-create-shift` | Define a repository transformation with a dry-run preview |
| `fleetshift-run-shift` | Run, monitor, or stop a shift |
| `fleetshift-check-shift` | Inspect target and PR progress |
| `fleetshift-troubleshoot-shift` | Diagnose failed targets |
| `fleetshift-create-prs` | Open PRs from completed targets |

These workflows invoke `npx @spotify/portal-cli` and require Portal setup.
Cursor and pi support the **Portal** workflows only: register this repository in
your Cursor team marketplace, or run `pi install git:github.com/happyhappy-jun/portal-ai-plugins`
and invoke `/skill:setup`.

## Repository layout

```text
plugins/shunt/                Shunt skills, worker scripts, host hooks, and evals
  .claude-plugin/plugin.json  Claude Code manifest
  .codex-plugin/plugin.json   Codex manifest
skills/                      Original Portal and Fleetshift workflows
.claude-plugin/              Root Portal manifest and Claude marketplace
.codex-plugin/               Root Portal manifest for Codex
.agents/plugins/             Codex marketplace listing Portal and Shunt
.cursor-plugin/              Portal manifest for Cursor
package.json                 Portal-only pi package
```

## Validation

```bash
bash plugins/shunt/evals/run.sh
claude plugin validate --strict plugins/shunt
claude plugin validate --strict .
```

See the [Shunt README](plugins/shunt/README.md) for the worker contract, host
limitations, authentication details, and optional live context-size measurements.
