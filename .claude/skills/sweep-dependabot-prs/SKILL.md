---
name: sweep-dependabot-prs
description: Run the merge-dependabot-prs skill across many repos at once. Discovers every repo the user can push to that has open Dependabot PRs created within a time window (default 2 years), and/or takes an explicit list of repo names, then clears each repo's queue in turn. Use when the user asks to "merge dependabot PRs across all my repos", "sweep my repos for dependabot PRs", "clear dependabot queues everywhere", "bulk merge bot updates in these repos", or similar multi-repo requests.
---

# Sweep Dependabot PRs Across Repos

Fleet-mode wrapper around [`merge-dependabot-prs`](../merge-dependabot-prs/SKILL.md). Build a target list of repos — by discovery, by explicit names, or both — then apply the full merge-dependabot-prs procedure to each repo **sequentially**, and finish with one aggregate report. A stuck PR never blocks its repo's queue; a stuck repo never blocks the sweep.

## 0. Preflight

Requires an authenticated `gh` (discovery uses the search API; the MCP GitHub tools have no equivalent bulk search, so in restricted environments ask the user for an explicit repo list and use the base skill's MCP paths for the inner loop).

```bash
gh auth status && gh api user --jq .login   # capture LOGIN for defaults
```

Resolve the run parameters from the user's request:

- **Window** — how far back a Dependabot PR's *creation date* may be. Default: **2 years**. "all" / "everything" disables the filter.
- **Repo list** — explicit names, if given. Normalize bare names (`myrepo`) to `LOGIN/myrepo`; if the user belongs to multiple orgs and a bare name is ambiguous, ask.
- **Scope** — for discovery: default is repos owned by `LOGIN`. Only include orgs if the user asks ("including my orgs" → add each of `gh api user/orgs --jq '.[].login'` as an extra `--owner`).

Both filters combine: an explicit list restricts *which repos*, the window restricts *which PRs* inside them.

```bash
# Cutoff date for the window (pick the variant that works on this platform)
CUTOFF=$(date -v-2y +%Y-%m-%d 2>/dev/null || date -d '2 years ago' +%Y-%m-%d)
```

## 1. Build the target list

### Discovery mode (no explicit list, or "and also anything else")

One search across all owned repos — never iterate `gh pr list` per repo to discover:

```bash
gh search prs \
  --author app/dependabot \
  --state open \
  --owner "$LOGIN" \
  --created ">=$CUTOFF" \
  --archived=false \
  --limit 1000 \
  --json repository,number,createdAt \
  --jq 'group_by(.repository.nameWithOwner)
        | map({repo: .[0].repository.nameWithOwner, prs: length, oldest: (map(.createdAt) | min)})
        | sort_by(.oldest)'
```

Omit `--created` entirely when the window is "all".

### List mode (user named repos)

For each name, confirm there is anything to do (and apply the window):

```bash
gh pr list -R "$REPO" --author 'app/dependabot' --state open \
  --search "created:>=$CUTOFF" --json number,createdAt --jq length
```

### Filter to repos you can actually merge in

For every candidate repo:

```bash
gh repo view "$REPO" --json viewerPermission,isArchived \
  --jq '{perm: .viewerPermission, archived: .isArchived}'
```

Drop repos that are archived or where `viewerPermission` is not `WRITE`/`MAINTAIN`/`ADMIN` — record them as "skipped: no push access" for the final report rather than failing mid-run.

## 2. Confirm the plan

Print the target table — repo, open Dependabot PR count, oldest PR date — plus the window in effect.

- **Discovery mode: always confirm with the user before merging anything.** Discovery can surface repos they forgot about, and this is a mass, outward-facing operation.
- **List mode:** the user already enumerated the targets — proceed without asking, unless the combined PR count is surprisingly large (say, 50+), then confirm.
- **Dry run** requested → print the table and each repo's would-be actions (base skill's dry-run mode), merge nothing, stop.

## 3. Per-repo loop

Process repos in table order (oldest outstanding PR first). For each repo, **follow the entire `merge-dependabot-prs` procedure** with these adaptations:

1. **No `cd` needed for the happy path.** Add `-R "$REPO"` to every `gh pr`/`gh repo` call in the base skill. Do not clone up front.
2. **Apply the window inside the repo too**: base skill step 1 becomes
   ```bash
   gh pr list -R "$REPO" --author 'app/dependabot' --state open \
     --search "created:>=$CUTOFF" \
     --json number,title,createdAt,headRefName,baseRefName,mergeable,mergeStateStatus \
     --jq 'sort_by(.createdAt)'
   ```
3. **Clone lazily.** Only when a fix must be authored locally (base skill steps 2e/2f) do:
   ```bash
   gh repo clone "$REPO" "$SCRATCH/$(basename "$REPO")" -- --filter=blob:none
   ```
   into the scratchpad directory, and work there. Delete or leave per scratchpad convention when the repo is done.
4. **Repo-level failure never blocks the sweep.** If a repo errors in a way that isn't about one PR (auth, permissions changed mid-run, repo transferred), log it under "skipped repos" and continue with the next repo.
5. **Pace between repos.** Sleep ~10s between repos on long sweeps; on any 403/429 back off 60s before continuing (search + merge traffic across many repos hits secondary rate limits sooner than a single-repo run).

Keep the loop **sequential** — parallel merging across repos multiplies rate-limit pressure and interleaves CI waits confusingly for no real win, since most wall-clock time is waiting on CI anyway.

## 4. Fleet report

After the last repo, print one aggregate report:

- **Per repo:** merged PR numbers, skipped PRs with one-line reasons, open follow-up PRs — same shape as the base skill's final report, grouped by repo.
- **Skipped repos:** name + reason (archived, no push access, nothing in window, repo-level error).
- **Totals:** N repos processed, M PRs merged, K skipped, J follow-ups opened.

## Gotchas

- **`gh search prs` caps at 1000 results.** If the search returns exactly 1000, results were truncated — narrow the window, split by `--owner`, or page with `--created` date ranges.
- **The window filters on creation date, not last activity.** A 3-year-old PR Dependabot rebased yesterday is excluded by the default window. If the user says "old" or "stale" PRs are the point, suggest window "all".
- **Search index lag.** A PR merged/closed seconds ago can still appear in search results. The per-repo `gh pr list` in step 3 is the source of truth; discovery is only for building the candidate list.
- **Forks:** Dependabot PRs on your fork usually target *your* default branch and are mergeable — but if the user's intent is upstream contributions, forks are noise. When discovery surfaces forks, flag them in the confirmation table rather than silently including them.
- **Org repos need explicit opt-in.** Merging across an org you belong to affects other people's repos — never widen scope beyond what the user asked for.
- **One `@dependabot rebase` wave per repo, not per sweep.** The bot processes rebase comments per-repo; commenting on 20 PRs across 10 repos simultaneously is fine, but within one repo follow the base skill's one-at-a-time discipline.

## Inputs the user might give

- "sweep all my repos" → discovery mode, default 2-year window, confirm before merging.
- "these repos: foo, bar, org/baz" → list mode, default window, no confirmation.
- "past 6 months" / "last 90 days" → override `CUTOFF` accordingly.
- "everything, however old" → window "all".
- "including my orgs" → add org logins to discovery scope.
- "dry run" → step 2's dry-run behavior across the whole fleet.
- "just the patch bumps" → pass the base skill's title filter down into every repo's inner loop.
