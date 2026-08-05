# Deriving `arg#`

`arg#` is the register position (`x0`–`x3`) the string occupies in the call the
compiler actually emits. To derive it for a callee that is not yet in
`CALLSITES` in `scripts/xnu_scan.py`, work through these in order.

## 1. Start from the real prototype

Find the declaration, not the call. Count from zero.

```c
void OSKextLog(OSKext *aKext, OSKextLogSpec msgLogSpec, const char *format, ...);
```

`format` is index 2 → `2|...|...|_OSKextLog`. Matches the 14 `_OSKextLog` rules
in the shipped file.

## 2. Expand macros that prepend arguments

`os_log` is the one that bites. In `libkern/os/log.h`:

```c
#define os_log(log, format, ...) \
    os_log_with_type(log, OS_LOG_TYPE_DEFAULT, format, ##__VA_ARGS__)
```

which lowers to `_os_log_internal(&__dso_handle, log, type, format, ...)`. The
format string is written second but emitted fourth → **`arg# = 3`**. Every
`_os_log_internal` rule in the file is a 3.

## 3. Follow thin wrappers that get inlined away

A wrapper that is one call deep never survives as its own function; the emitted
call is the *inner* one, with the inner one's argument order.

`pexpert/gen/bootargs.c`:

```c
boolean_t
PE_parse_boot_argn(const char *arg_string, void *arg_ptr, int max_arg)
{
    return PE_parse_boot_argn_internal(PE_boot_args(), arg_string, arg_ptr, max_len, FALSE);
}
```

`arg_string` is index 0 in the source call, index **1** in the emitted one. All
the working `PE_parse_boot_argn` rules are 1. (`xnu.matchers:297` is a 0 — that
one is inert. Left alone: rules are additive-only.)

`osfmk/kern/thread.c`:

```c
void
thread_set_thread_name(thread_t th, const char* name)
{
    if (th && name) {
        bsd_setthreadname(get_bsdthread_info(th), thread_tid(th), name);
    }
}
```

`name` is index 1 in source, index **2** emitted.

## 3a. Wrapper inlining can be per-call-site

`thread_set_thread_name` is the warning: at some call sites it inlines to
`bsd_setthreadname` and the name lands at 2, at others it survives as a real
call and the name stays at 1. The shipped file has **both** forms — four rules
at 2 and two at 1 — and both are right, for different sites. Do not "fix" one to
match the other.

The table below is therefore a prior, not a guarantee. `xnu_inline_check.py`
resolves it per site: its `ARGBAD` verdict reports the register the string is
actually materialised into.

That check found a genuine error in this table. `IOCurrentTaskHasEntitlement`
was recorded as arg 0 from its own prototype, but in `IOKitBSDInit.cpp`:

```c
extern "C" OS_ALWAYS_INLINE boolean_t
IOCurrentTaskHasEntitlement(const char *entitlement)
{
	return IOTaskHasEntitlement(NULL, entitlement);
}
```

`OS_ALWAYS_INLINE`, so the emitted call is always `IOTaskHasEntitlement` and the
string is always at **1**. Same for `IOCurrentTaskGetEntitlement`. Nine
candidates were wrong before the binary check caught it.

## 4. Sanity-check against the shipped file

Before trusting a new entry, grep `xnu.matchers` for the callee. If a dozen
existing rules disagree with your derivation, they are right and you are wrong —
they were validated against real kernelcaches.

```bash
grep -E "^[0-3]\|" xnu.matchers | awk -F'|' '{print $1, $4}' | sort | uniq -c | sort -rn
```

## Verified table

As encoded in `CALLSITES`. `src` is the index in the C source, `bin` the index
emitted. Where they differ, the reason is in the last column.

| Source callee | Emitted symbol | src | bin | Why they differ |
|---|---|---|---|---|
| `panic` | `_panic` | 0 | 0 | |
| `panic_with_options` | `_panic_with_options` | 3 | 3 | |
| `panic_with_thread_kernel_state` | same | 0 | 0 | |
| `paniclog_append_noflush` | same | 0 | 0 | |
| `printf` / `kprintf` / `IOLog` | `_printf` / `_kprintf` / `_IOLog` | 0 | 0 | |
| `snprintf` / `tsnprintf` | `_snprintf` | 2 | 2 | |
| `scnprintf` | `_scnprintf` | 2 | 2 | |
| `strlcpy` / `strlcat` / `strncpy` | as named | 1 | 1 | source operand |
| `strlen` | `_strlen` | 0 | 0 | |
| `strcmp` / `strncmp` / `strcasecmp` | as named | any | same | literal sits on either side — see below |
| `os_log*` | `_os_log_internal` | 1 | **3** | macro prepends dso + type |
| `os_log_with_type` | `_os_log_internal` | 2 | **3** | macro prepends dso |
| `OSKextLog` | `_OSKextLog` | 2 | 2 | |
| `zone_create` | `_zone_create_ext` | 0 | 0 | trailing args added |
| `zinit` | `_zinit` | 3 | 3 | |
| `PE_parse_boot_argn` | `_PE_parse_boot_argn` | 0 | **1** | wrapper inlines to `_internal` |
| `thread_set_thread_name` | `_thread_set_thread_name` | 1 | **2** or 1 | inlines to `bsd_setthreadname` at some sites only — see 3a |
| `kern_coredump_log` | same | 1 | 1 | |
| `tsleep`/`tsleep1`/`tsleep2` | as named | 2 | 2 | `wmesg` |
| `msleep` family | as named | 3 | 3 | `wmesg` |
| `lck_grp_init` | same | 1 | 1 | |
| `SecureDTGetProperty` | same | 1 | 1 | property name |
| `IOTaskHasEntitlement` | same | 1 | 1 | |
| `IOCurrentTaskHasEntitlement` | `_IOTaskHasEntitlement` | 0 | **1** | OS_ALWAYS_INLINE wrapper, NULL task prepended |
| `IOCurrentTaskGetEntitlement` | `_IOTaskGetEntitlement` | 0 | **1** | same |
| `mac_system_check_info` | same | 1 | 1 | |

## Comparisons take the literal on either side

`strcmp(name, "com.apple.foo")` is as common in XNU as
`strcmp("com.apple.foo", name)`, and both are worth mining — identifier
comparisons are exactly the stable strings this skill wants. These entries carry
`src_idx = None` in `CALLSITES`, meaning "accept the literal wherever it is
written, and emit it at that same index". Pinning them to 0 silently dropped the
arg-1 form, which is the more common of the two in practice.

Do **not** do this for `strlcpy`/`strlcat`/`strncpy`: their argument 0 is the
destination buffer and can never be a literal, so a fixed `src_idx` of 1 is
correct and a `None` would only admit noise.

## Highest-yield callees

Format strings are plentiful but often shared between builds and edited between
releases. Identifier-like strings are better matchers — they are unique, stable,
and name the function almost by definition:

- `zone_create` / `zinit` — the zone name is the subsystem name
- `thread_set_thread_name` — names the thread's own entry function
- `PE_parse_boot_argn` — boot-arg names are stable across releases
- `IOTaskHasEntitlement` / `IOCurrentTaskHasEntitlement` — entitlement strings
- `lck_grp_init` — lock group names
- `SecureDTGetProperty` — device-tree property names

`xnu_scan.py` scores these above format strings for this reason.
