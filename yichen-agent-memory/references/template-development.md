> Paths used in commands are relative to the parent skill directory. Read this reference only for the route selected in SKILL.md.

## Upgrade Or Publish Workflow

When updating the public template repository:

1. Work in the `agent-memory-vault` repository.
2. Add or update only public-safe scripts, templates, docs, and fake examples.
3. Keep real user memory in the private vault.
4. Run:

```bash
python3 -m py_compile scripts/*.py scripts/memoryctl
python3 -m unittest tests.test_memory_v2_core tests.test_memoryctl
python3 scripts/agent_memory_check.py --skip-state-db
git diff --check
rg -n "/Users/|sk-[A-Za-z0-9]|token|secret|cookie|password|\\.sqlite|\\.db|zvec" .
```

5. Inspect `git diff` before committing.
6. Commit and push only after the leak check is clean or every match is confirmed to be a harmless example or warning.
