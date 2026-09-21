> Paths used in commands are relative to the parent skill directory. Read this reference only for the route selected in SKILL.md.

## Troubleshooting

- If search says the SQLite index is missing, run `agent_memory_index.py --init --scan --report`.
- If a managed command reports a transition or integrity failure, run `version --json`, the read-only migrator/installer plan, and Doctor. Never bypass it by running a direct script with alternate root/state environment variables.
- If apply reports a stale read token, stale fence, expired lease, or changed base, preserve current bytes, re-read, and prepare a new proposal.
- If closeout reports post-finalize content drift, leave the incident unresolved until an exact ADOPT for the same target succeeds; do not edit SQLite manually.
- If Zvec is slow or unavailable, use `--no-zvec` for search/reconcile or `--skip-zvec` for closeout.
- If Zvec parity fails, run `agent_memory_zvec_index.py --scan --prune` and then `--report`.
- If audit repeats the same finding, record a decision with `--ack`, `--ignore`, `--resolve`, or `--snooze`; finding IDs must remain stable as counts change.
- If Claude debug reports zero matching hooks after installation, check whether a provider switcher rewrote `~/.claude/settings.json`. Persist the hooks in that manager's common configuration and any live rollback copy, then restart it and verify the loaded matchers again.
- If doctor reports `needs_review` or `mtime_fallback`, do not fabricate a verification date. Classify structural/snapshot documents explicitly, use document dates only as provenance, and add `verified_at` only after checking real evidence.
- If Doctor reports Zvec hash mismatch, rebuild the derived index from the current Markdown/Git baseline; equal document counts alone do not prove fresh vectors.
- Legacy active claims are disposed only by the backed-up schema migrator using an exact reviewed disposition file. In v2, inspect the bound intent/lease/fence instead of treating claim age as write authority.
- If doctor reports `memory_remote_backup`, inspect the private-vault diff and leak scan before pushing. A clean local Git baseline is not a remote backup.
- If doctor reports `semantic_python_runtime`, recreate the private venv from the exact dependency lock with an available Python of the same supported minor version, then rerun the offline semantic probe.
