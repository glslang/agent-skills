#!/usr/bin/env python3
"""
Scan an XNU source tree for string literals that can become disarm matcher rules.

A matcher line is:

    arg#|pattern|containing_function|calling_function|comment

where arg# is the position the string occupies in the call *as emitted*, not as
written in C. This script finds each string literal, works out the call it is an
argument of and the function it lives in, applies the known wrapper/macro
rewrites (see CALLSITES), and prints candidate lines.

It is deliberately conservative: everything it prints is a *candidate* that still
needs the judgement described in SKILL.md (inlining, config guards, uniqueness).

Usage:
    xnu_scan.py --source <xnu-tree> [--matchers <existing.matchers>] [options]
"""

import argparse
import os
import re
import sys
from collections import defaultdict

# ---------------------------------------------------------------------------
# Call-site table.
#
# Maps a source-level callee to (emitted_symbol, arg_index_of_string).
# `src_idx` is the index the string has in the C source call; `bin_idx` is the
# index it has in the call the compiler actually emits. They differ whenever a
# macro adds leading arguments or a thin wrapper gets inlined away.
#
# Verified against xnu-11417.140.69 headers and against the existing
# xnu.matchers file. See reference/callsites.md for how to extend this.
# ---------------------------------------------------------------------------
CALLSITES = {
    # name:            (emitted symbol,                 src_idx, bin_idx)
    "panic":           ("_panic",                            0, 0),
    "panic_plain":     ("_panic",                            0, 0),
    "panic_with_options": ("_panic_with_options",            3, 3),
    "panic_with_thread_kernel_state": ("_panic_with_thread_kernel_state", 0, 0),
    "paniclog_append_noflush": ("_paniclog_append_noflush",  0, 0),
    "printf":          ("_printf",                           0, 0),
    "kprintf":         ("_kprintf",                          0, 0),
    "IOLog":           ("_IOLog",                            0, 0),
    "IOPanic":         ("_IOPanic",                          0, 0),
    "log":             ("_log",                              1, 1),
    "snprintf":        ("_snprintf",                         2, 2),
    "scnprintf":       ("_scnprintf",                        2, 2),
    "tsnprintf":       ("_snprintf",                         2, 2),
    "sprintf":         ("_sprintf",                          1, 1),
    "strlcpy":         ("_strlcpy",                          1, 1),
    "strlcat":         ("_strlcat",                          1, 1),
    "strncpy":         ("_strncpy",                          1, 1),
    # Comparisons take the literal on either side -- strcmp(name, "com.apple.x")
    # is as common as strcmp("com.apple.x", name). src_idx None means "any
    # position, emitted where it was written".
    "strcmp":          ("_strcmp",                        None, None),
    "strncmp":         ("_strncmp",                       None, None),
    "strcasecmp":      ("_strcasecmp",                    None, None),
    "strlen":          ("_strlen",                           0, 0),
    # os_log(log, fmt, ...) expands to
    # _os_log_internal(&__dso_handle, log, type, fmt, ...) -> fmt lands at 3.
    "os_log":          ("_os_log_internal",                  1, 3),
    "os_log_info":     ("_os_log_internal",                  1, 3),
    "os_log_debug":    ("_os_log_internal",                  1, 3),
    "os_log_error":    ("_os_log_internal",                  1, 3),
    "os_log_fault":    ("_os_log_internal",                  1, 3),
    "os_log_with_type": ("_os_log_internal",                 2, 3),
    # OSKextLog(kext, spec, fmt, ...)
    "OSKextLog":       ("_OSKextLog",                        2, 2),
    "OSKextVLog":      ("_OSKextVLog",                       2, 2),
    # zone_create(name, size, flags) -> zone_create_ext(name, size, flags, zid, setup)
    "zone_create":     ("_zone_create_ext",                  0, 0),
    "zone_create_ext": ("_zone_create_ext",                  0, 0),
    "zinit":           ("_zinit",                            3, 3),
    # PE_parse_boot_argn(s, p, max) is a wrapper that inlines to
    # PE_parse_boot_argn_internal(PE_boot_args(), s, p, max, FALSE) -> s at 1.
    "PE_parse_boot_argn": ("_PE_parse_boot_argn",            0, 1),
    "PE_parse_boot_arg_str": ("_PE_parse_boot_argn",         0, 1),
    "PE_boot_arg_uint64_eq": ("_PE_parse_boot_argn",         0, 1),
    "PE_get_default":  ("_PE_get_default",                   0, 0),
    # thread_set_thread_name(th, name) inlines to
    # bsd_setthreadname(info, tid, name) -> name at 2.
    "thread_set_thread_name": ("_thread_set_thread_name",    1, 2),
    "kern_coredump_log": ("_kern_coredump_log",              1, 1),
    "tsleep":          ("_tsleep",                           2, 2),
    "tsleep0":         ("_tsleep0",                          2, 2),
    "tsleep1":         ("_tsleep1",                          2, 2),
    "tsleep2":         ("_tsleep2",                          2, 2),
    "msleep":          ("_msleep",                           3, 3),
    "msleep0":         ("_msleep0",                          3, 3),
    "msleep1":         ("_msleep1",                          3, 3),
    "lck_grp_init":    ("_lck_grp_init",                     1, 1),
    "lck_grp_alloc_init": ("_lck_grp_alloc_init",            0, 0),
    "SecureDTGetProperty": ("_SecureDTGetProperty",          1, 1),
    "SecureDTFindEntry": ("_SecureDTFindEntry",              0, 0),
    "IOTaskHasEntitlement": ("_IOTaskHasEntitlement",        1, 1),
    # Both IOCurrentTask* wrappers are OS_ALWAYS_INLINE and forward to the
    # task-taking form with a NULL task, so the string always lands at 1.
    "IOCurrentTaskHasEntitlement": ("_IOTaskHasEntitlement",  0, 1),
    "IOCurrentTaskGetEntitlement": ("_IOTaskGetEntitlement",  0, 1),
    "mac_system_check_info": ("_mac_system_check_info",      1, 1),
    "getsectbynamefromheader": ("_getsectbynamefromheader",  1, 1),
    "vnode_open":      ("_vnode_open",                       0, 0),
    "kernel_debug_early": ("_kernel_debug_early",            0, 0),
}

