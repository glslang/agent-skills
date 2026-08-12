---
name: use-xnoop
description: >-
  Analyze offline Apple XNU kernel-memory images with the Xn00p/xnoop.lite CLI:
  load segmented .mem and .zone dumps; inspect kernel identity, symbols, raw
  memory, typed structures, zones, processes, tasks, Mach ports, VM maps,
  vnodes, kexts, MAC policies, and I/O Registry state; search bytes or pointer
  references; and correlate findings with an XNU source checkout. Use when the
  user mentions xnoop or Xn00p, asks to inspect an XNU/iOS/macOS kernel-memory
  dump with this tool, supplies a kernel address or structure from an Xn00p
  image, or wants to relate this local dump to XNU source.
---

# Use Xn00p

Use Xn00p as a read-only, offline XNU memory-forensics tool. Preserve target identity, address form, command output, and uncertainty; memory fragments and typed decoders can be incomplete.

## Respect the tool and the data

- Honor the supplied LITE binary's banner: it restricts use to eligible OBTS 8.0 participants, offline, for personal and non-commercial use. Stop if the requested use falls outside those terms.
- Analyze only dumps the user is authorized to inspect. Kernel memory may contain credentials, tokens, messages, paths, or other private data; search narrowly and redact unrelated sensitive values from reports.
- Stay offline. Do not use `remote`, `image`, `plugin`, or `unsafe`. Do not use Xn00p's internal `>` redirection, `pmap save`, or any other argument-bearing `pmap` command.
- Treat the dump and `set.out` as immutable evidence. Do not edit, rename, or regenerate their fragments.

## Prepare

The configured fixture is:

- executable: `/Users/goncalo/OS_Security_Insecurity/xnoop/xnoop.lite`
- segmented dump: `/Users/goncalo/OS_Security_Insecurity/xnoop`
- source reference: `/Users/goncalo/OS_Security_Insecurity/xnu-xnu-11417.140.69`

Read [references/xnoop.md](references/xnoop.md) before selecting commands or correlating fields with source. It records the observed target identity, command grammar, LITE limitations, and source-version caveat.

Use [scripts/run-xnoop.sh](scripts/run-xnoop.sh) rather than invoking one analysis command directly. Xn00p is stateful: it must process `offline <dump-directory>` before subsequent commands in the same process, and it resolves the type library relative to its working directory. The runner handles both requirements.

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh \
  "search Darwin Kernel Version" \
  "pid 1"
```

Pass each complete REPL command as one quoted shell argument, and use full command names rather than Xn00p abbreviations. Commands in one invocation share session state. Override defaults only for a user-supplied compatible fixture:

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh \
  --binary /path/to/xnoop.lite \
  --dump /path/to/dump \
  "zprint"
```

## Investigate

1. Establish identity before interpreting memory. Inspect `set.out`, then corroborate the embedded build string with `search Darwin Kernel Version`. Record architecture, Darwin/XNU build, machine, slide, and dump path when available.
2. Choose the narrowest command that answers the question:
   - inventory or locate allocations: `zprint`, `zone <address>`, `pages <zone-name>`;
   - inspect a known process: `pid <pid> [all|fds|ports|mem]`;
   - inspect memory: `dump <absolute-address>,<length>` or `dump <address> <type>`;
   - resolve pointer variables: `dump <symbol> uint64_t`, then validate and type the returned address;
   - find data: `search <literal>` or `refs <absolute-address>`;
   - inspect kernel subsystems: `task`, `kexts`, `macp`, `ioreg`, `vnode`, `mountlist`, `vfstable`, `pmap`, or `ptov`.
3. Validate every important pointer before following it. Use `zone <address>` to check a heap object, confirm the address exists in a mapped fragment, and compare the reported zone with the expected Xn00p type.
4. Corroborate a structural conclusion with at least two available signals: a typed dump, the containing zone, a second pointer path, a raw dump, a related high-level command, or XNU source semantics.
5. Run fragile or broad traversals in a fresh invocation. On this fixture, `ps` has produced a `SIGBUS`; prefer `pid <n>` when the PID is known and report crashes as tool limitations rather than dump facts.

## Handle symbols and addresses carefully

- Treat addresses passed to `dump`, `zone`, `refs`, `task`, and similar commands as live absolute kernel virtual addresses unless the command explicitly says otherwise.
- Use `sdump` only for a known unslid address. Label slid, unslid, and PAC-stripped values distinctly in notes.
- Force pointer-valued globals to a primitive when dereferencing them. For example:

  ```bash
  .claude/skills/use-xnoop/scripts/run-xnoop.sh "dump _kernel_task uint64_t"
  .claude/skills/use-xnoop/scripts/run-xnoop.sh \
    "zone 0xffffffeb9d57da40" \
    "dump 0xffffffeb9d57da40 task"
  ```

- Do not assume `dump _pointer_symbol,8` is raw. A known symbol type can override the requested length and decode the variable's storage as the pointee. Use `uint64_t`, then issue a second typed dump at the returned pointer.
- Expect ARM64e PAC. Use `unpac <address>` when appropriate, but preserve the original value. LITE cannot search references to some PACed addresses.
- Treat plausible-looking decoded fields as provisional when duplicate/colliding type definitions, missing pages, failed reads, or impossible values appear.

## Correlate with XNU source

Use the source tree to understand invariants, ownership, field meaning, list topology, flags, and call paths. Search with `rg` before opening a file:

```bash
rg -n "struct task|bsd_info_ro" /Users/goncalo/OS_Security_Insecurity/xnu-xnu-11417.140.69/osfmk/kern/task.h
rg -n "struct proc|p_proc_ro" /Users/goncalo/OS_Security_Insecurity/xnu-xnu-11417.140.69/bsd/sys/proc_internal.h
rg -n "struct zone|z_elems_free" /Users/goncalo/OS_Security_Insecurity/xnu-xnu-11417.140.69/osfmk/kern/zalloc_internal.h
```

The supplied dump identifies itself as `xnu-11215.2.5~62`, while the source checkout is `xnu-11417.140.69`. Therefore:

- use Xn00p's `type <name>` and dump behavior as the primary evidence for this image's layout;
- use the newer checkout as a semantic reference, not proof of field offsets, sizes, feature gates, or list representation;
- call out any conclusion that depends on a cross-version assumption, and seek a matching `xnu-11215.2.5` source/tag when exact layout matters.

## Interpret startup and partial-read diagnostics

- `offline: No such variable` can appear while loading this fixture's `set.out`; it is not fatal by itself when load-command ranges appear and initialization reaches `XnuInit: 0`.
- `Some colliding fields detected` warns that typed output needs extra scrutiny.
- `Not in offline image`, a missing metadata page, or a truncated queue means the segmented acquisition lacks that range. Do not infer a null pointer or absent object from a failed read.
- Xn00p mixes buffered stdout and stderr, so diagnostics can precede the banner or command output. Interpret content, not apparent print order.
- Preserve nonzero exits and signals. Retry only with a narrower, read-only command in a fresh session.

## Report

Lead with the finding, then include:

- dump identity and the exact Xn00p LITE build;
- the smallest reproducible runner command(s);
- addresses labeled as absolute, unslid, or PAC-stripped;
- the evidence chain and containing zones/types;
- missing ranges, decoder warnings, crashes, and source-version mismatches that affect confidence;
- any artifact path created, or state explicitly that the analysis was read-only.
