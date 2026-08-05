---
name: improve-xnu-matchers
description: Grow a disarm/jtool2 `.matchers` file by mining XNU source for string literals that identify kernel functions, so more of a stripped kernelcache gets symbolicated. Scans a local XNU tree or fetches the matching tag from GitHub, derives `arg#|pattern|containing_function|calling_function` lines, verifies each pattern exists in the target kernel, and appends only new rules. Use when the user asks to "improve the matchers", "add matchers from source", "symbolicate more of the kernelcache", "update xnu.matchers", "find new matcher patterns", or points at a `.matchers` file and an XNU source tree.
---

# Improve XNU Matchers From Source

A `.matchers` file teaches `disarm` to name functions in a stripped kernelcache. Each rule says: *"the function that passes this string to that callee is named X."* Apple ships kernelcaches stripped but leaves the format strings in `__TEXT.__cstring`, so every `panic("...")` in the XNU source is a potential symbol.

This skill turns XNU source into new matcher rules. The mechanical part is scripted; the judgement part is not, and skipping it produces rules that silently never fire.

## The one thing to get right

```
arg#|pattern|function_this_is_called_in|calling_function|trailing comment
```

**`arg#` is the argument position in the call the compiler *emits*, not the call as written in C.** Macros that prepend arguments and thin wrappers that get inlined both shift it. Three examples from the existing file:

| Source | Emitted | `arg#` |
|---|---|---|
| `panic("...")` | `_panic(fmt)` | 0 |
| `os_log(log, "...")` | `_os_log_internal(dso, log, type, fmt)` | **3** |
| `thread_set_thread_name(th, "...")` | inlines to `_bsd_setthreadname(info, tid, name)` | **2** |

Get this wrong and the rule is inert — it costs nothing and does nothing, which is why stale wrong rules accumulate unnoticed. `reference/callsites.md` has the derivation method and the verified table.

## Hard rules

- **Additive only.** Never delete, rewrite, or reorder an existing rule, and never "clean up" ones that look stale. A pattern absent from *this* kernel is still correct for another build the user cares about. Append to the end of the matching `arg#` section.
- **Patterns are exact prefix matches.** Truncating is always safe; the pattern must match the binary string from character one.
- **No `|` in a pattern** — it is the field separator. No newlines or escapes either: the binary holds the decoded bytes, so cut the pattern before the first `\n`.
- **`arg#` is 0–3 only.** A string at position 4+ cannot be expressed; drop the candidate.
- **Order matters.** Two rules with the same pattern apply first-match-then-disable. Prefer patterns unique across the source tree so ordering never matters.

## 1. Identify the target kernel version, then match the source to it

This is the step that decides whether the whole run is useful. Source from the wrong XNU version yields rules for strings that do not exist in the target.

```bash
strings -a <kernel> | grep -o 'xnu-[0-9.]*' | sort -u
```

Take the local tree if its version matches. Otherwise fetch the closest published tag (`apple-oss-distributions/xnu` publishes tags a little behind shipping builds — pick the nearest, and expect some drift):

```bash
gh api repos/apple-oss-distributions/xnu/tags --paginate --jq '.[].name' | head -20

curl -sL https://codeload.github.com/apple-oss-distributions/xnu/tar.gz/refs/tags/<tag> \
  | tar xz -C /path/to/work
```

State the version pairing in your report. If they differ, say so — it explains the hit rate.

## 2. Scan the source for candidates

```bash
python3 scripts/xnu_scan.py \
  --source <xnu-tree> \
  --matchers <existing.matchers> \
  > candidates.txt
```

The scanner blanks comments and literals, finds function bodies by XNU's column-0 brace style, walks out from each string to the call that contains it, applies the `CALLSITES` rewrites, and drops anything already covered by the existing file. It runs in a few seconds over the whole tree.

Useful narrowing:

