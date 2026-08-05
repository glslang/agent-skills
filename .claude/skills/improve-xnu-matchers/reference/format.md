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
