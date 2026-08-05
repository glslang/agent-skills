#!/usr/bin/env python3
"""
Check candidate matchers against the kernel's real function boundaries.

The failure this catches: a `static` source function that the compiler inlined
into its caller. The string then lives inside the *caller's* function body, so a
rule naming the callee can never fire -- and it fails silently, because a
matcher that never matches produces no error.

The kernel is stripped (nsyms 0), so nothing here recovers names. What it does
recover is structure, from data already in the file:

  * LC_FUNCTION_STARTS gives exact function boundaries -- the same data disarm
    uses to decide what a function is.
  * ADRP+ADD / ADR pairs in __text give the code references to each __cstring
    entry.

Put those together and each candidate resolves to a binary function. Then the
name-free inlining tell: if candidates from two *different* source functions
land in the same binary function, at least one of them was inlined and names the
wrong thing.

Usage:
    xnu_inline_check.py --kernel <macho> --matchers candidates.txt
    xnu_inline_check.py --kernel <macho> --matchers candidates.txt --only OK
"""

import argparse
import bisect
import re
import struct
import sys
from array import array
from collections import defaultdict

VERIFY_PREFIX = re.compile(r"^(?:PRESENT|ABSENT|IMM|OK|ARGBAD|ARGUNK|SHARED|MULTI|NOREF|NOSTR)\s*"
                           r"(?:@ 0x[0-9a-f]+)?\s*\d*:?\s+(?=[0-3]\|)")

MH_MAGIC_64 = 0xFEEDFACF
LC_SEGMENT_64 = 0x19
LC_FUNCTION_STARTS = 0x26
S_ATTR_PURE_INSTRUCTIONS = 0x80000000


def read_macho(path):
    """Return (data, text_vmaddr, string_sections, exec_sections, func_starts_span).

    A rebuilt kernel spreads literals across several sections: every __cstring
    (the main one plus __KLDDATA's), __TEXT,__const where things like the
    version banner land, and __TEXT,__os_log which holds every os_log format
    string. Miss __os_log and all the arg-3 _os_log_internal candidates come
    back unresolvable.
    """
    with open(path, "rb") as fh:
        data = fh.read()

    magic, = struct.unpack_from("<I", data, 0)
    if magic != MH_MAGIC_64:
        sys.exit(f"{path}: not a 64-bit little-endian Mach-O (magic {magic:#x}); "
                 "decompress/rebuild the kernelcache first")

    ncmds, = struct.unpack_from("<I", data, 16)
    off = 32
    text_vmaddr = None
    strsects = []
    execs = []
    fstarts = None

    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, off)
        if cmd == LC_SEGMENT_64:
            segname = data[off + 8:off + 24].rstrip(b"\0").decode("ascii", "replace")
            vmaddr, = struct.unpack_from("<Q", data, off + 24)
            nsects, = struct.unpack_from("<I", data, off + 64)
            if segname == "__TEXT":
                text_vmaddr = vmaddr
            soff = off + 72
            for _ in range(nsects):
                sectname = data[soff:soff + 16].rstrip(b"\0").decode("ascii", "replace")
                addr, size = struct.unpack_from("<QQ", data, soff + 32)
                foff, = struct.unpack_from("<I", data, soff + 48)
                flags, = struct.unpack_from("<I", data, soff + 64)
                if size:
                    if sectname in ("__cstring", "__os_log") or \
                            (segname == "__TEXT" and sectname == "__const"):
                        strsects.append((addr, size, foff))
                    if flags & S_ATTR_PURE_INSTRUCTIONS or sectname == "__text":
                        execs.append((addr, size, foff))
                soff += 80
        elif cmd == LC_FUNCTION_STARTS:
            dataoff, datasize = struct.unpack_from("<II", data, off + 8)
            fstarts = (dataoff, datasize)
        off += cmdsize

    if text_vmaddr is None:
        sys.exit("no __TEXT segment")
    if not strsects:
        sys.exit("no __cstring section")
    if fstarts is None or fstarts[1] == 0:
        sys.exit("no LC_FUNCTION_STARTS -- this check needs it and cannot proceed")
    if not execs:
        sys.exit("no executable sections found")
    return data, text_vmaddr, strsects, execs, fstarts


def function_starts(data, base, span, execs):
    """Decode LC_FUNCTION_STARTS (ULEB128 deltas from the __TEXT vmaddr).

    The table is zero-padded to alignment, and the padding does not always
    decode as a clean terminator -- on kernel.rebuilt the tail runs on and
    accumulates past the 64-bit address space. Keep only starts that land in an
    executable section, which is the real invariant.
    """
    off, size = span
    end = off + size
    addr = base
    out = []
    while off < end:
        delta = 0
        shift = 0
        while off < end:
            b = data[off]
            off += 1
            delta |= (b & 0x7F) << shift
            if not (b & 0x80):
                break
            shift += 7
        if delta == 0:
            break
        addr += delta
        out.append(addr)
    ranges = [(a, a + s) for a, s, _ in execs]
    return [a for a in out if in_ranges(a, ranges)]


