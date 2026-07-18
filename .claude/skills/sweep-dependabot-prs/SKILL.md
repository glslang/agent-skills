---
name: sweep-dependabot-prs
description: Run the merge-dependabot-prs skill across many repos at once. Discovers repos with open Dependabot PRs created within a time window (default 2 years) — the user's own repos by default, org repos on explicit request — and/or takes an explicit list of repo names, then clears each repo's queue in turn. Use when the user asks to "merge dependabot PRs across all my repos", "sweep my repos for dependabot PRs", "clear dependabot queues everywhere", "bulk merge bot updates in these repos", or similar multi-repo requests.
---

# Sweep Dependabot PRs Across Repos

Fleet-mode wrapper around [`merge-dependabot-prs`](../merge-dependabot-prs/SKILL.md). Build a target list of repos — by discovery, by explicit names, or both — then apply the full merge-dependabot-prs procedure to each repo **sequentially**, and finish with one aggregate report. A stuck PR never blocks its repo's queue; a stuck repo never blocks the sweep.

## 0. Preflight

Detect tooling the same way the base skill does: prefer `gh` if it's authenticated, otherwise fall back to the `mcp__github__*` tools.

**Discovery needs `gh`** — it relies on the search API, and the MCP GitHub tools have no equivalent bulk search. In a restricted environment (Claude Code on the web, no `gh`), discovery is unavailable: ask the user for an explicit repo list, then run the whole procedure over the MCP paths — the wrapper's own per-repo steps below give MCP equivalents, and the inner loop already has them in the base skill.

```bash
gh auth status && gh api user --jq .login   # capture LOGIN for defaults
```

Resolve the run parameters from the user's request:

- **Window** — how far back a Dependabot PR's *creation date* may be. Default: **2 years**. "all" / "everything" disables the filter.
- **Repo list** — explicit names, if given. Normalize bare names (`myrepo`) to `LOGIN/myrepo`; if the user belongs to multiple orgs and a bare name is ambiguous, ask.
- **Scope** — for discovery: default is repos owned by `LOGIN`. Only include orgs if the user asks ("including my orgs" → add each of `gh api --paginate user/orgs --jq '.[].login'` as an extra `--owner`). Discovery never sees repos where the user is only an outside collaborator — those must be named explicitly in the repo list.

Both filters combine: an explicit list restricts *which repos*, the window restricts *which PRs* inside them.

Build the date filter **once**, as optional arguments every later `gh pr list` reuses — so a window of "all" omits the filter everywhere, not just in discovery:

```bash
if [[ "$WINDOW" == "all" ]]; then
  CREATED_FILTER=()
else
  # Derive the cutoff from the RESOLVED window — shown here for the 2-year default.
  # Swap the offset to match the request: "past 6 months" → -v-6m / '6 months ago',
  # "last 90 days" → -v-90d / '90 days ago', etc. Never leave it at 2y for a
  # narrower request — that sweeps PRs the user didn't ask about.
  CUTOFF=$(date -v-2y +%Y-%m-%d 2>/dev/null || date -d '2 years ago' +%Y-%m-%d)
  CREATED_FILTER=(--search "created:>=$CUTOFF")
fi
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

For each name, capture the same `{count, oldest}` shape discovery produces — the confirmation table shows each repo's oldest PR and the loop runs oldest-first, so a bare count isn't enough:

```bash
gh pr list -R "$REPO" --author 'app/dependabot' --state open --limit 1000 \
  "${CREATED_FILTER[@]}" --json number,createdAt \
  --jq '{repo: "'"$REPO"'", prs: length, oldest: (if length == 0 then null else (map(.createdAt) | min) end)}'
```

Repos with `prs == 0` still appear in the report ("nothing in window"); those with PRs join the same oldest-first ordering as discovered repos.

**MCP:** `mcp__github__list_pull_requests` (`state: "open"`), keep `user.login == "dependabot[bot]"`, and filter `created_at >= CUTOFF` in the result (unless the window is "all").

### Both modes together (explicit list + "and anything else")

Take the **union** of the explicit list and the discovery results, de-duplicated by full `owner/name`. Explicitly named repos are never silently dropped: one with zero PRs in the window still appears in the final report as "nothing in window". Discovered repos merely join the list — they never displace a named one. The entire union then goes through the eligibility filter below.

### Filter to repos you can actually merge in

For every candidate repo:

```bash
gh repo view "$REPO" --json viewerPermission,isArchived \
  --jq '{perm: .viewerPermission, archived: .isArchived}'
