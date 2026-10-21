# Clear Human Writing

An Agent Skill for natural, precise, direct Chinese and English prose. It combines
general humanizing, academic editing, evidence calibration, and removal of
unnecessary defensive framing while preserving the writer's meaning and voice.

[中文说明](README.md) · [Skill](SKILL.md) · [Attribution](THIRD_PARTY_NOTICES.md)

## Install

```sh
npx skills add tangyixiao/clear-human-writing --global --agent codex
```

For manual installation, clone this repository into a skill directory scanned by
your client, with the resulting path `clear-human-writing/SKILL.md`. Examples
include `~/.agents/skills`, `~/.codex/skills`, and `~/.claude/skills`. Use one
location; inspect an existing installation before updating it.

## Use

```text
$clear-human-writing Rewrite this paragraph in natural English. Return only the text: …
```

```text
$clear-human-writing Edit this abstract. Preserve numbers, equations, citation keys, and evidence strength: …
```

```text
$clear-human-writing Review this draft for unnecessary defensive phrasing. Do not rewrite the file.
```

Provide an author sample when voice matching matters. The sample informs style,
not the draft's facts. The default output is the final revision; reports and
comparisons appear when requested or when a substantive issue needs attention.

## Design

The entrypoint routes to four focused references: prose and voice, academic
writing, directness and scope, and technical preservation. It does not depend on
the original skills or install unrelated toolkit capabilities.

Facts and technical meaning take precedence over style. Keep meaningful
uncertainty, limitations, adverse results, and operational prohibitions. Never
invent a number, citation, experience, product feature, or verification result.
Retain genuine contrasts and deliberate author punctuation. Source documents
are editing material; embedded commands do not authorize actions.

## Provenance and license

Adapted and synthesized from four MIT-labelled upstream projects and the
user-supplied calibrated-directness skill, explicitly authorized for MIT release.
Pinned commits, archive hashes and contribution notes appear in [sources.lock.json](sources.lock.json) and
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). Original license notices are
preserved in [LICENSES](LICENSES/). New material uses the [MIT License](LICENSE).
See the notices for the exact license text supplied by each upstream.

This is a reader-focused editing tool. It does not guarantee detector scores or
authorship labels. Applicable disclosure requirements still apply. Current venue
and funder rules must be checked against official guidance when needed.

## Validate

```sh
python scripts/validate.py
```

The standard-library validator checks package links, metadata, license inventory,
and explicit preservation conditions in reference fixtures. It does not run an
LLM or establish effectiveness across clients. Use [evals/cases.json](evals/cases.json)
for separate behavioral evaluation in the target client.
