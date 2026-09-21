> Paths used in commands are relative to the parent skill directory. Read this reference only for the route selected in SKILL.md.

## Install And Upgrade Workflow

Clone or update the public source, then use the platform installer. On POSIX, always run the read-only plan first:

```bash
git clone https://github.com/mcncarl/agent-memory-vault.git
cd agent-memory-vault
python3 scripts/install-posix.py --plan \
  --memory-root "/absolute/path/to/Agent Memory" \
  --git-root "/absolute/path/to/git-root" \
  --host codex --host claude --json
```

The plan must identify fresh versus upgrade, the canonical Vault/config/state paths, Runtime changes, config migration, state blockers, and every exact legacy-claim disposition. It must run the source checkout's `agent_memory_migrate.py` with an existing Python 3.10+ (select one with `--python /absolute/python` when needed), so a live v1 Runtime does not need to contain the new migrator. It must not create templates, change the Vault, mutate SQLite, install Hooks, or publish `ready`.

For apply, use only new private backup paths/directories and the exact reviewed disposition JSON requested by plan. Never overwrite a prior backup:

```bash
python3 scripts/install-posix.py --apply \
  --memory-root "/absolute/path/to/Agent Memory" \
  --git-root "/absolute/path/to/git-root" \
  --host codex --host claude \
  --config-backup "/new/private/config-before-v2.toml" \
  --state-backup "/new/private/state-before-v2.sqlite" \
  --disposition-file "/private/reviewed-dispositions.json" \
  --hook-backup-dir "/new/private/hook-backup" --json
```

Use only the inputs the plan requires. Both TOML and state missing is fresh; both present is upgrade; a half-present combination is ambiguous and must fail closed. Before installing Runtime files or touching the Vault, apply reruns the source state plan and verifies every blocker plus the exact reviewed disposition. A fresh install creates the template and initial Git baseline; an upgrade must never bootstrap, add template files, initialize/commit Git, or directly edit an existing Vault. It only validates the configured roots and required governance files. Existing Markdown governance is migrated later through Write Gateway v2. Apply then installs the Runtime into a closed transition, migrates config/state with online backup and exact CAS, installs selected Hooks, rebuilds/validates derived state, runs Doctor, then publishes `ready` only after the strong attestation passes.

On Windows 10/11 use `scripts/install-windows.ps1`; do not translate POSIX lock or Hook commands. The Windows writer remains unsupported if the current release explicitly reports a fail-closed platform boundary.

After installation, report the three storage layers separately:

- user-selected Markdown Vault and Git root;
- private Runtime/state root, normally `~/.config/agent-memory` on macOS/Linux;
- client-private state such as Ailu's Vault `.ailu/` and Home `~/.ailu/`, which is not formal memory.