# Callees whose string argument is a name/identifier rather than a format
# string. These make excellent matchers because the string is usually unique.
HIGH_VALUE = {
    "_zone_create_ext", "_zinit", "_lck_grp_init", "_thread_set_thread_name",
    "_PE_parse_boot_argn", "_SecureDTGetProperty", "_IOTaskHasEntitlement",
    "_IOCurrentTaskHasEntitlement", "_IOCurrentTaskGetEntitlement",
}

SKIP_DIRS = {"tests", "tools", "libkdd", "SETUP", "doc", "san", ".git"}

# Paths that never end up in a kernelcache of the given arch. Without this the
# scanner happily proposes matchers for _i386_init.
ARCH_SKIP = {
    "arm64": re.compile(r"(^|/)(i386|x86_64|x86)(/|$)"),
    "x86_64": re.compile(r"(^|/)(arm|arm64)(/|$)"),
    "any": re.compile(r"(?!)"),
}

INLINE_RE = re.compile(r"\b(?:__inline|inline|always_inline)\b")
IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:::[~A-Za-z_][A-Za-z0-9_]*)*$")
CONFIG_RE = re.compile(r"\b(DEVELOPMENT|DEBUG|MACH_ASSERT|CONFIG_[A-Z0-9_]+|XNU_[A-Z0-9_]+|__x86_64__|__i386__)\b")

ESCAPES = {
    "n": "\n", "t": "\t", "r": "\r", "0": "\0", "\\": "\\",
    '"': '"', "'": "'", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
}


