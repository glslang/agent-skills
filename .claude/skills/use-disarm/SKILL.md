---
name: use-disarm
description: >-
  Inspect and reverse-engineer binaries with the disarm CLI: identify Mach-O,
  ELF, and PE metadata and regions; translate addresses and file offsets;
  extract or smart/hexdump sections and entitlements; search strings, bytes,
  references, and gadgets; disassemble ARM64 instructions, ranges, files,
  kernelcaches, and dyld shared-cache images; inspect symbols and Mach-O
  signatures; produce patched copies; and create or use companion and matcher
  files for persistent symbolication. Use when the user mentions disarm,
  supplies an ARM64 opcode or binary for command-line
  inspection/disassembly, asks for disarm-based reversing or symbolication,
  or needs help with disarm companion/matcher syntax. For mining XNU source
  specifically to grow a matcher file, use the improve-xnu-matchers skill as
  well.
---

# Use disarm

Use `disarm` as a format-aware binary inspector, ARM64 disassembler, dumper, search tool, and lightweight analysis engine. Prefer targeted commands and preserve exact addresses, offsets, architecture, and build identity in the result.

## Prepare

1. Resolve the executable with `command -v disarm`. If it is absent, use the path supplied by the user or ask where it is installed; do not download a replacement implicitly.
2. Run `disarm -h` once when syntax or build behavior matters. Nightly builds differ, and the long help reports the compile date and known decoder gaps.
3. Inspect the target with `file <binary>`, then start with:

   ```bash
   disarm -i <binary>
   disarm -l <binary>
   ```

4. For a universal Mach-O, select a slice with `ARCH=<arch>` on every command. Record the selected slice. Do not assume the host architecture is the intended target.
5. Quote all paths, search strings, and region names containing spaces. Keep color off when parsing output.

## Route the task

- Read [references/cli.md](references/cli.md) for instruction lookup, metadata, regions, address/offset conversion, dumps, extraction, searches, references, gadgets, disassembly, symbols, signatures, formatting, shared caches, or patching.
- Read [references/analysis.md](references/analysis.md) before creating/editing companions, running `--analyze`, supplying `JMATCHERS`, or writing argument, region, fixed-address, or opcode matcher rules.
- Use `improve-xnu-matchers` in addition to this skill when the task is specifically to mine XNU source and append verified matcher candidates.

## Default investigation flow

1. Establish identity with `-i`: format, architecture, target OS, entry point, image size, UUID/build ID, and code-signing status.
2. Establish layout with `-l`. Use `-I` or `-L -v` only when format-native header or section details matter.
3. Convert between virtual addresses and file offsets with `-A` and `-O`. Never report one as the other.
4. Narrow before disassembling:
   - Use `-a <address>[-<address>]` for a virtual-address range.
   - Use `-o <offset>[-<offset>]` for a file-offset range.
   - Use `-r <region>` for a named region.
5. Use normal disassembly when arguments, resolved pointers, or synthesized calls matter. Add `-q` only when speed matters more than register following.
6. Corroborate important conclusions with at least two available signals: region metadata, strings, references, resolved calls, symbols, companion entries, or a second disassembler for uncertain opcodes.

## Preserve evidence and files

- Treat target binaries as read-only by default. Parsing or disassembling a binary does not execute it.
- Recognize side effects: `-e` writes an extracted file; `--companion` and `--analyze` create a companion in the target directory or current directory; the current `-P` implementation creates/truncates `/tmp/out` without an atomic no-clobber option.
- Invoke `-P` only inside an isolated environment whose filesystem root and `/tmp` are private and not host-mounted. A host-side existence or symlink check is race-prone and is not a safety guarantee. If isolation is unavailable, use another patcher with an explicit atomic/no-clobber destination. Verify the exact preimage/postimage bytes before exporting the result, and expect Mach-O code signatures to become invalid.
- Before analysis, choose the working directory deliberately and list existing companion files. `disarm` refuses to overwrite them; do not delete or replace one without user authorization.
- Keep raw command output or extracted artifacts only when the user asks for them. Report every created path.

## Interpret conservatively

- Expect format inspection for Mach-O, ELF, and PE, but expect instruction disassembly to be ARM64-focused. Metadata operations can still work on unsupported instruction architectures.
- Treat register tracking as lightweight emulation, not full control-flow analysis. A reconstructed call is evidence, not proof of every runtime value.
- Cross-check rare SIMD/SVE/SME, floating-point, system-register, or bitmask instructions when a decode looks suspicious; the tool reports incomplete areas in its help.
- Remember that fat binaries, IM4P/kernelcache payloads, and local dyld shared-cache images may be unwrapped or selected before offsets are displayed. State which logical image an address or offset belongs to.
- Tie companion and matcher findings to the target UUID/build ID. Symbols from another build can be dangerously plausible.
- Pair matcher files with a compatible `disarm` release. License markers and accepted rule families have changed between builds, and an incompatible file may be rejected before analysis.

## Report

Lead with the finding, then include:

- target path, format, architecture/slice, UUID/build ID, and any rebase;
- the smallest reproducible `disarm` commands;
- findings with virtual addresses and file offsets labeled explicitly;
- output or companion/extraction paths created;
- decoder, emulation, signing, or build-mismatch caveats that affect confidence.