```

**MCP:** read the repo's metadata (`mcp__github__get_repository` / `mcp__github__search_repositories`) and check its `archived` flag and the `permissions.push` boolean. If no repository-read tool is available in the environment, skip this pre-filter and lean on the base skill's per-PR error handling instead — an archived or no-push repo simply fails its first merge attempt, which the loop already logs and skips.

Drop repos that are archived or where the user can't push (`viewerPermission` not in `WRITE`/`MAINTAIN`/`ADMIN`, or MCP `permissions.push == false`) — record them as "skipped: no push access" for the final report rather than failing mid-run.

## 2. Confirm the plan

Print the target table — repo, open Dependabot PR count, oldest PR date — plus the window in effect.

- **Discovery mode: always confirm with the user before merging anything.** Discovery can surface repos they forgot about, and this is a mass, outward-facing operation.
- **List mode:** the user already enumerated the targets — proceed without asking, unless the combined PR count is surprisingly large (say, 50+), then confirm.
- **Dry run** requested → print the table and each repo's would-be actions (base skill's dry-run mode), merge nothing, stop.

## 3. Per-repo loop

Process repos in table order (oldest outstanding PR first). For each repo, **follow the entire `merge-dependabot-prs` procedure** with these adaptations:

1. **No `cd` needed for the happy path.** Add `-R "$REPO"` to **every** repo-scoped `gh` call in the base skill — `gh pr`, `gh repo`, and the `gh run view`/`gh run rerun` calls in its CI-failure steps (2e). A `gh run` command without `-R` resolves against the current checkout, which is *not* the target repo. Do not clone up front.
2. **Apply the window inside the repo too**: base skill step 1 becomes
   ```bash
   gh pr list -R "$REPO" --author 'app/dependabot' --state open --limit 1000 \
     "${CREATED_FILTER[@]}" \
     --json number,title,createdAt,headRefName,baseRefName,mergeable,mergeStateStatus \
     --jq 'sort_by(.createdAt)'
   ```
3. **Clone lazily, once per repo.** Only when local git work is needed — a fix authored locally (base skill steps 2e/2f) or the manual-rebase fallback when Dependabot ignores two `@dependabot rebase` comments (step 2b) — do:
   ```bash
   SCRATCH="${SCRATCH:-$(mktemp -d "${TMPDIR:-/tmp}/dependabot-sweep.XXXXXX")}"   # session scratchpad if set, else a fresh temp dir
   mkdir -p "$SCRATCH"   # in case $SCRATCH was preset to a path that doesn't exist yet
   DEST="$SCRATCH/${REPO//\//__}"   # owner__name: two repos sharing a basename must not share a checkout
   if [ -d "$DEST/.git" ]; then
     git -C "$DEST" fetch origin   # reuse the existing checkout for a later PR in the same repo
   elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
     gh repo clone "$REPO" "$DEST" -- --filter=blob:none
   else
     git clone --filter=blob:none "https://github.com/$REPO.git" "$DEST"   # plain git, using SSH/credential-helper auth
   fi
   ```
   and work there (`git -C "$DEST" checkout <headRefName>`). Delete or leave per scratchpad convention when the repo is done.

   **When local git can't reach the remote, drop to API-only remediation.** The gate is *Git capability*, not the presence of `gh`: a no-`gh` environment with SSH keys or a credential helper can still clone and push, so use the plain-`git` path above. Only when neither `gh` nor git credentials can reach GitHub — e.g. a locked-down web sandbox — is there no local-fix path. Probe once (a failing `git ls-remote "https://github.com/$REPO.git" >/dev/null 2>&1` with no credential fallback signals this); when confirmed unreachable, restrict remediation to the options the base skill supports without a checkout — re-run a flaky job, comment `@dependabot rebase`/`recreate` — and otherwise skip the PR with a note. The queue keeps moving; only PRs that genuinely need hand-authored fixes are deferred.
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
