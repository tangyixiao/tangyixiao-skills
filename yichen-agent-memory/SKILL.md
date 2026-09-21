---
name: yichen-agent-memory
description: "安装、升级、检索或维护 Agent Memory Vault 共享记忆系统；用于明确的记忆系统任务。普通业务的历史回忆按 Vault 入口读取，不启动安装或维护流程。"
---

# Agent Memory Vault

## Overview

Use this skill to help a user install or operate the public Agent Memory Vault system. The vault can be shared by Claude Code and Codex: Markdown remains the single fact source, while each host keeps a thin rule and hook adapter. Treat the GitHub repository as the product source, and treat this skill as the Agent-facing runbook for setup, maintenance, and troubleshooting.

Repository: `https://github.com/mcncarl/agent-memory-vault`

## Safety Rules

- Never copy a user's real memory vault into a public repository.
- Never commit `.env`, SQLite databases, Zvec/vector stores, model caches, logs, API keys, cookies, tokens, passwords, private chat logs, customer data, or personal absolute paths.
- When migrating an existing memory system, migrate structure, scripts, and sanitized patterns only.
- Before publishing or pushing, run leak checks and inspect the diff.
- If a task involves deleting files, ask for explicit user permission first and use Trash, not permanent deletion.
- Never point Claude Code auto-memory at the formal vault. Either disable it or treat it as non-authoritative scratch memory.
- Shared cookies and tokens belong in a private config outside the vault and Git, with owner-only permissions; Agents should inject selected values into commands instead of printing the whole file.

## Runtime v2 Boundary

Before any normal command, run `memoryctl --actor <actor> version --json`. A managed Runtime is usable only when the response has `ready=true`, `runtime_api_version=2`, `writer_protocol_version=2`, a valid state-schema attestation, and a current Runtime/config/Hook integrity hash. During install or migration, normal commands must fail closed; do not bypass the transition marker with a direct Python entrypoint.

Markdown is the only fact source. SQLite/FTS, Zvec, claims, intents, receipts, and observations are control or derived state. Claims are a closeout/audit projection of an active write intent; they are never a lock or permission to edit. The supported automatic writers are `codex`, `claude`, and `ailu`, and all three compete for the same canonical path lease.

## Choose the requested operation

Read only the selected operation reference. Do not run installation, auditing, or repair as a side effect of an ordinary read.

| Task | Required reference |
|---|---|
| Search or read current memory | [Daily reads](references/daily-reads.md) |
| Add or update formal memory | [Write Gateway](references/write-gateway.md), plus the Vault's write policy before preparing a proposal |
| Install or upgrade the runtime | [Install and upgrade](references/install-upgrade.md) |
| Requested audit, semantic-index maintenance, or hook configuration | [Maintenance](references/maintenance.md); read only the relevant section |
| Work on the public-safe template source | [Template development](references/template-development.md); publication still needs the user's authorization |
| Diagnose a concrete failure or recover an unfinished transaction | [Troubleshooting](references/troubleshooting.md), then the affected operation's reference |

Formal writes always use `read-target → prepare → apply`; never edit first and claim later. Preserve per-action confirmation, path leases, CAS, and Stop Hook protection. Normal successful apply includes closeout. Search results remain candidates until current Markdown is reread.