def blank(src):
    """Return (skeleton, spans).

    skeleton is src with every comment and string/char literal replaced by
    spaces of the same length, so offsets stay valid. spans is the list of
    (start, end, decoded_text) for each string literal.
    """
    out = list(src)
    spans = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            while i < n and src[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and src[i + 1] == "*":
            while i < n and not (src[i] == "*" and i + 1 < n and src[i + 1] == "/"):
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            for j in range(i, min(i + 2, n)):
                out[j] = " "
            i += 2
        elif c == '"':
            start = i
            i += 1
            buf = []
            while i < n and src[i] != '"':
                if src[i] == "\\" and i + 1 < n:
                    buf.append(ESCAPES.get(src[i + 1], "\x00"))
                    out[i] = out[i + 1] = " "
                    i += 2
                    continue
                buf.append(src[i])
                if src[i] != "\n":
                    out[i] = " "
                i += 1
            out[start] = " "
            if i < n:
                out[i] = " "
            i += 1
            spans.append((start, i, "".join(buf)))
        elif c == "'":
            out[i] = " "
            i += 1
            while i < n and src[i] != "'":
                if src[i] == "\\":
                    out[i] = " "
                    i += 1
                if i < n and src[i] != "\n":
                    out[i] = " "
                i += 1
            if i < n:
                out[i] = " "
            i += 1
        else:
            i += 1
    return "".join(out), spans


def find_functions(skeleton, src):
    """Find function bodies using XNU's column-0 brace style.

    A function body is a '{' in column 0 whose previous non-space character is
    ')', running to the next '}' in column 0. Returns a list of
    (body_start, body_end, name, header).
    """
    funcs = []
    for m in re.finditer(r"^\{", skeleton, re.M):
        bstart = m.start()
        j = bstart - 1
        while j >= 0 and skeleton[j] in " \t\r\n":
            j -= 1
        if j < 0 or skeleton[j] != ")":
            continue
        # walk back to the matching '('
        depth, k = 0, j
        while k >= 0:
            if skeleton[k] == ")":
                depth += 1
            elif skeleton[k] == "(":
                depth -= 1
                if depth == 0:
                    break
            k -= 1
        if k < 0:
            continue
        name_m = IDENT_RE.search(skeleton[max(0, k - 300):k].rstrip())
        if not name_m:
            continue
        name = name_m.group(0)
        end_m = re.compile(r"^\}", re.M).search(skeleton, bstart + 1)
        bend = end_m.start() if end_m else len(skeleton)
        hstart = max(0, k - 300)
        header = src[hstart:bstart]
        if "\n\n" in header:
            header = header.rsplit("\n\n", 1)[1]
        funcs.append((bstart, bend, name, header))
    return funcs


def cpp_stack(src):
    """Map line number -> list of active #if conditions."""
    stack, per_line = [], {}
    for lineno, line in enumerate(src.split("\n"), 1):
        s = line.lstrip()
        per_line[lineno] = list(stack)
        if s.startswith("#if"):
            cond = s[3:].lstrip()
            if cond.startswith("def "):
                cond = cond[4:]
            elif cond.startswith("ndef "):
                cond = "!" + cond[5:]
            stack.append(cond.strip())
            per_line[lineno] = list(stack)
        elif s.startswith("#elif") or s.startswith("#else"):
            if stack:
                stack[-1] = s
        elif s.startswith("#endif"):
            if stack:
                stack.pop()
    return per_line


def enclosing_call(skeleton, pos):
    """Return (callee_name, arg_index) for the call whose argument list
    directly contains the string at `pos`, or (None, None)."""
    depth, commas, i = 0, 0, pos - 1
    while i >= 0:
        c = skeleton[i]
        if c == ")":
            depth += 1
        elif c == "(":
            if depth == 0:
                break
            depth -= 1
        elif c == "," and depth == 0:
            commas += 1
        elif c in ";{}" and depth == 0:
            return None, None
        i -= 1
    if i < 0:
        return None, None
    name_m = IDENT_RE.search(skeleton[max(0, i - 200):i].rstrip())
    if not name_m:
        return None, None
    return name_m.group(0).split("::")[-1] if "::" not in name_m.group(0) else name_m.group(0), commas


def merge_adjacent(spans, skeleton):
    """Merge C adjacent-string-literal concatenation into single logical spans."""
    merged, i = [], 0
    while i < len(spans):
        start, end, text = spans[i]
        j = i + 1
        while j < len(spans):
            gap = skeleton[end:spans[j][0]]
            if gap.strip() != "":
                break
            text += spans[j][2]
            end = spans[j][1]
            j += 1
        merged.append((start, end, text))
        i = j
    return merged


def make_pattern(text, maxlen):
    """Turn a decoded C string into a matcher pattern.

    The pattern is a prefix match, so truncating is always safe. Cut at the
    first control character (a matcher line cannot contain a newline) and at
    '|' (the field separator), then trim a dangling format specifier.
    """
    out = []
    for ch in text:
        if ch == "|" or ord(ch) < 0x20 or ord(ch) > 0x7E:
            break
        out.append(ch)
    p = "".join(out)[:maxlen]
    p = re.sub(r"%[-+ #0-9.lhqzjt]*$", "", p)
    return p.rstrip() if len(p) > 12 else p


def load_matchers(path):
    """Return (patterns, functions) already present in a matchers file."""
    pats, funcs = [], set()
    if not path or not os.path.exists(path):
        return pats, funcs
    with open(path, errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            f = line.split("|")
            if len(f) < 3 or f[0].strip() not in {"0", "1", "2", "3"}:
                continue
            pats.append(f[1])
            funcs.add(f[2].lstrip("_"))
    return pats, funcs


def covered(pattern, existing):
    """True if `pattern` overlaps an existing rule by prefix in either direction."""
    for e in existing:
        if not e:
            continue
        if pattern.startswith(e) or e.startswith(pattern):
            return True
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, help="XNU source tree root")
    ap.add_argument("--matchers", help="existing matchers file, for dedup")
    ap.add_argument("--callee", help="comma-separated source callee filter (e.g. panic,zone_create)")
    ap.add_argument("--subsystem", help="restrict to a path prefix, e.g. osfmk/kern")
    ap.add_argument("--arch", choices=["arm64", "x86_64", "any"], default="arm64",
                    help="drop sources belonging to another architecture (default arm64)")
    ap.add_argument("--max-pattern", type=int, default=55)
    ap.add_argument("--min-pattern", type=int, default=8)
    ap.add_argument("--include-guarded", action="store_true",
                    help="include strings under DEVELOPMENT/DEBUG/CONFIG_ guards")
    ap.add_argument("--include-known", action="store_true",
                    help="include functions already named in the matchers file")
    ap.add_argument("--all-callees", action="store_true",
                    help="also emit calls to functions not in the CALLSITES table")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--format", choices=["matchers", "tsv"], default="matchers")
    args = ap.parse_args()

    want = set(args.callee.split(",")) if args.callee else None
    known_pats, known_funcs = load_matchers(args.matchers)

    # Pass 1: collect every candidate, and count global string occurrences so we
    # can tell unique strings from ones the linker will coalesce.
    cands = []
    occurrences = defaultdict(int)

    for root, dirs, files in os.walk(args.source):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if not fn.endswith((".c", ".cpp")):
                continue
            path = os.path.join(root, fn)
            rel = os.path.relpath(path, args.source)
            if args.subsystem and not rel.startswith(args.subsystem):
                continue
            if ARCH_SKIP[args.arch].search(os.path.dirname(rel)):
                continue
            try:
                with open(path, errors="replace") as fh:
                    src = fh.read()
            except OSError:
                continue

            skeleton, spans = blank(src)
            if not spans:
                continue
            spans = merge_adjacent(spans, skeleton)
            funcs = find_functions(skeleton, src)
            guards = cpp_stack(src)
            line_of = [0] * (len(src) + 1)
            ln = 1
            for idx, ch in enumerate(src):
                line_of[idx] = ln
                if ch == "\n":
                    ln += 1
            line_of[len(src)] = ln

            for start, end, text in spans:
                pattern = make_pattern(text, args.max_pattern)
                if len(pattern) < args.min_pattern:
                    continue
                occurrences[pattern] += 1

                callee, argidx = enclosing_call(skeleton, start)
                if not callee:
                    continue
                entry = CALLSITES.get(callee)
                if entry is None and not args.all_callees:
                    continue
                if entry:
                    sym, src_idx, bin_idx = entry
                    if src_idx is None:
                        emit_idx = argidx
                    elif argidx != src_idx:
                        continue
                    else:
                        emit_idx = bin_idx
                else:
                    sym, emit_idx = "_" + callee, argidx
                if emit_idx > 3:
                    continue
                if want and callee not in want:
                    continue

                fname, header = None, ""
                for bstart, bend, nm, hdr in funcs:
                    if bstart < start < bend:
                        fname, header = nm, hdr
                if not fname:
                    continue

                lineno = line_of[start]
                cands.append({
                    "arg": emit_idx,
                    "pattern": pattern,
                    "func": fname,
                    "sym": sym,
                    "rel": rel,
                    "line": lineno,
                    "guards": [g for g in guards.get(lineno, []) if CONFIG_RE.search(g)],
                    "inline": bool(INLINE_RE.search(header)),
                    "static": header.strip().startswith("static"),
                    "cpp": fn.endswith(".cpp"),
                })

    # Pass 2: filter and rank.
    rows = []
    for c in cands:
        if covered(c["pattern"], known_pats):
            continue
        if not args.include_known and c["func"].lstrip("_") in known_funcs:
            continue
        if c["inline"]:
            continue
        if c["guards"] and not args.include_guarded:
            continue
        c["dupes"] = occurrences[c["pattern"]]
        if c["dupes"] > 1:
            continue
        score = 0
        score += 40 if c["sym"] in HIGH_VALUE else 0
        score += min(len(c["pattern"]), 40)
        score -= 20 if c["cpp"] else 0
        score -= 15 if c["static"] else 0
        c["score"] = score
        rows.append(c)

    rows.sort(key=lambda r: -r["score"])
    if args.limit:
        rows = rows[:args.limit]

    if args.format == "tsv":
        print("arg\tpattern\tfunc\tsym\tfile\tline\tstatic\tcpp\tscore")
        for r in rows:
            print(f"{r['arg']}\t{r['pattern']}\t{r['func']}\t{r['sym']}\t"
                  f"{r['rel']}\t{r['line']}\t{int(r['static'])}\t{int(r['cpp'])}\t{r['score']}")
    else:
        for r in rows:
            fn = r["func"] if r["cpp"] and "::" in r["func"] else "_" + r["func"]
            note = f"{r['rel']}:{r['line']}"
            if r["static"]:
                note += " [static - may be inlined]"
            if r["cpp"]:
                note += " [C++ - needs mangled symbol]"
            print(f"{r['arg']}|{r['pattern']}|{fn}|{r['sym']}|{note}")

    print(f"\n# {len(rows)} candidates from {len(cands)} call sites", file=sys.stderr)


if __name__ == "__main__":
    main()
