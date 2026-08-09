# disarm CLI reference

Use this reference for direct inspection and disassembly. Examples use `disarm`; substitute the resolved executable path if it is not on `PATH`.

## Contents

- [Invocation and target selection](#invocation-and-target-selection)
- [Information and regions](#information-and-regions)
- [Addressing and rebasing](#addressing-and-rebasing)
- [Dumping and extraction](#dumping-and-extraction)
- [Searching, references, and gadgets](#searching-references-and-gadgets)
- [Disassembly](#disassembly)
- [Symbols and signatures](#symbols-and-signatures)
- [Output controls](#output-controls)
- [Patching](#patching)
- [Practical workflows](#practical-workflows)

## Invocation and target selection

### Decode one ARM64 instruction

Pass a 32-bit word or four little-endian bytes:

```bash
disarm 0xd503201f
disarm 1f 20 03 d5
disarm -v 0xd965a31a
```

Plain mode prints the decoded instruction. `-v` also interprets the value as signed/unsigned decimal, binary, byte-swapped big endian, float, ASCII, and a string. Feature-specific instructions may be annotated, such as `FEAT_MTE`.

### Select a universal Mach-O slice

```bash
ARCH=arm64e disarm -i <fat-binary>
ARCH=arm64e disarm -e arch <fat-binary>
```

Use a value actually listed by the fat-file diagnostic, commonly `arm64`, `arm64e`, or `x86_64`. `-e arch` extracts the selected slice, even when later instruction disassembly is unsupported for that architecture.

### Inspect a dyld shared-cache image on Darwin

```bash
disarm -i :
disarm -i :libobjc.A.dylib
```

`:` addresses the local in-memory shared cache; `:<image>` selects an image. This is a current Darwin feature and may not exist in older builds.

### Containers

`disarm` recognizes some encapsulated inputs such as fat binaries and IM4P kernelcaches. It may select a slice, decompress a BVX2 payload, or operate on an inner image. Read its diagnostic lines before interpreting offsets. If it reports `IM4P...But contents are unknown`, `No regions to iterate over`, or an unrecognized format, preserve that as the result; do not pretend offsets belong to an unwrapped image.

Mach-O fileset kernelcaches can expose hundreds of bundle-named regions such as `com.apple.kernel`, not ordinary leaf-section names. A bundle region may begin with an embedded Mach-O header rather than pure instructions. Use `-i`/`-l`, `-A`/`-O`, and a precise `-a` range to identify real text before interpreting it as code.

## Information and regions

| Command | Purpose |
|---|---|
| `disarm -i <file>` | Format-agnostic identity: file type, format, OS, architecture, size, entry, common regions, UUID/build ID, signature status |
| `disarm -I <file>` | Format-specific headers and details, analogous to selected `otool`, `readelf`, `objdump`, or `dumpbin` views |
| `disarm -l <file>` | Normalized regions with file ranges, virtual-address ranges, names, flags, and sizes |
| `disarm -L <file>` | Format-native load commands, program/section headers, or PE details |
| `disarm -L -v <file>` | More detailed format-native region/header listing |

Use lowercase `-i/-l` for portable parsing across Mach-O, ELF, and PE. Use uppercase `-I/-L` for format semantics such as Mach-O load commands, ELF dynamic entries, or PE-specific structures.

## Addressing and rebasing

| Command | Meaning |
|---|---|
| `disarm -A 0x<va> <file>` | Map a virtual address to a file offset and containing region |
| `disarm -O 0x<off> <file>` | Map a file offset to a virtual address and containing region |
| `disarm -a 0x<va>[-0x<va>] <file>` | Disassemble/dump a virtual-address range |
| `disarm -o 0x<off>[-0x<off>] <file>` | Disassemble/dump a file-offset range |
| `disarm -b 0x<base> <file>` | Rebase a raw or supported image to a virtual base |
| `BASE=0x<base> disarm ... <file>` | Environment form of `-b` |

The installed help text describes `-a` imprecisely; direct use confirms that `-a` accepts mapped virtual addresses while `-o` accepts file offsets. Confirm a range with `-A`/`-O` and the region list before drawing conclusions.

## Dumping and extraction

### Classic hexdump

```bash
disarm -d <file>
```

This is intentionally close to `hexdump -C`. For an encapsulated input it dumps the selected/decompressed inner payload, not necessarily the container bytes.

### Smart-dump a region

```bash
disarm -l <file>
disarm -r <region-name> <file>
disarm -d -r <region-name> <file>
```

Without `-d`, `-r` chooses a semantic dumper from region metadata and known names. Mach-O handlers can interpret C strings, CFStrings, Objective-C/Swift metadata, MIG, vtables, exception tables, chained pointers, and other recognized structures. Add `-d` for raw canonical hex.

If a smart dump produces implausible instructions or structure fields, do not force the interpretation. Re-run the exact region with `-d`, inspect its header bytes, and narrow to a more specific child region or address range.

Use the exact name printed by `-l`/`-L`, for example:

```bash
disarm -r __TEXT.__cstring <macho>
disarm -r .rodata <elf>
disarm -r .rdata <pe>
```

### Entitlements

```bash
disarm -r entitlements <macho>
disarm -r 'entitlements DER' <macho> | openssl asn1parse -inform DER
```

The first dumps legacy XML entitlements when present. The second emits DER data for external ASN.1 parsing.

### Extract

```bash
disarm -e <region-name> <file>
disarm -e 0x<start>-0x<end> <file>
ARCH=<slice> disarm -e arch <fat-binary>
```

`-e` creates an output file, commonly under `/tmp` or the current directory depending on operation/build. Read the `Extracted to ...` diagnostic and report the path. Do not assume fixups were applied; current builds may explicitly say they were not.

## Searching, references, and gadgets

### Find strings or bytes

```bash
disarm -f 'needle' <file>
disarm -f 'prefix\x00suffix' <file>
disarm -f 0x<hex-value> <file>
```

`-f` reports matches with their offset/address, containing region, and nearby data. Use single quotes so the shell preserves `\xNN`. A `\x00` participates in the match rather than terminating the pattern.

### Find references

```bash
disarm --refs <symbol> <file>
disarm --refs 0x<address> <file>
disarm -v --refs 0x<address> <file>
```

Data references are found as stored values. Code references use disassembly and register following, so normal mode is materially more useful than `-q`. Add `-v` for the surrounding code snippet.

### Find gadgets

```bash
disarm -g 'ADRP,ADD,RET' <file>
```

Supply a comma-delimited mnemonic sequence with no operands. Use opcode names as `disarm` prints them. A one-opcode request may be rejected by some builds; provide the meaningful sequence.

## Disassembly

### Whole file or selected range

```bash
disarm <file>
disarm -a 0x<start>-0x<end> <file>
disarm -o 0x<start>-0x<end> <file>
disarm -r <text-region> <file>
```

Normal mode follows register values, resolves pointers/strings/bindings, and emits synthesized call lines with inferred arguments. Those call lines begin with whitespace, making them easy to filter:

```bash
disarm -a 0x<start>-0x<end> <file> | grep '^[[:space:]]'
```

Treat this as cursory decompilation. It is a linear dry run and cannot establish all pass-through values or path-sensitive state.

### Quick mode

```bash
disarm -q <file>
```

Use `-q` for fast bulk disassembly when resolved registers and call arguments are unnecessary. It can reduce large-kernel disassembly from minutes to seconds.

### Suppression and verbosity

```bash
disarm -v <file>
disarm -n <file>
disarm -nn <file>
disarm -opcodes <file>
disarm -c <file>
```

- `-v`: add detail; some operations accept `-vv`.
- `-n`: suppress NOP instructions.
- `-nn`: also suppress `DCD 0x0`.
- `-opcodes`: explicitly include encoded opcodes with disassembly.
- `-c`: emit ANSI color; use only for interactive viewing.

## Symbols and signatures

```bash
disarm -S <file>
disarm --signature <macho>
```

`-S` is the normalized symbol view, similar to `nm`, for Mach-O/ELF inputs. `--signature` parses a Mach-O embedded code signature, including CodeDirectory metadata, identifiers, hashes, entitlements/constraints when present, and signing flags.

## Output controls

Prefer one-shot environment assignments so results remain reproducible:

| Variable | Effect |
|---|---|
| `ARCH=<slice>` | Select a universal-binary architecture |
| `BASE=0x<va>` | Set the image base, equivalent to `-b` |
| `JCOLOR=1` | Enable ANSI color |
| `NOPSUP=1` / `2` | Suppress NOPs / NOPs plus zero words |
| `JFIXUP=1` / `2` | Show Mach-O chained fixups / verbose fixups |
| `NOOP=1` | Omit encoded opcode words from disassembly lines |
| `NOPC=1` | Omit address/PC values from disassembly lines |
| `OBJDUMP=1` | Render instruction bytes in objdump-compatible byte order |
| `JDEBUG=1` | Emit internal diagnostics; use only for troubleshooting |

For stable bindiff text, combine `NOOP=1` and/or `NOPC=1`. Do not combine `JCOLOR` with machine parsing unless ANSI escapes are stripped.

## Patching

```bash
test ! -e /tmp/out
disarm '-P@0x<file-offset>=\xNN\xNN...' <file>
```

In the February 2026 build, `-P` leaves the input unchanged and writes the reconstructed file to the fixed path `/tmp/out`. It opens that path with truncation. If `/tmp/out` exists, stop and ask the user how to preserve it; do not invoke `-P` first.

Use a file offset, not a virtual address; resolve it with `-A` first. Encode binary bytes as shell-preserved `\xNN` escapes. Unescaped `41424344` means the eight ASCII characters, not four hexadecimal bytes.

After patching, compare the source and `/tmp/out`, verify the exact changed range, and run targeted disassembly on `/tmp/out`. Move it to a user-selected path only after verification. Patching signed Mach-O content invalidates the original signature relationship even though the signature blob remains present.

## Practical workflows

### Triage an unknown binary

```bash
disarm -i <file>
disarm -l <file>
disarm -I <file>
disarm -S <file>
```

Then smart-dump only the interesting regions and disassemble the entry point or referenced functions.

### Go from a string to code

```bash
disarm -f 'interesting message' <file>
disarm --refs 0x<string-address> <file>
disarm -a 0x<caller-start>-0x<caller-end> <file>
```

Label whether `-f` reported an offset or a virtual address, convert with `-A`/`-O` as needed, and use `-v --refs` when the caller boundary is unclear.

### Produce parseable or diffable assembly

```bash
NOOP=1 NOPC=1 disarm -q <file>
OBJDUMP=1 disarm -q <file>
```

Use the same architecture, base, companion, and matcher inputs for both binaries before comparing output.
