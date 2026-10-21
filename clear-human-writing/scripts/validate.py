"""Validate the package and reference fixtures without invoking an LLM."""

import hashlib
import json
import re
from pathlib import Path


def validate(root):
    errors = []
    skill = (root / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"\A---\n(.*?)\n---\n", skill, re.S)
    if not match:
        errors.append("SKILL.md: missing frontmatter")
    else:
        header = match.group(1)
        if not re.search(r"^name: clear-human-writing$", header, re.M):
            errors.append("SKILL.md: incorrect name")
        if not re.search(r"^description: >-?\n  \S", header, re.M):
            errors.append("SKILL.md: missing folded description")

    for path in root.rglob("*.md"):
        if ".git" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        for link in re.findall(r"\]\(([^)]+)\)", text):
            if "://" in link or link.startswith(("#", "mailto:")):
                continue
            target = (path.parent / link.split("#", 1)[0]).resolve()
            if not target.is_relative_to(root.resolve()) or not target.exists():
                errors.append(f"{path.relative_to(root)}: invalid local link {link}")

    sources = json.loads((root / "sources.lock.json").read_text(encoding="utf-8"))
    for source in sources["sources"]:
        license_path = root / source["license_file"]
        if not license_path.is_file():
            errors.append(f"Missing license: {source['id']}")
        elif hashlib.sha256(license_path.read_bytes()).hexdigest() != source["license_sha256"]:
            errors.append(f"License hash mismatch: {source['id']}")
        if source.get("commit") and not re.fullmatch(r"[0-9a-f]{40}", source["commit"]):
            errors.append(f"Invalid pinned commit: {source['id']}")

    fixtures = json.loads((root / "evals/cases.json").read_text(encoding="utf-8"))["cases"]
    seen = set()
    for case in fixtures:
        if case["id"] in seen:
            errors.append(f"Duplicate fixture id: {case['id']}")
        seen.add(case["id"])
        for key in ("request", "input", "reference_revision", "criteria"):
            if not isinstance(case.get(key), str) or not case[key].strip():
                errors.append(f"{case['id']}: missing {key}")
        for item in case["must_keep"]:
            if item not in case["reference_revision"]:
                errors.append(f"{case['id']}: reference lost {item!r}")
        for item in case["must_avoid"]:
            if item in case["reference_revision"]:
                errors.append(f"{case['id']}: reference contains {item!r}")

    return errors, len(fixtures), len(sources["sources"])


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    failures, fixture_count, source_count = validate(package_root)
    if failures:
        for failure in failures:
            print(f"ERROR: {failure}")
        raise SystemExit(1)
    print(f"PASS: package links, metadata, {source_count} source notices, "
          f"and {fixture_count} reference fixtures")
    print("No LLM was invoked; this is not a behavioral benchmark.")
