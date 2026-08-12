# Xn00p offline reference

Use this reference for the supplied `xnoop.lite` 2.0-IBZ binary and segmented XNU dump. Command behavior is based on the binary's built-in help and direct read-only tests against the fixture; it is not a vendor manual.

## Contents

- [Local fixture](#local-fixture)
- [Invocation model](#invocation-model)
- [Command map](#command-map)
- [Reliable workflows](#reliable-workflows)
- [Known limitations and diagnostics](#known-limitations-and-diagnostics)
- [XNU source correlation](#xnu-source-correlation)
- [Public supplemental material](#public-supplemental-material)

## Local fixture

| Item | Value |
|---|---|
| Xn00p | `/Users/goncalo/OS_Security_Insecurity/xnoop/xnoop.lite` |
| Binary identity | Mach-O 64-bit arm64, Xn00p LITE `2.0-IBZ` |
| Dump directory | `/Users/goncalo/OS_Security_Insecurity/xnoop` |
| Dump shape | 113 `.mem` fragments and 8,423 `.zone` fragments, about 205 MB at inspection time |
| Type data | `xn00p.types.18.0` |
| Target config | `set.out` |
| Target | `iPhone14,6`, Darwin 24.0.0, `RELEASE_ARM64_T8110` |
| Dump XNU build | `xnu-11215.2.5~62` |
| Configured slide | `0x3cd08000` |
| Source reference | `/Users/goncalo/OS_Security_Insecurity/xnu-xnu-11417.140.69` |

The dump's XNU build and source checkout do not match. Treat the checkout as a newer semantic reference, not an exact layout oracle.

## Invocation model

`xnoop.lite <analysis-command>` starts without an attached target. The useful form is a stateful stdin session:

```text
offline /path/to/dump
command one
command two
```

Use the bundled runner, which validates the inputs, changes to the dump directory so Xn00p can find `xn00p.types.*`, prepends `offline`, keeps all requested commands in one process, and allowlists full read-only/session-local command names. It rejects abbreviations, target-changing commands, `pmap save`, and Xn00p-internal file redirection:

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh "zone 0xffffffeb9d57da40"
```

Use one fresh runner invocation for each independent question. Group commands only when a later command depends on state established by an earlier command.

## Command map

### Identity, metadata, and arithmetic

| Command | Purpose and cautions |
|---|---|
| `help` | List commands registered after target initialization. `help <command>` is not reliably command-specific in this LITE build. |
| `version` | Print Xn00p build. The startup banner also reports it. |
| `info` | Request target/kernel information; corroborate with `set.out` and a memory search. |
| `syms [slid]` | List known symbols, optionally at runtime addresses. Output is build-dependent. |
| `sym <name> <address> [type]` | Add a session-local symbol. Record why it is valid before relying on it. |
| `type <name>` | Print Xn00p's definition for one type. Use this before reasoning about offsets. |
| `types` | List known types; output can be very large. |
| `hex <expression>` | Perform hexadecimal arithmetic. |
| `slide <address>` | Apply the configured kernel slide. |
| `unslide <address>` | Remove the configured kernel slide. |
| `unpac <address>` | Strip PAC bits. Preserve the original address alongside the result. |
| `cache` | Show cached reads for the current session. |

### Memory, search, and references

| Command | Purpose and cautions |
|---|---|
| `dump <symbol-or-address>[,<length>]` | Dump memory. Symbols are auto-slid; numeric addresses are absolute. A known symbol type may override the length. |
| `dump <symbol-or-address> <type>` | Force a typed interpretation, including primitive `uint64_t`. |
| `dump <symbol-or-address> smart` | Ask Xn00p to infer a useful interpretation; verify it independently. |
| `sdump <address>[,<length>]` | Apply the slide before dumping. Use only when the input is definitely unslid. |
| `search <literal-or-pattern>` | Search mapped image memory and print matching addresses, zones/segments, and nearby bytes. Narrow searches to avoid excessive or private output. |
| `refs <absolute-address>` | Find stored references to an address. LITE reports that references to PACed addresses are unsupported. |
| `visualize ...` | Not available in LITE. |

Xn00p supports internal `>` output redirection, but the runner blocks it. If the user asks to preserve output, use ordinary shell redirection on the runner after validating the destination; this also captures the full session context.

### Zones and VM

| Command | Purpose and cautions |
|---|---|
| `zone <absolute-address>` | Report the containing zone and metadata address, or report that no zone contains it. |
| `zone` | Request zone-map information in builds that support the no-argument form. |
| `zprint` | Print the zone inventory with element sizes, allocation sizes, counts, and usage. Expect hundreds of lines. |
| `pages <zone-name>` | Walk the zone's page queues. Spaces in a zone name remain part of the quoted runner argument. Missing metadata fragments can truncate queues. |
| `walk zone [zone-name]` | Build-dependent zone walker. This fixture's build has emitted only a placeholder for some forms; prefer `zprint` plus `pages`. |
| `pmap` | Walk the kernel pmap. Potentially broad. |
| `pmap <argument>` | Blocked by the runner because `pmap save` writes mapped data; do not pass any argument to `pmap`. |
| `ptov <address>` | Translate an address using the target's physical/virtual mapping data. Validate whether the input is physical or virtual from the result. |

### Processes and kernel structures

| Command | Purpose and cautions |
|---|---|
| `pid <pid>` | Show the process, `proc_ro`, task, IDs, and VM map for one PID. Tested successfully with PIDs 0 and 1. |
| `pid <pid> all` | Request the fullest supported per-process view. Potentially large. |
| `pid <pid> fds` | Focus on file descriptors. Memory may expose paths and other private data. |
| `pid <pid> ports` | Focus on the task's Mach port namespace. |
| `pid <pid> mem` | Focus on process memory/map state. |
| `ps` | Walk all processes. This command produced `SIGBUS` on the supplied fixture; prefer `pid` for known targets. |
| `task <absolute-task-address>` | Inspect a task address; Xn00p expects it to reside in the task/proc-task zone. |
| `walk <family>` | Traverse the `zone`, `proc`, `task`, or `kmod` structure family. Treat placeholder, incomplete-read, or crash output as a limitation. |
| `kexts` | Dump loaded-kext summaries. |
| `macp` | Dump loaded MAC policies. |
| `ioreg [arguments]` | Dump or search the I/O Registry. Start narrowly where arguments are supported. |
| `vnode <absolute-vnode-address>` | Print detailed vnode information and attempt path reconstruction. |
| `mountlist` | Walk mounted filesystems. |
| `vfstable` | Walk the VFS configuration list. |

Do not use `remote`, `image`, `plugin`, or `unsafe`. They are outside this offline read-only workflow and some are unavailable or license-restricted in LITE.

## Reliable workflows

### Confirm dump identity

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh "search Darwin Kernel Version"
```

The fixture returns the target build string in `__PRELINK_TEXT.mem` and a copied allocation. Record the kernel-text match as the stronger provenance signal.

### Dereference a pointer-valued global

First force the symbol storage to a primitive:

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh "dump _kernel_task uint64_t"
```

The observed fixture returns `0xffffffeb9d57da40`. Validate and decode it in a new read-only session:

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh \
  "zone 0xffffffeb9d57da40" \
  "dump 0xffffffeb9d57da40 task"
```

Do not decode the address of `_kernel_task` itself as `task`; that address stores a pointer, not the task object.

### Inspect a process without walking the whole list

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh "pid 1"
```

Follow only the task, VM map, FDs, or ports needed for the question. Validate returned heap pointers with `zone` before typed dumps.

### Locate and inspect a string

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh "search Darwin Kernel Version"
.claude/skills/use-xnoop/scripts/run-xnoop.sh "dump 0xfffffff043d49c55,80"
```

Treat search result addresses as absolute. Keep the second dump short and relevant.

### Inspect zone state

```bash
.claude/skills/use-xnoop/scripts/run-xnoop.sh "zprint"
.claude/skills/use-xnoop/scripts/run-xnoop.sh "pages proc_task"
```

Use `zprint` to establish the zone's index, element size, and counts. Use `pages` only when queue/chunk topology matters.

## Known limitations and diagnostics

- `offline: No such variable` appears while this fixture loads `set.out`. Initialization has still succeeded when Mach-O load-command ranges are printed and output reaches `XnuInit: 0`.
- `Type init unsuccessful` followed by unknown-field warnings usually means Xn00p was started outside the directory containing `xn00p.types.*`. Use the runner rather than continuing with degraded typed output.
- `Some colliding fields detected, but not warning` means definitions overlap. Validate offsets and values rather than suppressing it.
- The acquisition is sparse. `Not in offline image`, failed metadata reads, and truncated queue walks are expected possibilities; they prove only that the necessary fragment was not acquired.
- `ps` has exited with signal 10 (`SIGBUS`, shell status 138) on this exact fixture. Do not repeatedly retry it.
- `refs` cannot handle some PACed targets in LITE. Try a justified `unpac`, preserve both values, and state the limitation.
- `visualize` and remote/live capabilities are unavailable in LITE.
- Stdout and stderr buffering can place initialization diagnostics before the banner. Apparent line order is not always execution order.
- Typed structure output can include unions, conditional fields, or duplicate aliases at the same offsets. Do not count aliases as independent fields.

## XNU source correlation

Useful starting points in the supplied checkout are:

| Xn00p concept | Newer XNU source reference |
|---|---|
| `task` | `osfmk/kern/task.h` |
| `thread` | `osfmk/kern/thread.h` |
| `proc` | `bsd/sys/proc_internal.h` |
| `proc_ro` | `bsd/sys/proc_ro.h` |
| `zone` | `osfmk/kern/zalloc_internal.h`, `osfmk/kern/zalloc.c` |
| `ipc_port` | `osfmk/ipc/ipc_port.h` |
| `_vm_map`, `vm_map_entry` | `osfmk/vm/vm_map_xnu.h` |
| `vnode` | `bsd/sys/vnode_internal.h` |

Search definitions and all consumers of a field:

```bash
rg -n "bsd_info_ro|pr_proc|pr_task" /Users/goncalo/OS_Security_Insecurity/xnu-xnu-11417.140.69
```

Use the source to explain meaning and invariants. Do not copy an offset from `xnu-11417.140.69` into an `xnu-11215.2.5~62` interpretation without build-matched evidence. Conditional compilation, opaque substructures, security hardening, and allocator changes can all move fields.

## Public supplemental material

No public standalone manual was located during skill creation. Jonathan Levin's public *OS Internals “Kernel Memory Management” chapter contains concrete Xn00p examples for `syms slid`, raw and typed `dump`, and zone walking:

<https://newosxbook.com/bonus/democratizingZones.pdf>

Use it for conceptual examples only. Its shown builds and command output differ from this Xn00p LITE 2.0 fixture.
