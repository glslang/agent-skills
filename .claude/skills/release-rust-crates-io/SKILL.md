---
name: release-rust-crates-io
description: Release a Rust crate to crates.io with mandatory preflight checks, user-confirmed version bump and git tag (following repo tag conventions), a required green-CI gate on the released commit before publishing, GitHub release, and post-publish verification from crates.io. Use when the user asks to release or publish a Rust crate, ship a version to crates.io, cut a crate release, tag and publish a Rust library, or run a crates.io release workflow.
---

# Release Rust Crate to crates.io

End-to-end release: confirm version → mandatory preflight checks → user-confirmed tag → green CI on the released commit → `cargo publish` → GitHub tag/release → smoke test against the published crate on crates.io.

**Every step and every check is mandatory.** Do not skip, defer, or proceed on failure. Stop and ask the user only when a gate fails or a decision is required.

## 0. Detect repo and crate

From the repo root (or the path the user gave):

```bash
git rev-parse --show-toplevel
cargo metadata --no-deps --format-version 1
```

Determine:

- **Package name** and **current version** from the target crate's `Cargo.toml` (`[package].name`, `[package].version`).
- **Workspace?** If multiple publishable crates, list them and confirm which to release (or release in dependency order — dependencies before dependents).
- **Default branch** (`main` / `master`).

If `[package].publish = false`, stop — crate is not publishable.

If the working tree has uncommitted changes, ask whether to commit them first or stash. Do not tag or publish on a dirty tree unless the user explicitly approves.

## 1. Confirm release version (required — do not proceed without approval)

Before any checks or version edits, present the release target and **wait for explicit confirmation**.

Gather context:

```bash
# Current version (workspace: add -p <crate>)
cargo pkgid 2>/dev/null | sed 's/.*#//' || grep '^version' Cargo.toml

# Latest published on crates.io (may 404 for first release)
curl -s "https://crates.io/api/v1/crates/<crate-name>" | jq -r '.crate.max_version // "none"'

# Recent git tags for this repo
git tag -l --sort=-v:refname | head -20
```

Propose a **target version** using, in order:

1. Version the user already stated in the request.
2. Semver bump inferred from commits since the last tag (`feat` → minor, `fix`/`chore` → patch, breaking/`!` → major) — state the reasoning.
3. If ambiguous, suggest patch bump from current `Cargo.toml` and ask.

Use `AskQuestion` or ask conversationally. Present:

- **Current version** in `Cargo.toml`: `X.Y.Z`
- **Latest on crates.io** (if any): `A.B.C`
- **Proposed release version**: `N.E.W`
- **Bump type**: patch / minor / major / pre-release (and why)

**Wait for explicit confirmation** of the target version. If the user picks a different version, use that.

Only after confirmation, update version in all required places:

- `[package].version` in `Cargo.toml` (and `Cargo.lock` via `cargo check` / `cargo build`)
- Workspace members that depend on the crate internally, if they pin path versions
- `CHANGELOG.md` (or project equivalent) — add a section for the new version if the project keeps one
- Any other repo files that embed the version (README badges, etc.) — search `git grep` for the old version string

Commit the version bump (unless the user wants it folded into an existing commit — confirm). Re-read `Cargo.toml` to verify the confirmed version is on disk before step 2.

## 2. Detect tag convention (required)

Tags must match **this repo's existing convention**, not a assumed default.

```bash
git tag -l --sort=-v:refname | head -30
git ls-remote --tags origin | awk '{print $2}' | sed 's|refs/tags/||' | sort -V | tail -20
```

Infer the pattern from recent release tags (ignore junk tags like `test`, `snapshot`):

| Observed tags | Convention | Example for version `1.2.3` |
|---|---|---|
| `v1.0.0`, `v1.1.0` | `v` prefix | `v1.2.3` |
| `1.0.0`, `1.1.0` | bare semver | `1.2.3` |
| `crate-name-v1.0.0` | prefixed with crate name | `<crate-name>-v1.2.3` |
| `release-1.0.0` | custom prefix | match existing prefix + version |

If **no prior release tags** exist, check `CONTRIBUTING.md`, `RELEASING.md`, or `.github/workflows/*release*` for documented convention. If still unclear, ask the user which format to use.

Record: **tag template** = `<confirmed-version>` with the repo's prefix/suffix applied.

Verify the tag does not already exist:

