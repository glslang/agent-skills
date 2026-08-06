# agent-skills

A collection of [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills) for common engineering workflows.

Skills live under `.claude/skills/<skill-name>/`. Claude Code discovers them automatically when working anywhere inside this repo, and auto-loads each one when a user request matches its `description`.

## Skills

Every skill directory sits directly under `.claude/skills/` — that flat layout is what Claude Code discovers. The grouping below is editorial, not structural.

### GitHub & pull requests

| Skill | What it does |
|---|---|
| [`merge-dependabot-prs`](.claude/skills/merge-dependabot-prs/SKILL.md) | Walks the open Dependabot PR queue oldest-first and merges each PR once CI is green. Diagnoses CI failures and either pushes a fix to the bot's branch or opens a follow-up PR. One stuck PR never blocks the rest of the queue. |
| [`sweep-dependabot-prs`](.claude/skills/sweep-dependabot-prs/SKILL.md) | Fleet-mode wrapper around `merge-dependabot-prs`: discovers repos with open Dependabot PRs inside a time window (default 2 years) — your own repos by default, org repos on request — and/or takes an explicit repo list, then clears each repo's queue and prints one aggregate report. |
| [`address-pr-comments`](.claude/skills/address-pr-comments/SKILL.md) | Works through review feedback on a PR: syncs the branch with its base, triages every unresolved thread, verifies each claim before touching code, and pushes back with evidence when a comment is wrong. Detects repetitive and circular threads and caps them — file an issue, defer, or escalate rather than commit round six. Understands bot acks (a Codex 👍 closes the thread) and reports merge readiness. Runs as a one-shot sweep or in watch mode as comments arrive. |

### Release

| Skill | What it does |
|---|---|
| [`release-rust-crates-io`](.claude/skills/release-rust-crates-io/SKILL.md) | Releases a Rust crate to crates.io: user-confirmed version bump, mandatory preflight checks, repo-convention git tag, a required green-CI gate on the released commit before publishing, GitHub release, publish, and smoke test against the published version from crates.io. |

### Reverse engineering

| Skill | What it does |
|---|---|
| [`improve-xnu-matchers`](.claude/skills/improve-xnu-matchers/SKILL.md) | Grows a `disarm`/`jtool2` `.matchers` file by mining XNU source for the string literals that identify kernel functions, so more of a stripped kernelcache gets symbolicated. Scans a local tree or the matching `apple-oss-distributions/xnu` tag, derives `arg#\|pattern\|containing_function\|calling_function` rules (handling the macro and inlining rewrites that shift the argument index), then gates every candidate against the real kernel — string presence, plus `LC_FUNCTION_STARTS` and ADRP/ADD xrefs to catch inlined functions and prove which argument register the string lands in. Only ever appends. |

## Using a skill in another repo

Copy the skill directory into the target repo:

```bash
mkdir -p <target-repo>/.claude/skills
cp -r .claude/skills/<skill-name> <target-repo>/.claude/skills/
```

Or symlink for live updates:

```bash
ln -s "$PWD/.claude/skills/<skill-name>" <target-repo>/.claude/skills/<skill-name>
```

Claude Code picks it up on the next session in that repo.

## Invoking a skill

Two ways:

- **Auto-load** — describe the task in natural language; Claude matches against the skill's `description` and loads it. Example: "merge the dependabot PRs" → `merge-dependabot-prs` loads.
- **Slash command** — type `/<skill-name>` directly, e.g. `/merge-dependabot-prs`.

## Adding a new skill

1. Create `.claude/skills/<name>/SKILL.md`. Keep it directly under `.claude/skills/` — Claude Code only discovers skills one level deep, so a category subdirectory would stop the skill loading.
2. Frontmatter must include `name:` (matches the directory) and `description:` (what triggers auto-load — include the verbs an agent would actually type).
3. Body is the procedure the agent follows.
4. Add a row to the matching section of the [Skills](#skills) table.
5. Commit.

CI checks steps 1, 2 and 4 on every push and PR. Run it locally with:

```bash
python .github/scripts/validate_skills.py
```
