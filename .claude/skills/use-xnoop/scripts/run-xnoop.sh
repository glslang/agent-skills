#!/bin/bash

set -euo pipefail

xnoop_binary="${XNOOP_BIN:-/Users/goncalo/OS_Security_Insecurity/xnoop/xnoop.lite}"
dump_directory="${XNOOP_DUMP_DIR:-/Users/goncalo/OS_Security_Insecurity/xnoop}"
commands=()

usage() {
  printf '%s\n' \
    'Usage: run-xnoop.sh [--binary PATH] [--dump DIR] "COMMAND" ["COMMAND" ...]' \
    '' \
    'Load an Xn00p segmented dump in offline mode, then run each quoted REPL' \
    'command in the same process. Defaults can also be overridden with XNOOP_BIN' \
    'and XNOOP_DUMP_DIR.' \
    '' \
    'Examples:' \
    '  run-xnoop.sh "search Darwin Kernel Version"' \
    '  run-xnoop.sh "dump _kernel_task uint64_t"' \
    '  run-xnoop.sh "zone 0xffffffeb9d57da40" "dump 0xffffffeb9d57da40 task"'
}

while (($#)); do
  case "$1" in
    --binary)
      (($# >= 2)) || { printf 'error: --binary needs a path\n' >&2; exit 2; }
      xnoop_binary="$2"
      shift 2
      ;;
    --dump)
      (($# >= 2)) || { printf 'error: --dump needs a directory\n' >&2; exit 2; }
      dump_directory="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    --)
      shift
      while (($#)); do
        commands+=("$1")
        shift
      done
      ;;
    -*)
      printf 'error: unknown option: %s\n' "$1" >&2
      usage >&2
      exit 2
      ;;
    *)
      commands+=("$1")
      shift
      ;;
  esac
done

[[ -x "$xnoop_binary" ]] || {
  printf 'error: Xn00p binary is not executable: %s\n' "$xnoop_binary" >&2
  exit 2
}

binary_directory="$(cd "$(dirname "$xnoop_binary")" && pwd -P)"
xnoop_binary="$binary_directory/$(basename "$xnoop_binary")"

[[ -d "$dump_directory" ]] || {
  printf 'error: dump directory does not exist: %s\n' "$dump_directory" >&2
  exit 2
}

dump_directory="$(cd "$dump_directory" && pwd -P)"

case "$dump_directory" in
  *$'\n'*|*$'\r'*)
    printf 'error: dump directory must not contain newlines\n' >&2
    exit 2
    ;;
esac

[[ -f "$dump_directory/set.out" ]] || {
  printf 'error: dump directory has no set.out: %s\n' "$dump_directory" >&2
  exit 2
}

(
  cd "$dump_directory"

  compgen -G '*.mem' >/dev/null || compgen -G '*.zone' >/dev/null || {
    printf 'error: dump directory has no .mem or .zone fragments: %s\n' "$dump_directory" >&2
    exit 2
  }

  compgen -G 'xn00p.types.*' >/dev/null || {
    printf 'error: dump directory has no Xn00p type library: %s\n' "$dump_directory" >&2
    exit 2
  }
)

((${#commands[@]})) || {
  printf 'error: provide at least one quoted Xn00p command\n' >&2
  usage >&2
  exit 2
}

for command in "${commands[@]}"; do
  case "$command" in
    *$'\n'*|*$'\r'*)
      printf 'error: commands must not contain newlines\n' >&2
      exit 2
      ;;
    *'>'*)
      printf 'error: Xn00p internal redirection is blocked; redirect the runner output instead\n' >&2
      exit 2
      ;;
  esac

  command_name=""
  command_rest=""
  read -r command_name command_rest <<< "$command"
  case "$command_name" in
    help|version|info|syms|sym|type|types|hex|slide|unslide|unpac|cache|dump|sdump|search|refs|zone|zprint|pages|walk|pmap|ptov|pid|ps|task|kexts|macp|ioreg|vnode|mountlist|vfstable|color|debug|verbose|history|reload)
      ;;
    *)
      printf 'error: unsupported, abbreviated, target-changing, or unsafe command: %s\n' "$command_name" >&2
      exit 2
      ;;
  esac

  if [[ "$command_name" == "pmap" && -n "$command_rest" ]]; then
    printf 'error: pmap arguments are blocked because pmap save writes files\n' >&2
    exit 2
  fi
done

(
  cd "$dump_directory"
  {
    printf 'offline %s\n' "$dump_directory"
    for command in "${commands[@]}"; do
      printf '%s\n' "$command"
    done
  } | "$xnoop_binary"
)