```bash
git tag -l '<proposed-tag>'
git ls-remote --tags origin "refs/tags/<proposed-tag>"
```

## 3. Mandatory preflight checks

Run **all** checks below. Every command must exit 0. Fix failures and re-run the full suite from the top — do not cherry-pick.

```bash
rustup component add clippy rustfmt   # install if missing; do not skip
cargo fmt --all -- --check
cargo clippy --all-targets --all-features -- -D warnings
cargo test --all-features
cargo build --release
cargo doc --no-deps --all-features
cargo publish --dry-run
```

For workspaces, scope with `-p <crate>` when releasing one member; still run the full list.

Additionally verify (fail if missing):

- `Cargo.toml` has `license` (or `license-file`), `description`, and `repository`/`homepage` as appropriate.
- `README` and `LICENSE` are included in the published package (confirm via dry-run output).
- CHANGELOG documents the confirmed release version (when the project maintains one).

Report a checklist — every item must show pass:

```
[ ] cargo fmt --check
[ ] cargo clippy
[ ] cargo test --all-features
[ ] cargo build --release
[ ] cargo doc
[ ] cargo publish --dry-run
[ ] manifest metadata
[ ] changelog (if applicable)
```

## 4. Confirm tag (required — do not proceed without approval)

Propose the tag using the convention from step 2 and the version from step 1:

- **Proposed tag:** `<proposed-tag>` (state the detected convention)
- **Target commit:** current `HEAD` short SHA + one-line subject
- **Crate:** `<name>` version `<confirmed-version>`

**Wait for explicit confirmation** before creating the tag. If the user wants a different tag, adjust only if it still matches repo convention (or document a one-time exception with user approval).

## 5. Create and push tag

Only after step 4 confirmation:

```bash
git tag -a <proposed-tag> -m "Release <crate-name> <confirmed-version>"
git push origin <proposed-tag>
```

If the version bump commit is not yet on the remote, push the branch first:

```bash
git push origin HEAD
```

## 5a. Wait for remote CI (required)

Step 3 only ever exercises **one** host — one OS, one architecture, one toolchain. A crate whose behavior depends on target ABI, pointer width, endianness, or OS APIs can pass every local check and still be broken on a platform the project supports. `cargo publish` is irreversible: a version can be yanked, never replaced. So gate the publish on the project's own CI, run against the exact commit being released.

Resolve the SHA **once** — re-evaluating it inside the loop would silently retarget the gate if anything moved `HEAD` — and pass an explicit `--limit` above the number of workflows one commit can start (`gh run list` defaults to 20, so a busy repo can hide the very run still pending):

```bash
SHA=$(git rev-parse HEAD)
gh run list --commit "$SHA" --limit 100 --json databaseId,name,status,conclusion
```

`gh run watch <run-id> --exit-status` turns a failed run into a non-zero exit, but it has no deadline of its own — wrap it in `timeout 1200` if you watch runs individually.

**An all-completed snapshot is not sufficient on its own.** Workflows triggered by the push you just made take time to register, so `gh run list` can lag behind reality. If the commit already carries a completed run from an earlier push, the very first poll may show "everything finished, one success" while the tag-triggered matrix is still queuing — passing the gate on evidence that predates the release. So require the run set to have **stopped changing** before accepting it:

```bash
SHA=$(git rev-parse HEAD)
DEADLINE=$(( $(date +%s) + 1200 ))          # 20 minutes overall
SETTLE=60                                   # run set must be unchanged this long
PREV_IDS=""; STABLE_SINCE=0

while :; do
  RUNS=$(gh run list --commit "$SHA" --limit 100 \
           --json databaseId,name,status,conclusion) \
    || { echo "gh run list failed — stopping, NOT publishing"; exit 1; }

  IDS=$(jq -r '[.[].databaseId] | sort | join(",")' <<<"$RUNS")
  PENDING=$(jq '[.[] | select(.status != "completed")] | length' <<<"$RUNS")
  NOW=$(date +%s)

  # A run appearing (or the first look) restarts the settle timer.
  if [ "$IDS" != "$PREV_IDS" ]; then
    PREV_IDS="$IDS"; STABLE_SINCE=$NOW
  fi

  # Accept only a set that is fully completed AND has stopped growing.
  if [ "$PENDING" -eq 0 ] && [ $(( NOW - STABLE_SINCE )) -ge "$SETTLE" ]; then
    break
  fi

  if [ "$NOW" -ge "$DEADLINE" ]; then
    echo "CI not settled after 20 min. Outstanding:"
    jq -r '.[] | select(.status != "completed")
           | "  \(.databaseId)  \(.name)  \(.status)"' <<<"$RUNS"
    exit 1                                   # ask the user; do not publish
  fi
  sleep 20
done

jq -r '.[] | "\(.name): \(.conclusion)"' <<<"$RUNS"

OK=$( jq '[.[] | select(.conclusion == "success")] | length' <<<"$RUNS")
BAD=$(jq '[.[] | select(.conclusion
          | IN("failure","cancelled","timed_out","startup_failure","action_required"))]
          | length' <<<"$RUNS")

[ "$BAD" -eq 0 ] || { echo "CI is not green — NOT publishing"; exit 1; }
[ "$OK"  -gt 0 ] || { echo "no successful run for $SHA — NOT publishing"; exit 1; }
```