| Flag | Use |
|---|---|
| `--callee panic,zone_create` | target one call family |
| `--subsystem osfmk/kern` | one subsystem |
| `--arch arm64` | default; keeps `osfmk/i386` out of an ARM64 run |
| `--all-callees` | propose calls absent from the table — **verify each arg index by hand** |
| `--include-guarded` | include `#if DEVELOPMENT`/`CONFIG_*` strings (usually absent from RELEASE) |

## 3. Gate candidates on the real kernel

A rule can only fire if its pattern is a prefix of a string actually in the kernel. This catches config-guarded strings, version drift, and transcription slips in one pass:

```bash
python3 scripts/xnu_verify.py --kernel <kernel-macho> --matchers candidates.txt --only-present
```

Any decompressed kernel Mach-O works. If the user only has an IM4P kernelcache, `disarm -f "<pattern>" <kernelcache>` does the same check one pattern at a time and handles the IM4P/fileset unwrap itself.

**Discard everything reported ABSENT.** It does not matter how right the source looked.

## 4. Resolve inlining and `arg#` against the binary

The scanner can only guess at inlining from `static` in the source, and takes
`arg#` on faith from the `CALLSITES` table. The kernel answers both exactly,
using data already in the file — no disassembler licence needed:

```bash
python3 scripts/xnu_inline_check.py --kernel <kernel-macho> --matchers candidates.txt
```

It decodes `LC_FUNCTION_STARTS` for real function boundaries (the same data
disarm uses), scans `__text` for the ADRP+ADD / ADR pairs that materialise each
string, and maps every candidate to the binary function that references it.
Runs in under a second. Verdicts:

| Verdict | Meaning | Action |
|---|---|---|
| `OK` | one referencing function, unshared, and the string lands in the register the rule claims | trust the rule |
| `ARGBAD` | the string is materialised into a different argument register than `arg#` says | fix `arg#` to the register reported |
| `ARGUNK` | `arg#` not proven here — the string is built in x4+ or in several registers across sites | check by hand; do not append on trust |
| `SHARED` | the binary function also holds strings belonging to *other* source functions — something was inlined | re-check which function to name; the report lists who else landed there |
| `MULTI` | string referenced from more than one function | ambiguous; pick deliberately or drop |
| `NOREF` | string present but no ADRP+ADD/ADR reference found | may be reached another way; verify by hand |

`SHARED` is the name-free inlining tell: the kernel is stripped (`nsyms 0`), so
nothing recovers names, but if candidates from two different source functions
resolve to one binary function then at least one of them was inlined and names
the wrong thing. Confirmed against source — e.g. `SecureDTInit` is small enough
that its `panic("DeviceTree overflow:")` ends up inside `_PE_init_platform`, so
a rule naming `_SecureDTInit` could never fire.

`ARGBAD` works because the compiler almost always builds the string directly in
its argument register: `ADRP X2, … ; ADD X2, X2, #201` *is* `arg# = 2`. When it
does not — the string goes into a callee-saved register like x23 and is moved
into place later, or several sites in one function use different registers —
`arg#` is simply not established, and that is `ARGUNK` rather than `OK`. Only an
exact match between the observed register set and the declared `arg#` earns
`OK`, because `--bare` emits `OK` rows for appending and an unproven row would
land in the matchers file dressed as a verified one. It has
already caught a real error — `IOCurrentTaskHasEntitlement` is `OS_ALWAYS_INLINE`
and forwards to `IOTaskHasEntitlement(NULL, entitlement)`, so its string is at 1,
not 0. Treat `CALLSITES` as a prior and this as the evidence.

To see a call fully resolved, disassemble the function the checker names —
disarm emulates registers and prints the synthesized call:

```bash
disarm -a 0x<func_start>-0x<func_start+0x80> <kernel>
#  ADD X2, X2, #201  ; ... = 'Break 0x%04X instruction exception from kernel...'
#  _snprintf(0xfffffe000b2f6aa0, 0x400, "Break 0x%04X instruction exception...")
```

Add `--only OK --bare` to emit clean matcher lines ready to append.

