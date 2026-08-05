# The `.matchers` file format

Distilled from the header comment of `xnu.matchers` plus behaviour observed
running `disarm` (build of Oct 11 2025) against Darwin 24 and Darwin 25
kernelcaches.

## Argument rules

```
arg#|pattern|function_this_is_called_in|calling_function|anything here is ignored
```

- `arg#` — `0`, `1`, `2`, or `3` only.
- `pattern` — partial but exact match **from the beginning**. Cannot contain `|`.
- `function_this_is_called_in` — the containing function, i.e. the one being
  named. This is the output of the rule.
- `calling_function` — optional. Omit it when the string is distinctive enough
  on its own; supply it when the callee disambiguates.
- Anything after the fourth field is a comment. The convention in the shipped
  file is the source path, sometimes with a note such as
  `inlines machine_thread_init and init_thread_ledgers` or `PACIBSP`.

`#` starts a comment line. The shipped file keeps disabled rules around
commented out rather than deleting them.

Rules are grouped into `## Matches for argument N:` sections, but the parser
does not care — `arg#` is per-line.

**Order matters.** The same pattern may appear more than once; the first match
applies and that rule is then disabled, so the second can match the next
occurrence.

## Region rules

Below `## Another rule type` the format changes to data matching:

```
_SEGMENT.__section|"string"|symbol|type|+/-offset
_SEGMENT.__section|val=0x...|symbol|symbol|+/-offset
```

Examples:

```
__DATA_CONST|val=0x0004000100000000|_sysent|_sysent|-40
__DATA_CONST|val=0x0000000000000504|_mach_trap_table|_mach_trap_table|-240
__DATA_CONST|"nbuf"|_sysctl.kern.nbuf|sysctl:I,nbuf_headers|-40
__DATA_CONST|"kern"|_sysctl.kern|sysctl:N|-48
```

The offset is applied to the address where the string or value was found, to
land on the start of the structure. `sysctl:I,<name>` and `sysctl:N` are
type hints for sysctl leaf and node entries.

These fire reliably — they were the only rules observed firing in testing.

## Running it

```bash
JMATCHERS=/path/to/xnu.matchers disarm --analyze <kernelcache>
```

Results land in an auto-generated companion file next to the binary, named
`<file>.ARM64.<UUID>`. It is plain text, one `0xADDRESS|symbol` per line, and is
read back automatically on later runs to skip re-analysis.

- `--analyze` **refuses to run if a companion file already exists**, to avoid
  discarding hand edits. Move it aside first.
- `JMD=1` prints per-rule usage and an unused-rule list at the end.
- `JA=1` is no longer supported; the binary errors out and tells you to use
  `--analyze`.
- `disarm -f "<string>" <binary>` locates a string and reports its file offset,
  virtual address, and section. It unwraps IM4P/BVX2 payloads itself, which
  makes it the easy way to check a pattern against a compressed kernelcache.
- `disarm --refs 0x<addr> <binary>` is documented to list references, but
  returned nothing for `__TEXT.__cstring` addresses in testing.

## Binary structures the checks rely on

Verified against `kernel.rebuilt` (xnu-12377.2.8, arm64e):

| Structure | Why it matters |
|---|---|
| `LC_SYMTAB` with `nsyms 0` | the kernel is fully stripped — no tool recovers names, only structure |
| `LC_FUNCTION_STARTS` (34000 bytes → 20505 functions) | exact function boundaries, ULEB128 deltas from the `__TEXT` vmaddr |
| `__TEXT,__cstring` (0x7b948) | the bulk of string literals |
| `__TEXT,__os_log` (0x3c2f3) | **every `os_log` format string** — miss this section and all arg-3 `_os_log_internal` candidates come back unresolvable |
| `__TEXT,__const` | some literals, including the version banner |
| `__KLDDATA,__cstring` | small, KLD-only |
| `__TEXT_EXEC,__text` (0x89c614) plus `__hib_text`, `__bootcode`, `__KLD,__text` | the executable ranges to scan for xrefs |

Two traps found while implementing this:

- **A rebuilt kernel has several `__cstring` sections.** Keeping only the last
  one yields 56 strings instead of 35191.
- **The `LC_FUNCTION_STARTS` tail is not a clean terminator.** Decoding to the
  end of `datasize` runs past the address space (a 65-bit value on this kernel).
  Filter starts to those landing inside an executable section.

The kernel version is in the binary itself:

```bash
strings -a <kernel> | grep -o 'xnu-[0-9.]*' | sort -u
```

## Caveat on `JMD=1`

The unused-rule report is not a usable staleness signal. Against both
`kernelcache.18.0.iPhone14,6` (Darwin 24.0.0) and `kernelcache.release.d23`
(Darwin 25.0.0), `JMD=1` reported 455–456 of 459 argument rules unused, and no
string-derived symbol reached the companion file — while region and immediate
rules (`0x55aa0101`, `0x7020010`, `0x77d3`, `_sysent`, `_mach_trap_table`,
`_lowGlo`) fired normally on the same runs.

So a rule appearing in the unused list means the check produced no information,
not that the rule is wrong. Never remove a rule on that basis. Use
`scripts/xnu_verify.py` — a direct string-presence test against the kernel — as
the gate instead.
