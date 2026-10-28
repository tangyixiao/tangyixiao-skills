---
name: external-model-agents
description: Delegate bounded tasks from Codex to models available through WorkBuddy, WorkBuddy AI, ZCode or OpenCode, and collect their results with a local executor. Use when the user requests one of these external models or agents; not for ordinary Codex native subagents.
---

# External Model Agents

Use the bundled Node executor to dispatch external agents while keeping task planning and acceptance in the current Codex chat. These agents have independent sessions, accounts and quotas. Do not substitute them into native `spawn_agent` model names.

Read [usage](references/usage.md) for commands, configuration, supported controls and troubleshooting. Run `node <skill-dir>/scripts/agent.mjs --help` to check the installed CLI before preparing a task.

## Choose and dispatch

1. Run offline `doctor` and list the requested source models. Distinguish installed, launchable, credential presence and successful real execution. Cached model lists must retain their source/time. Refresh metadata only when needed; do not turn discovery into inference or effort probes.
2. Select the exact source and model from that source current catalog. Record the requested work, allowed files, work directory, permission mode, timeout, and supported limits. Respect the user existing budget and authorization; ask only for genuinely missing cost boundaries. Do not interpret a past test allowance as permanent dispatch permission.
3. Use a dedicated Git worktree or explicit task directory for code changes. The executor cwd is not an OS sandbox. If a requested hard restriction is unsupported, stop that task before inference and explain it.
4. Submit a task spec with explicit `allowLive: true` only within the user authorized task and budget. Do not set it for discovery. Keep initial execution and any followup within the remaining budget. Do not retry or change providers/accounts automatically after errors.
5. Track the returned task ID. Wait for new events or a terminal state; use the exact native session for followup. A task in `awaiting_input` needs a decision, not a fabricated successful result. Cancel only through the executor task control.

## Accept results

Read the result and inspect the actual file diff or artifact. Run checks appropriate to the requested change. An agent statement, exit code 0, or text reply alone does not prove a coding task succeeded. Report model/source, changed files, checks run, known usage, and any unknown cost or live-verification limits.

Keep raw task/session data local. Never print credential files, tokens, complete provider configs, account identifiers or secret-bearing process environments. Provider errors may contain sensitive values; use the executor redacted output. Reused Connect code remains in its installed upstream package; do not bundle desktop authentication material.

## Practical limits

The first version is a skill with a local executor, not a Codex-native subagent provider or an installed MCP server. It can track jobs while the current Codex turn is running; automatic wakeup of an ended chat is not promised. Task timeouts and cancellation are separate from monetary caps. Only report a source as live-verified when a real task and its result have been checked in the current relevant environment.
