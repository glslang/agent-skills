#!/usr/bin/env python3
"""Validate the skill library.

Claude Code discovers a skill at `.claude/skills/<name>/SKILL.md` and nowhere
else, so the checks here are the ones that decide whether a skill loads at all:
the frontmatter is valid YAML, `name` matches the directory, and `description`
is a non-empty string. The README check is drift control — the table is the only
index of what lives here.

The frontmatter is parsed, not scanned. Scanning it with a regex passes files
Claude Code cannot load — `description: "unterminated` and `name: "foo` are not
valid YAML, and `description: null` has no description at all, but all three
look fine to a pattern match. A validator that green-lights an unloadable skill
is worse than no validator, so this uses a real parser.

The README is checked in both directions: every skill needs a catalogue link,
and every catalogue link needs a skill. Checking only the first leaves a
renamed or deleted skill behind a broken link that CI reports as fine.
"""

import re
import sys
from pathlib import Path

# A Markdown link whose destination is a skill's SKILL.md, in either the plain
# `](path)` or the angle-bracketed `](<path>)` form.
SKILL_LINK = re.compile(r"\]\(<?(\.claude/skills/[^)>\s]+/SKILL\.md)>?\)")

try:
    import yaml
except ModuleNotFoundError:
    sys.exit(
        "validate_skills.py needs PyYAML.\n"
        "    pip install -r .github/requirements.txt"
    )

REPO = Path(__file__).resolve().parents[2]
SKILLS = REPO / ".claude" / "skills"
README = REPO / "README.md"


def frontmatter(text):
    """Return the YAML frontmatter block of a SKILL.md, or None if absent.

    The closing delimiter is a line that is exactly `---`, so a `---` inside the
    body doesn't truncate the block.
    """
    if not text.startswith("---\n"):
        return None
    rest = text[4:]
    end = re.search(r"^---[ \t]*$", rest, re.MULTILINE)
    if end is None:
        return None
    return rest[: end.start()]


def rendered(markdown):
    """Strip what a reader never sees: fenced code blocks and HTML comments.

    Both can hold text in exact Markdown link form — a commented-out catalogue
    row is the usual way it happens — and neither puts a link on the rendered
    page. Matching them would accept a skill that is missing from the visible
    catalogue.
    """
    without_fences = re.sub(r"^```[\s\S]*?^```", "", markdown, flags=re.MULTILINE)
    return re.sub(r"<!--[\s\S]*?-->", "", without_fences)


def linked_from_readme(readme, relative):
    """True if the README links to `relative` as a visible Markdown link."""
    return f"]({relative})" in readme or f"](<{relative}>)" in readme


def stale_readme_links(readme, directories):
    """Catalogue links pointing at skills that no longer exist."""
    linked = set(SKILL_LINK.findall(readme))
    existing = {(d / "SKILL.md").relative_to(REPO).as_posix() for d in directories}
    return sorted(linked - existing)


def check_skill(directory, readme):
    """Return a list of problems with one skill directory."""
    skill_md = directory / "SKILL.md"
    relative = skill_md.relative_to(REPO).as_posix()

    if not skill_md.is_file():
        return [f"{relative}: missing (a skill directory needs a SKILL.md)"]

    block = frontmatter(skill_md.read_text(encoding="utf-8"))
    if block is None:
        return [f"{relative}: no `---` frontmatter block"]

    try:
        meta = yaml.safe_load(block)
    except yaml.YAMLError as exc:
        detail = str(exc).replace("\n", " ")
        return [f"{relative}: frontmatter is not valid YAML — {detail}"]

    if not isinstance(meta, dict):
        return [f"{relative}: frontmatter must be a YAML mapping of keys to values"]

    problems = []

    name = meta.get("name")
    if not isinstance(name, str) or not name.strip():
        problems.append(f"{relative}: frontmatter needs a non-empty string `name`")
    elif name.strip() != directory.name:
        problems.append(
            f"{relative}: `name: {name.strip()}` does not match directory "
            f"`{directory.name}` — the directory name wins, so the skill "
            f"loads as `/{directory.name}`"
        )

    description = meta.get("description")
    if not isinstance(description, str) or not description.strip():
        problems.append(
            f"{relative}: frontmatter needs a non-empty string `description` — "
            f"Claude Code matches requests against it to auto-load the skill"
        )

    if not linked_from_readme(readme, relative):
        problems.append(
            f"{relative}: not linked from README.md — add it to the "
            f"relevant Skills section"
        )

    return problems


def main():
    errors = []

    directories = sorted(d for d in SKILLS.iterdir() if d.is_dir())
    if not directories:
        errors.append(f"{SKILLS}: no skill directories found")

    readme = rendered(README.read_text(encoding="utf-8"))
    for directory in directories:
        errors.extend(check_skill(directory, readme))

    for link in stale_readme_links(readme, directories):
        errors.append(
            f"README.md: links to {link}, which does not exist — "
            f"remove the row, or restore the skill if it was renamed"
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
