> Paths used in commands are relative to the parent skill directory. Read this reference only for the route selected in SKILL.md.

## Audit And Maintenance

Run audit or Doctor when asked:

```bash
memoryctl --actor codex audit
memoryctl --actor codex doctor
```

Audit findings are review prompts, not authority to rewrite facts. Doctor is read-only by default. `doctor --repair-derived` may rebuild SQLite/FTS and Zvec only when requested and only from Markdown; it must not modify Markdown. Human global closeout, migration, incident recovery, and legacy-ledger disposition are maintenance operations, not automatic-writer fallbacks.

## Optional Semantic Retrieval

Install the tested `requirements-vector.lock`, then build and validate Zvec:

```bash
python3 scripts/agent_memory_zvec_index.py --scan --prune
python3 scripts/agent_memory_zvec_index.py --report
```

For durable offline use, copy or APFS-clone a pinned model snapshot into the private runtime, set `require_local_model = true`, and record a private model manifest with revision, sizes, and hashes. `doctor` should pass the local-model, manifest-integrity, dependency-lock, and real offline-query checks before calling the semantic layer hardened.

The unified search runs SQLite and Zvec in parallel, applies all filters after merging, and discards semantic neighbors beyond the configured distance threshold. Search hits are candidates; always read the Markdown source before treating a claim as true.

## Optional Automation

Only install global Codex hooks, a macOS LaunchAgent, or a Windows Task Scheduler task after the user has asked for automation.

- Stop is turn-scoped in both hosts. The Hook is quiet unless the current session owns a live, unexpired write intent; claims alone never trigger write authority.
- Claude must have the SessionStart bridge in the live settings and in any settings manager's persistent configuration; verify it alongside Stop and SessionEnd after provider switches.
- A shared setup lets high-level apply perform normal closeout. Stop is only a fail-closed recovery/continuation boundary for the current live intent. External dirty files, expired leases, stale fences, terminal-intent/active-claim mismatches, and unresolved closeout incidents must block rather than suggest a new claim.
- Both hosts should block normal completion when closeout fails, using their native protocols: Claude returns `decision: block`; Codex exits with code `2` and writes a continuation prompt to stderr. Claude SessionEnd can be a non-blocking fallback; Codex currently has no direct equivalent.
- Keep the outer Stop hook timeout slightly above the closeout timeout. For a 300-second closeout, use at least 320 seconds outside.
- Keep one write/closeout lock domain, one Git baseline, one path-fence ledger, one audit scheduler, one SQLite database, and one Zvec index across all clients.
- Let `agent_memory_audit_autorun.py --min-interval-days 7` decide whether audit is due.
- When the interval is due, autorun should run the content audit and then the read-only Doctor, persisting separate `latest-audit.json` and `latest-doctor.json` reports and notifying on either findings or infrastructure health drift.
- The weekly LaunchAgent must not use `--force`; otherwise closeout, hook, and launchd can run duplicate audits inside the same seven-day window.
- On Windows, use the installed `stop-hook.ps1`, `install-codex-hook.ps1`, and `audit-task.ps1` adapters; do not execute extensionless Python entrypoints directly or simulate `source .env` in PowerShell.
- Merge the memory command into existing `~/.codex/hooks.json`; never overwrite unrelated hooks.
- After changing a hook command, tell the user Codex may ask them to review/trust the new hook hash.