def cstrings(data, sections):
    """Yield (address, text) for every NUL-terminated entry in the string
    sections. __TEXT,__const interleaves literals with binary constants, so
    non-text runs come out as junk entries -- harmless, they simply never
    prefix-match a pattern."""
    for addr, size, foff in sections:
        blob = data[foff:foff + size]
        pos = 0
        while pos < len(blob):
            nxt = blob.find(b"\0", pos)
            if nxt < 0:
                break
            if nxt > pos:
                yield addr + pos, blob[pos:nxt].decode("utf-8", "replace")
            pos = nxt + 1


def sign_extend(value, bits):
    if value & (1 << (bits - 1)):
        value -= 1 << bits
    return value


def in_ranges(target, ranges):
    for lo, hi in ranges:
        if lo <= target < hi:
            return True
    return False


def cstring_xrefs(data, execs, ranges, starts):
    """Map every string address inside `ranges` to the (code address, register)
    pairs that materialise it via ADRP+ADD or ADR.

    One pass over all executable sections. The ADRP page is tracked per
    destination register; the ADD that completes the pair usually follows
    within a few instructions, and a later ADRP to the same register
    supersedes the earlier one.

    The tracked state is cleared at every function boundary. Registers do not
    survive a call, so an ADRP at the tail of one function must never pair with
    an ADD at the head of the next -- that would record an xref at a PC whose
    function never materialises the string, and the containing-function and
    argument-register verdicts are both derived from that PC.
    """
    refs = defaultdict(list)
    for addr, size, foff in execs:
        words = array("I")
        words.frombytes(data[foff:foff + (size & ~3)])
        if sys.byteorder == "big":
            words.byteswap()
        pages = {}
        nxt = bisect.bisect_right(starts, addr)
        for i, insn in enumerate(words):
            pc = addr + i * 4
            if nxt < len(starts) and pc >= starts[nxt]:
                pages.clear()
                while nxt < len(starts) and pc >= starts[nxt]:
                    nxt += 1
            if (insn & 0x9F000000) == 0x90000000:          # ADRP
                immlo = (insn >> 29) & 0x3
                immhi = (insn >> 5) & 0x7FFFF
                imm = sign_extend((immhi << 2) | immlo, 21) << 12
                pages[insn & 0x1F] = (pc & ~0xFFF) + imm
            elif (insn & 0xFF800000) == 0x91000000:        # ADD (imm, 64-bit)
                rn = (insn >> 5) & 0x1F
                base = pages.get(rn)
                if base is None:
                    continue
                imm12 = (insn >> 10) & 0xFFF
                if insn & (1 << 22):
                    imm12 <<= 12
                target = base + imm12
                rd = insn & 0x1F
                if in_ranges(target, ranges):
                    refs[target].append((pc, rd))
                if rd != rn:
                    pages.pop(rd, None)
            elif (insn & 0x9F000000) == 0x10000000:        # ADR
                immlo = (insn >> 29) & 0x3
                immhi = (insn >> 5) & 0x7FFFF
                target = pc + sign_extend((immhi << 2) | immlo, 21)
                if in_ranges(target, ranges):
                    refs[target].append((pc, insn & 0x1F))
                pages.pop(insn & 0x1F, None)
    return refs