Because the first observation seeds `STABLE_SINCE`, the loop always polls at least twice — a snapshot taken before the new workflows registered can never satisfy the gate by itself. Raise `SETTLE` on repos where workflows are slow to queue.

Four failure modes here look exactly like success if you don't check for them:

- **`gh` itself failing** (network, auth, rate limit) prints nothing on stdout, so a naive emptiness test reads it as "nothing pending." Check the exit status.
- **Zero runs for the commit** ends the wait instantly with an empty verdict list. The `OK > 0` assertion is what stops an empty set from passing the gate.
- **A truncated listing** silently drops runs beyond the default limit.

Gate on the outcome:

- **Every run `success`** (`BAD == 0`, `OK > 0`) → proceed to step 6.
- **Any `failure` / `cancelled` / `timed_out`** → **stop, do not publish.** Report which job failed. The tag is already pushed; fix forward with a new version rather than reusing this one.
- **No CI configured**, or no runs for the commit → say so explicitly and ask whether to publish on local checks alone. Never silently treat "no CI" as "CI passed".
- **Still running at the deadline** → report the outstanding run IDs and ask.

If required checks only run on pull requests and the release commit landed directly on the default branch, there may be no runs for that SHA. **Do not substitute the introducing PR's checks as evidence.** Squash and rebase merges produce a different commit than the one CI ran on, so those results describe a tree you are not publishing. Stop, and proceed only on explicit user approval recorded as a documented exception in the final report. PR checks may be cited as context — never as the gate.

## 6. Publish to crates.io

**What authorizes this irreversible step:** the step-4 confirmation covers publishing **that exact tag and commit**, and only once step 5a is green. It is not open-ended approval to publish whatever is on disk now.

So before running `cargo publish`, re-check that nothing moved underneath you — `HEAD` still at the confirmed commit, the tag still pointing there, the green CI runs belonging to that same SHA, and `Cargo.toml` still holding the confirmed version:

```bash
git rev-parse HEAD "<proposed-tag>^{commit}"   # must match each other and the confirmed commit
```

If any has changed — a new commit landed, the tag was re-pointed, CI went green on a different SHA — **stop and re-confirm with the user.** Publishing a tree the user never approved is exactly the mistake that cannot be undone.

**Matching revisions are not enough: `cargo publish` packages the working tree, not the commit.** If step 0 proceeded on a dirty tree, or anything changed on disk during the CI wait, `HEAD` and the tag can both still be correct while the tarball uploaded to crates.io differs from what CI validated. Require the tree to be clean:

```bash
git status --porcelain   # must print nothing
```

If it prints anything, **stop.** Commit the change and restart from step 3 so the checks and CI run against what will actually ship — or stash it if it doesn't belong in the release. Never reach for `--allow-dirty` to get past this: it is precisely the flag that decouples the published artifact from the reviewed, tested, tagged commit.

Verify credentials (token in `~/.cargo/credentials.json` — do not print it). Re-run dry-run, then publish:

```bash
cargo publish --dry-run
cargo publish
# Workspaces:
cargo publish -p <crate-name>
```

If publish fails (name taken, version exists, manifest error), **do not delete the tag** unless the user asks. Report the error and stop.

On success, note that crates.io index propagation can take **1–10 minutes**.

## 7. GitHub release

Create a GitHub release for the tag (prefer `gh`):

```bash
gh release create <proposed-tag> \
  --title "<crate-name> <confirmed-version>" \
  --notes "$(cat CHANGELOG.md 2>/dev/null | sed -n '/## \[<confirmed-version>\]/,/## \[/p' | head -n -1 || echo 'Release <confirmed-version>')"
```

