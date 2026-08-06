#!/usr/bin/env python3
"""Validate the skill library.

Claude Code discovers a skill at `.claude/skills/<name>/SKILL.md` and nowhere
else, so the checks here are the ones that decide whether a skill loads at all:
the file exists, its frontmatter parses, `name` matches the directory, and
`description` is non-empty. The README check is drift control — the table is the
only index of what lives here.

Stdlib only, to match the scripts the skills themselves bundle.
"""

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / ".claude" / "skills"
README = REPO / "README.md"


def frontmatter(text):
    """Return the frontmatter block of a SKILL.md, or None if there isn't one."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    return text[4:end]


def scalar(block, key):
    """Read a top-level `key: value` out of a frontmatter block."""
    match = re.search(rf"^{key}:[ \t]*(.*)$", block, re.MULTILINE)
    if match is None:
        return None
    return match.group(1).strip().strip("'\"")


def main():
    errors = []

    directories = sorted(d for d in SKILLS.iterdir() if d.is_dir())
    if not directories:
        errors.append(f"{SKILLS}: no skill directories found")

    readme = README.read_text(encoding="utf-8")

    for directory in directories:
        skill_md = directory / "SKILL.md"
        relative = skill_md.relative_to(REPO).as_posix()

        if not skill_md.is_file():
            errors.append(f"{relative}: missing (a skill directory needs a SKILL.md)")
            continue

        block = frontmatter(skill_md.read_text(encoding="utf-8"))
        if block is None:
            errors.append(f"{relative}: no `---` frontmatter block")
            continue

        name = scalar(block, "name")
        if name is None:
            errors.append(f"{relative}: frontmatter has no `name`")
        elif name != directory.name:
            errors.append(
                f"{relative}: `name: {name}` does not match directory "
                f"`{directory.name}` — the directory name wins, so the skill "
                f"loads as `/{directory.name}`"
            )

        description = scalar(block, "description")
        if not description:
            errors.append(
                f"{relative}: frontmatter has no `description` — Claude Code "
                f"matches requests against it to auto-load the skill"
            )

        if relative not in readme:
            errors.append(
                f"{relative}: not linked from README.md — add it to the "
                f"relevant Skills section"
            )

    for error in errors:
        print(f"error: {error}", file=sys.stderr)

    if errors:
        print(f"\n{len(errors)} problem(s) in {len(directories)} skill(s)", file=sys.stderr)
        return 1

    print(f"ok: {len(directories)} skills validated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