def parse_candidates(path):
    """Read matcher lines. Tolerates the `PRESENT  62: ` prefix that
    xnu_verify.py prints, so its output can be piped straight in."""
    rows = []
    with open(path, errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = VERIFY_PREFIX.sub("", raw.rstrip("\n"))
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            f = raw.split("|")
            if len(f) < 3 or f[0].strip() not in {"0", "1", "2", "3"}:
                continue
            rows.append({"lineno": lineno, "raw": raw, "arg": int(f[0].strip()),
                         "pattern": f[1], "func": f[2],
                         "note": f[4] if len(f) > 4 else ""})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True)
    ap.add_argument("--matchers", required=True)
    ap.add_argument("--only", help="comma-separated verdicts, e.g. OK or ARGBAD,ARGUNK,SHARED")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    ap.add_argument("--bare", action="store_true",
                    help="print matcher lines only, no verdict column (for appending)")
    args = ap.parse_args()

    data, text_vmaddr, strsects, execs, fstarts = read_macho(args.kernel)
    starts = function_starts(data, text_vmaddr, fstarts, execs)
    strings = list(cstrings(data, strsects))
    ranges = [(a, a + n) for a, n, _ in strsects]
    refs = cstring_xrefs(data, execs, ranges, starts)

    print(f"# {len(starts)} functions, {len(strings)} cstrings, "
          f"{len(refs)} referenced cstrings", file=sys.stderr)

    # Prefix lookup over __cstring, sorted by text.
    by_text = sorted(strings, key=lambda s: s[1])
    texts = [s[1] for s in by_text]

    rows = parse_candidates(args.matchers)

    # Resolve each candidate to the function(s) containing a reference to it.
    for r in rows:
        i = bisect.bisect_left(texts, r["pattern"])
        addrs = []
        while i < len(texts) and texts[i].startswith(r["pattern"]):
            addrs.append(by_text[i][0])
            i += 1
        if not addrs:
            r["verdict"] = "NOSTR"
            r["funcs"] = []
            continue
        sites = [pc for a in addrs for pc in refs.get(a, [])]
        if not sites:
            r["verdict"] = "NOREF"
            r["funcs"] = []
            continue
        fns = set()
        for pc, _rd in sites:
            j = bisect.bisect_right(starts, pc) - 1
            if j >= 0:
                fns.add(starts[j])
        r["funcs"] = sorted(fns)
        r["regs"] = sorted({rd for _pc, rd in sites})
        r["verdict"] = "MULTI" if len(fns) > 1 else "OK"

    # Name-free inlining tell: one binary function claimed by candidates from
    # more than one source function means at least one of them was inlined.
    owners = defaultdict(set)
    for r in rows:
        for fn in r["funcs"]:
            owners[fn].add(r["func"])
    for r in rows:
        if r["verdict"] != "OK":
            continue
        fn = r["funcs"][0]
        if len(owners[fn]) > 1:
            r["verdict"] = "SHARED"
            r["shared_with"] = sorted(owners[fn] - {r["func"]})
            continue
        # The register the string is materialised into is the argument register
        # when the compiler builds it directly in place, which is the common
        # case. Anything else -- x4+ (it goes somewhere else first), or several
        # registers across multiple sites -- means arg# is simply not proven
        # here. That must not read as OK: bare mode emits OK rows for
        # appending, so an unproven row would land in the matchers file dressed
        # as a verified one.
        regs = r.get("regs") or []
        if regs == [r["arg"]]:
            continue
        if len(regs) == 1 and regs[0] <= 3:
            r["verdict"] = "ARGBAD"
            r["saw_reg"] = regs[0]
        else:
            r["verdict"] = "ARGUNK"
            r["saw_regs"] = regs

    want = set(args.only.split(",")) if args.only else None
    if args.bare and want is None:
        # Bare output is meant to be appended to a matchers file. Emitting the
        # rejected verdicts here would append exactly what the check just
        # disqualified, so bare mode defaults to OK only.
        want = {"OK"}
    counts = defaultdict(int)
    for r in rows:
        counts[r["verdict"]] += 1
        if args.quiet or (want and r["verdict"] not in want):
            continue
        if args.bare:
            print(r["raw"])
            continue
        loc = f" @ {r['funcs'][0]:#x}" if r["funcs"] else ""
        print(f"{r['verdict']:<7}{loc:>20}  {r['raw']}")
        if r["verdict"] == "SHARED":
            print(f"{'':>27}  ^ binary function also holds strings from: "
                  f"{', '.join(r['shared_with'])}")
        elif r["verdict"] == "ARGBAD":
            print(f"{'':>27}  ^ string is materialised into x{r['saw_reg']}, "
                  f"but the rule says arg {r['arg']}")
        elif r["verdict"] == "ARGUNK":
            seen = ", ".join(f"x{x}" for x in r["saw_regs"]) or "nothing"
            print(f"{'':>27}  ^ arg {r['arg']} not proven here (materialised into "
                  f"{seen}); check by hand before appending")

    total = len(rows)
    print(f"\n# {total} candidates: " + ", ".join(
        f"{k}={counts[k]}" for k in ("OK", "ARGBAD", "ARGUNK", "SHARED", "MULTI", "NOREF", "NOSTR")
        if counts[k]), file=sys.stderr)
    print("# OK = string referenced from exactly one function, unshared -> "
          "containing-function name is safe to trust", file=sys.stderr)
    print("# ARGBAD = string lands in a different argument register than the rule claims",
          file=sys.stderr)
    print("# ARGUNK = arg# not proven (built in x4+, or several registers) -- check by hand",
          file=sys.stderr)
    print("# SHARED/MULTI = inlined or ambiguous -> re-check which function to name",
          file=sys.stderr)
    print("# NOREF = string present but no ADRP+ADD/ADR reference found "
          "(may be reached another way)", file=sys.stderr)


if __name__ == "__main__":
    main()
