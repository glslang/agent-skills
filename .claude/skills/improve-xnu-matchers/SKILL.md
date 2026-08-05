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

## 4. Judge what survives — the part the script cannot do

The scanner emits *candidates*. Check each one you intend to keep:

- **Inlining.** The containing function must survive as its own function in the binary. A `static` function called from one place usually does not — the string ends up inside the *caller*, so the rule names the wrong function. The scanner tags these `[static - may be inlined]`; for those, walk up to the outermost non-inlined caller and use that name. Existing entries document exactly this, e.g. `_thread_init` carries a note that it inlines `machine_thread_init`.
- **C++ symbols.** `.cpp` candidates are tagged `[C++ - needs mangled symbol]`. The existing file uses mangled names (`__ZN6OSKext14autounloadKextEPS_`) far more often than demangled ones — prefer mangled. Build it from the real signature, or confirm against a symbol you can already see in the companion file.
- **Uniqueness.** The scanner drops patterns whose truncated form appears more than once in the tree, but the *linker* also coalesces identical strings across the image. If a rule must share a pattern, place it after the existing one and note why.
- **Unmapped callees.** With `--all-callees` the arg index is taken straight from the C source with no rewrite applied. Read the prototype and confirm before accepting.

## 5. Append and report

Add surviving rules to the end of their `arg#` section, each with a trailing `path/file.c` comment — the existing file uses that consistently and it is what makes the next pass maintainable. Keep the licence comment block intact.

Report: source tag vs kernel version, candidates scanned, how many passed the kernel gate, how many you appended, and anything you rejected on judgement with the reason.

## Optional deeper verification

Neither of these is required, and both have caveats worth knowing before spending time:

- **`disarm --analyze`** regenerates the companion file and applies matchers, with `JMD=1` printing per-rule usage. Its "unused" report is **not** a reliable staleness signal — in testing against both a Darwin 24 and a Darwin 25 kernelcache it reported 455+ of 459 string rules unused while region/immediate rules fired normally, and no string-derived symbols reached the companion file. Treat a low used-count as "this check told us nothing", never as grounds to touch a rule. Note `--analyze` refuses to run when a companion file already exists, and `JA=1` is no longer supported.
- **Binary Ninja** can confirm the argument register and the enclosing function properly. Headless automation needs a Commercial/Ultimate licence; a Personal licence fails at `_init_plugins` with "License is not valid" regardless of CLI availability. With a GUI-only licence, drive it from the built-in Python console instead of scripting it.