**This check supersedes the `[static - may be inlined]` tag**, in both
directions: of 638 source-flagged candidates in a full run, 286 were `OK` (false
alarm, the function survived) and 352 were `SHARED`/`MULTI` (real problem). The
tag is a prior; this is the evidence.

## 5. Judge what is left — the part no script can do

- **C++ symbols.** `.cpp` candidates are tagged `[C++ - needs mangled symbol]`, and no binary check helps: with `nsyms 0` there are no names in the kernel to compare against. The existing file uses mangled names (`__ZN6OSKext14autounloadKextEPS_`) far more often than demangled ones — prefer mangled, built from the real signature.
- **`SHARED` candidates.** The report names the other source functions sharing the binary function. Usually the right fix is to name the *caller* instead of the inlined callee — that is what existing entries do, e.g. `_thread_init` carries a note that it inlines `machine_thread_init`.
- **Uniqueness.** The scanner drops patterns whose truncated form appears more than once in the tree, but the *linker* also coalesces identical strings across the image. If a rule must share a pattern, place it after the existing one and note why.
- **Unmapped callees.** With `--all-callees` the arg index is taken straight from the C source with no rewrite applied. Read the prototype and confirm before accepting.
- **`ARGBAD` and `SHARED` on the same rule.** Only one verdict is reported per candidate; a rule can be wrong in both ways. Fix the function name first, then re-run.

## 6. Append and report

Add surviving rules to the end of their `arg#` section, each with a trailing `path/file.c` comment — the existing file uses that consistently and it is what makes the next pass maintainable. Keep the licence comment block intact.

Report: source tag vs kernel version, candidates scanned, how many passed the string gate, the `OK`/`SHARED`/`MULTI` split, how many you appended, and anything you rejected on judgement with the reason.

## Optional deeper verification

Neither of these is required, and both have caveats worth knowing before spending time:

- **`disarm --analyze`** regenerates the companion file and applies matchers, with `JMD=1` printing per-rule usage. Its "unused" report is **not** a reliable staleness signal — in testing against both a Darwin 24 and a Darwin 25 kernelcache it reported 455+ of 459 string rules unused while region/immediate rules fired normally, and no string-derived symbols reached the companion file. Treat a low used-count as "this check told us nothing", never as grounds to touch a rule. Note `--analyze` refuses to run when a companion file already exists, and `JA=1` is no longer supported.
- **Binary Ninja** buys less than it first appears. Enclosing function and `arg#` are both answered by `xnu_inline_check.py` and `disarm -a` for free, and C++ mangling is unanswerable from a stripped kernel either way. What a headless licence would add is proper dataflow for the residue — strings moved through a scratch register before the call, or an ADRP/ADD split across basic blocks, which the linear scan reports as `NOREF`. Headless needs Commercial/Ultimate; a Personal licence fails at `_init_plugins` with "License is not valid" regardless of CLI availability. Ghidra's `analyzeHeadless` is free and does the same dataflow.

## Limits of the binary checks

Worth knowing before trusting a verdict:

- The ADRP page is tracked **per register in linear order**, not along control flow. Compilers emit ADRP+ADD adjacently in practice, but a pair split across basic blocks can be missed or mispaired. `NOREF` is the usual symptom.
- The register check reads where the string is *built*, not what is live at the call. A string built in x1 and moved to x2 before the call reads as arg 1, and one built in a callee-saved register reads as `ARGUNK`. When a verdict looks wrong, disassemble the function and check — the `CALLSITES` prior and the shipped file are both evidence too.
- `SHARED` is computed **only across the candidate set**. A binary function can hold inlined strings the scan never proposed, so `OK` means "nothing in this batch contradicts it", not "provably not inlined".
- Function boundaries come from `LC_FUNCTION_STARTS`. If a kernel lacks it, this check cannot run at all — it exits rather than guessing.
- Strings are read from `__cstring`, `__os_log`, and `__TEXT,__const`. A literal placed elsewhere reports `NOSTR` even though `strings` finds it.
