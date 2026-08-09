# disarm analysis, companions, and matchers

Read this reference before running persistent analysis or changing symbolication rules.

## Contents

- [Analysis mode](#analysis-mode)
- [Companion files](#companion-files)
- [Matcher discovery and lifecycle](#matcher-discovery-and-lifecycle)
- [Argument matchers](#argument-matchers)
- [Region matchers](#region-matchers)
- [Fixed-address matchers](#fixed-address-matchers)
- [Opcode matchers](#opcode-matchers)
- [Verification and troubleshooting](#verification-and-troubleshooting)

## Analysis mode

Run static and optional user-supplied rules and save discovered symbols:

```bash
disarm --analyze <binary>
disarm -v --analyze <binary>
```

Keep `--analyze` as the only functional option; only verbosity may accompany it. Analysis can detect function starts and apply format/domain logic such as Objective-C metadata or XNU/Linux-kernel structures. If no matcher file is found, analysis continues with static rules and says that results are limited.

Analysis creates a companion file. Before running it:

1. Record `disarm -i <binary>`, especially architecture and UUID/build ID.
2. Choose and inspect the working directory.
3. Check both the binary directory and current directory for an existing companion.
4. Supply a matcher file explicitly with `JMATCHERS=<path>` when reproducibility matters.

On large kernelcaches, analysis can take tens of seconds and generate a companion with well over 100,000 mappings. Keep it in a deliberate scratch/output directory and report its size.

`disarm` intentionally refuses to overwrite an existing companion. Do not remove one merely to force reanalysis: preserve it or get the user's approval to replace it.

Create an empty companion without analysis when symbols will be added manually:

```bash
disarm --companion <binary>
```

## Companion files

### Naming

Companions are named:

```text
<binary-name>.ARM64[.<UUID-or-build-id>]
```

The identity suffix prevents symbols from one build silently loading into another. Never rename a companion to bypass an identity mismatch without proving the layouts match.

### Format

The February 2026 build generates:

```text
# comment
0x100006578|[KBXPCListener listener:shouldAcceptNewConnection:]
0x100006704|[KBXPCService remoteProcessHasBooleanEntitlement:]
```

Use exactly one mapping or comment per line. Do not add blank lines. Preserve hexadecimal virtual addresses and the `|` delimiter.

Important: the prose appendix says `Address:Symbol`, but its own generated examples and the current executable use `0xaddress|symbol`. Trust a newly generated companion from the installed build when behavior differs from prose documentation.

Add names only at proven addresses. After editing, invoke a targeted `disarm -a ...` and verify that the name appears at the intended function/global.

## Matcher discovery and lifecycle

By default, analysis looks for `<binary-name>.matchers`. Override that with:

```bash
JMATCHERS=/absolute/path/rules.matchers disarm --analyze <binary>
```

Setting `JMATCHERS` on a normal invocation also triggers one-time analysis when no companion exists, then creates the companion and exits:

```bash
JMATCHERS=/absolute/path/rules.matchers disarm <binary>
```

Prefer explicit `--analyze` in automated workflows because it states the side effect. Support the normal form for older documentation and established shell workflows.

Current builds create a companion and exit. Subsequent invocations prefer that companion and do not re-run matchers. To reanalyze, preserve or relocate the existing companion first; never clobber user annotations casually.

Matcher files are pipe-delimited text. Keep their license/header comments. Avoid `|` or literal newlines inside fields. Matcher ordering can matter when patterns overlap, so prefer unique patterns and append deliberately.

The analyzer refuses a matcher file without its required license marker. Preserve the complete header from a matcher shipped with the same `disarm` release. This is a compatibility requirement as well as attribution: a February 2026 binary rejects the older October 2025 sample header before loading rules, while the October binary accepts it. Do not silently rewrite a user's license block merely to bypass this check.

If creating a new matcher file specifically for the February 2026 build, copy its full distributed header. A minimal smoke-test file was accepted when it contained these required marker lines before any rules:

```text
# FREE TO USE (AISE
# **BUT** PLEASE GIVE CREDIT
# consider sharing your matcher
# and spread the word of disarm, the newosxbook.com books
# leaving this LICENSE comment intact
```

Analysis proceeds conceptually from static discovery through argument/region rules to opcode rules. Opcode rules run last because they can depend on symbols created by earlier stages.

## Argument matchers

Use a tracked function argument to name the containing function:

```text
<arg-index>|<pattern>|<containing-function>|<called-function>|<comment>
```

Examples:

```text
0|zone_require failed: address in unexpe|_zone_require_panic|_panic|osfmk/kern/zalloc.c
0|0x55aa0101|_write_legacy_header|_copy_cpu_map|integer magic
1|idle_thread_create|_kernel_bootstrap_thread|_strncpy|osfmk/kern/startup.c
```

Rules:

- Use argument indexes supported by the matcher engine, normally `0` through `3`.
- Write string patterns without quotes. Matching is exact from the beginning of the runtime string; truncating the end is allowed. Choose enough leading text to be unique, and do not start a string rule with `0x`.
- Write integer patterns as hexadecimal beginning with `0x`.
- Name the function that contains the call in field 3 and the called function in field 4.
- Use the argument position emitted under the ARM64 PCS, not necessarily the source-level position. Macros and inlined wrappers can shift it.
- Treat a matcher that never fires as unproven, not harmlessly correct.

For systematic XNU argument-matcher generation and binary gates, invoke the `improve-xnu-matchers` skill.

## Region matchers

Use a string or aligned 64-bit value in a data region to name a containing structure/global:

```text
<region>|"<string>"|<symbol>|<type>|<signed-offset>
<region>|val=0x<16-hex-digits>|<symbol>|<type>|<signed-offset>
```

Examples:

```text
__DATA_CONST|"slide"|_sysctl_kern_slide|sysctl|-40
__TEXT.__const|val=0xbb4b2aab1061437c|__ZL15gAppleNVRAMGuid||0
__DATA_CONST|val=0x0004000100000000|_sysent|_sysent|-40
__DATA_CONST|val=0x0000000000000504|_mach_trap_table|_mach_trap_table|-240
```

The signed offset is applied from the matched value/reference to the symbol base. Prove it from the structure layout; a wrong offset can create a plausible symbol at the wrong field.

Newer builds can attach typed region information, for example `sysctl:I,name` or `sysctl:A,name`, so smart dumping can render identified structures. Reuse a type spelling already accepted by the installed matcher set rather than inventing one.

For `val=`, use an aligned 64-bit little-endian value and verify uniqueness in the selected region/build.

## Fixed-address matchers

Recent builds accept direct address-to-symbol rules in matcher files, using the same mapping shape as a companion:

```text
0x<virtual-address>|<symbol>
```

Use these only when the rule file is tied to the exact UUID/build ID or the address is otherwise stable. A fixed virtual address from another build is more dangerous than an unused pattern rule because it can silently label the wrong function.

## Opcode matchers

Use a known function scope and instruction sequence to name a resolved register value:

```text
<scope-symbol>|opcodes:<mnemonic>,<mnemonic>|<register-selector>=<symbol>|<comment>
```

Example:

```text
_zone_require_panic|opcodes:ADRP,ADD|Xt=zone_array|zone_info.zi_map_range
```

Rules:

- Scope the matcher to an exported or previously discovered symbol; unscoped opcode scanning is intentionally avoided for cost and ambiguity.
- Specify mnemonics only, without operands, using disarm's spelling.
- Use the instruction register role required by the installed build, such as `Xt`, or a concrete `X<number>` if its diagnostics require that form.
- Confirm the final emulated value with a targeted normal-mode disassembly before accepting the generated symbol.

## Verification and troubleshooting

After analysis:

1. Read the generated companion as text and count/review the relevant entries.
2. Disassemble several discovered functions with `disarm -a <start>-<end> <binary>`.
3. Use `--refs <symbol-or-address>` and region dumps to corroborate important globals.
4. Confirm the architecture and UUID/build ID still match.
5. Keep the matcher file and companion distinct in the report: matcher rules are reusable inference; companion entries are build-specific results.

Common failures:

| Symptom | Likely cause | Response |
|---|---|---|
| `Not loading matchers (... not found)` | Default filename absent | Set `JMATCHERS` to the intended absolute path |
| Companion already exists | Previous analysis/manual work is present | Preserve it; inspect and ask before replacement |
| Matcher never creates a symbol | Pattern absent, wrong argument index/callee, inlining, overlap, or unsupported syntax | Verify string/value presence, disassemble the call, and reduce to one rule |
| Opcode matcher scope not found | Its prerequisite symbol was not loaded/discovered | Fix companion/earlier rule first |
| Symbols look shifted or absurd | Wrong slice, base, UUID/build, or region offset | Stop and re-establish identity/layout before editing |
| Analysis is unexpectedly slow | Register following on a very large image | Use `-q` only for exploratory disassembly; analysis itself needs its semantic passes |

Do not treat an unused-rule diagnostic by itself as proof that a rule is stale. Validate against the target binary and source/build pairing before changing or deleting matcher rules.
