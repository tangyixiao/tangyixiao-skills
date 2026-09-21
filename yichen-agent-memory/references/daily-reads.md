> Paths used in commands are relative to the parent skill directory. Read this reference only for the route selected in SKILL.md.

## Daily Reads

Use the neutral wrapper and canonical reader:

```bash
memoryctl --actor codex version --json
memoryctl --actor codex search "query" --limit 5
memoryctl --actor claude retrieve "project status" \
  --app-id example-app --project-id example-project --max-results 5 --json
```

Ailu is the exception: its private retrieve request uses schema-v2 stdin JSON and never places the query on argv.

Search/index results are candidates. Reopen current Markdown through the canonical reader before using a fact. A non-`global/shared` `project_id` is project-bound regardless of directory or track. Cross-project results are analogy-only and never authorize actions.
