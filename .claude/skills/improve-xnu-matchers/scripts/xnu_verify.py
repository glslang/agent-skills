#!/usr/bin/env python3
"""
Check matcher patterns against a real kernel binary.

A matcher can only ever fire if its pattern is a prefix of a string that is
actually present in the target kernel. This catches the three ways a
source-derived candidate goes wrong:

  * the string sits behind a config guard that is off in this build
  * the string changed or was removed between the source tree and this kernel
  * the pattern was mis-transcribed (stray escape, truncated mid-word)

It does NOT verify the arg index or the containing function -- those come from
reading the source. See SKILL.md.

Usage:
    xnu_verify.py --kernel /tmp/extracted/kernel.rebuilt --matchers cand.txt
    xnu_verify.py --kernel <macho> --matchers xnu.matchers --only-absent
"""

import argparse
import bisect
import os
import re
import subprocess
import sys


IMMEDIATE = re.compile(r"^0x[0-9a-fA-F]+$")


def kernel_strings(path):
    """Every printable string in the binary, sorted for prefix search.

    -n 2 because matcher patterns get as short as two characters; the default
    minimum of 4 would drop the very strings those rules target.
    """
    try:
        out = subprocess.run(["strings", "-a", "-n", "2", path], capture_output=True,
                             text=True, errors="replace", check=True).stdout
    except (OSError, subprocess.CalledProcessError) as e:
        sys.exit(f"could not run strings on {path}: {e}")
    return sorted(set(out.split("\n")))


def has_prefix(strings, pattern):
    """True if any string in `strings` starts with `pattern`."""
    i = bisect.bisect_left(strings, pattern)
    return i < len(strings) and strings[i].startswith(pattern)


def parse(path):
    """Yield (lineno, raw, arg, pattern) for real matcher rules."""
    with open(path, errors="replace") as fh:
        for lineno, raw in enumerate(fh, 1):
            raw = raw.rstrip("\n")
            if not raw.strip() or raw.lstrip().startswith("#"):
                continue
            f = raw.split("|")
            if len(f) < 3 or f[0].strip() not in {"0", "1", "2", "3"}:
                continue
            yield lineno, raw, f[0].strip(), f[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kernel", required=True, help="decompressed/rebuilt kernel Mach-O")
    ap.add_argument("--matchers", required=True, help="matcher file or candidate list")
    ap.add_argument("--only-absent", action="store_true")
    ap.add_argument("--only-present", action="store_true")
    ap.add_argument("--quiet", action="store_true", help="summary only")
    args = ap.parse_args()

    if not os.path.exists(args.kernel):
        sys.exit(f"no such kernel: {args.kernel}")

    strings = kernel_strings(args.kernel)
    present = absent = immediate = 0

    for lineno, raw, arg, pattern in parse(args.matchers):
        # 0x... rules match an immediate operand, not a string; a string search
        # cannot say anything about them either way.
        if IMMEDIATE.match(pattern):
            immediate += 1
            if not args.quiet and not (args.only_absent or args.only_present):
                print(f"IMM     {lineno:>4}: {raw}")
            continue
        ok = has_prefix(strings, pattern)
        if ok:
            present += 1
        else:
            absent += 1
        if args.quiet:
            continue
        if ok and args.only_absent:
            continue
        if not ok and args.only_present:
            continue
        print(f"{'PRESENT' if ok else 'ABSENT '} {lineno:>4}: {raw}")

    total = present + absent
    pct = (100.0 * present / total) if total else 0.0
    print(f"\n{present}/{total} string patterns present in {os.path.basename(args.kernel)} "
          f"({pct:.1f}%); {immediate} immediate rules not checked", file=sys.stderr)


if __name__ == "__main__":
    main()
