# agent-skills

A collection of [Claude Code skills](https://docs.claude.com/en/docs/claude-code/skills) for common engineering workflows.

Skills live under `.claude/skills/<skill-name>/`. Claude Code discovers them automatically when working anywhere inside this repo, and auto-loads each one when a user request matches its `description`.

## Skills

| Skill | What it does |
|---|---|
| [`merge-dependabot-prs`](.claude/skills/merge-dependabot-prs/SKILL.md) | Walks the open Dependabot PR queue oldest-first and merges each PR once CI is green. Diagnoses CI failures and either pushes a fix to the bot's branch or opens a follow-up PR. One stuck PR never blocks the rest of the queue. |
| [`sweep-dependabot-prs`](.claude/skills/sweep-dependabot-prs/SKILL.md) | Fleet-mode wrapper around `merge-dependabot-prs`: discovers repos with open Dependabot PRs inside a time window (default 2 years) — your own repos by default, org repos on request — and/or takes an explicit repo list, then clears each repo's queue and prints one aggregate report. |
| [`release-rust-crates-io`](.claude/skills/release-rust-crates-io/SKILL.md) | Releases a Rust crate to crates.io: user-confirmed version bump, mandatory preflight checks, repo-convention git tag, a required green-CI gate on the released commit before publishing, GitHub release, publish, and smoke test against the published version from crates.io. |

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

1. Create `.claude/skills/<name>/SKILL.md`.
2. Frontmatter must include `name:` (matches the directory) and `description:` (what triggers auto-load — include the verbs an agent would actually type).
3. Body is the procedure the agent follows.
4. Commit.
