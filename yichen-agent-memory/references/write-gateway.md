> Paths used in commands are relative to the parent skill directory. Read this reference only for the route selected in SKILL.md.

## Daily Writes: Gateway Only

Supported automatic writers must never edit formal Markdown first and add a claim later. They must not call low-level `intent`, `claim`, `finalize`, or direct closeout mutation. The only normal write sequence is:

1. `write read-target` returns the full current bytes, Git base, scope, and a bound `read_token`.
2. Build one complete final Markdown proposal from those bytes. An UPDATE cannot replace a whole file with only the Agent's new paragraph.
3. `write prepare` runs source safety and reconcile, then acquires the canonical path lease and monotonic `fencing_token` without modifying Markdown.
4. Continue the write only for `ADD` or `UPDATE`. `NOOP` writes nothing; `MERGE_REQUIRED` or `ASK_USER` pauses that memory transaction for an explicit decision. Continue independent authorized task work; do not bypass the gateway or Stop Hook, or claim an unfinished memory transaction is complete.
5. Bind authorization to the exact proposal hashes, target, and confirmation reference, then call `write apply`.
6. Apply performs byte/Git CAS and invokes scoped closeout; closeout rechecks the fence and atomically records the Git-bound receipt, observation, claim completion, and terminal intent.

Every request/response uses `schema_version: 2`, and private content goes through stdin JSON rather than argv:

```bash
AGENT_MEMORY_SESSION_ID="host-session-id" \
memoryctl --actor codex write read-target --json <<'JSON'
{"schema_version":2,"target_relative_path":"项目/example.md","app_id":"example-app","project_id":"example-project"}
JSON

AGENT_MEMORY_SESSION_ID="host-session-id" \
memoryctl --actor codex write prepare --json <<'JSON'
{"schema_version":2,"summary":"bounded summary","proposal_markdown":"<完整最终 Markdown>","target_relative_path":"项目/example.md","app_id":"example-app","project_id":"example-project","read_token":"<read token>","source_class":"user_direct","knowledge_kind":"fact","asserted_by":"user","evidence_ref":"task:message-reference"}
JSON
```

Apply must resend the identical proposal, `proposal_id`, raw/canonical hashes, target, and positive `fencing_token`, plus `confirmed_by` and a confirmation reference tied to that exact proposal. If the user abandons a prepared proposal, use high-level `write cancel` with its proposal ID and fence. If a lease expires, re-read and prepare again; do not revive an old fence through a low-level command.

Manually maintained root governance files (`AGENTS.md`, `README.md`, `STRUCTURE.md`) use `app_id=agent-memory` and `project_id=agent-memory-vault`, and only Codex/Claude may write them. Ailu uses `app_id=ailu`, must send one real project ID or `global`, may use `global` only under `用户记忆/`, and cannot write root governance. `INDEX.md` is runtime-generated: do not submit manual proposals for it. Verify the generated index after a successful normal apply; do not run another closeout unless recovering or diagnosing an unfinished transaction. Read-only/review-before-edit tasks do not initiate memory writes.

For an existing Obsidian/manual edit, never overwrite it. Either re-read and prepare a new proposal against the current bytes, or let Codex/Claude use `adopt_external:true` with a user-bound confirmation when the proposal exactly equals the current dirty bytes. Adoption still runs safety, reconcile, lease/fence, CAS, Git, and closeout. Ailu cannot auto-adopt external edits.

Codex uses its current thread identity. Claude must receive its real session through the installed SessionStart bridge and must not inherit a Codex thread ID. Ailu must create its own session identity. Raw session IDs, prompts, proposal bodies, and secrets do not enter the control ledger.