If no CHANGELOG section exists, use a one-line body or ask the user for release notes.

If `gh` is unavailable, stop and tell the user to create the release manually: `https://github.com/<owner>/<repo>/releases/new?tag=<proposed-tag>`.

## 8. Post-publish verification (required)

Confirm the crate is consumable **from crates.io**, not the local path.

### 8a. Wait for index

Poll until the version appears (cap at ~10 min, 30s intervals):

```bash
cargo search <crate-name> --limit 1
curl -s "https://crates.io/api/v1/crates/<crate-name>/<confirmed-version>" | jq -r '.version.num // empty'
```

### 8b. Create ephemeral smoke-test project

Use a temp directory outside the source repo:

```bash
SMOKE=$(mktemp -d)
cd "$SMOKE"
cargo init --name <crate-name>-smoke --bin
```

Pin the **published** version (no path dependency):

```toml
[dependencies]
<crate-name> = "= <confirmed-version>"
```

Write `src/main.rs` (and `tests/integration.rs` if needed) with a **minimal but meaningful** exercise of the public API — import the crate, call at least one exported type or function, assert a known result. Derive tests from the crate's own unit tests or README examples when possible.

For library-only crates, prefer a lib smoke project:

```bash
cargo init --name <crate-name>-smoke-test --lib
```

### 8c. Run smoke tests

```bash
cd "$SMOKE"
cargo build
cargo test
cargo run   # if binary smoke project
```

All must pass. On failure:

1. Report the error clearly (dependency resolution, API break, missing feature flag, etc.).
2. **Do not** yank the crate unless the user explicitly requests it.
3. Suggest fixes (yank + patch release, docs correction, etc.).

Clean up: `rm -rf "$SMOKE"`.

## 9. Final report

Print:

- **Published:** `<crate-name>` `<confirmed-version>` on crates.io
- **Tag:** `<proposed-tag>` pushed to origin (convention: …)
- **GitHub release:** URL (`gh release view <proposed-tag> --json url -q .url`)
- **Checks:** all mandatory checks passed
- **CI:** all runs green on the released commit (or the documented exception, if the user approved one)
- **Smoke test:** passed against crates.io `=<confirmed-version>`

## Workspace releases

When releasing multiple workspace crates in one session:

1. Confirm version for **each** crate with the user (step 1 per crate).
2. `cargo metadata --no-deps --format-version 1` → resolve publish order (dependencies before dependents).
3. Run step 3 once at workspace root (or scoped per crate — all checks still mandatory).
4. One tag per repo is typical; confirm tag strategy with the user when crates version independently.
5. Publish each crate in order; run step 8 smoke test for each published crate.

## Inputs the user might give

| Input | Behavior |
|---|---|
| "dry run" / "preflight only" | Run steps 0–1 (version confirmation), 2 (tag convention), and 3 (checks). Propose tag in step 4 but do not create it. No publish, GitHub release, or smoke test. |
| `-p <crate>` | Scope all commands to that workspace member. |
| Explicit version (e.g. "release 2.1.0") | Use as the confirmed version in step 1; still require user confirmation before editing files. |

There is **no** "skip smoke test", "skip clippy", "skip CI wait", or "skip GitHub release" path in a full release.

## Gotchas

- **`cargo publish` publishes the local tree**, not necessarily what's on GitHub. Push commits before publishing if the remote should match.
- **Green local checks are not a green matrix.** Step 3 runs on one host; step 5a is what covers the platforms the project actually claims to support. For ABI- or target-sensitive crates the difference is the whole point — don't collapse the two.
- **Re-publishing the same version is impossible.** Confirm the target version carefully in step 1.
- **Tag convention ≠ semver in Cargo.toml.** A repo may tag `1.2.3` while others use `v1.2.3` — always derive from existing tags.
- **Feature flags / MSRV:** smoke test with default features; if the crate is heavily feature-gated, also run smoke tests with `--all-features`.
- **Binary crates:** smoke test via `cargo install <crate> --version <confirmed-version>` when a binary entry point is the primary artifact.
- **Pre-release semver** (`1.0.0-alpha.1`): confirm explicitly in step 1; tag and publish as-is.
- **crates.io token scopes:** publish needs `publish-new` / `publish-update`. If login fails, point user to https://crates.io/settings/tokens .
