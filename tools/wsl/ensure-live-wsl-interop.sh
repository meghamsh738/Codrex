#!/usr/bin/env bash

# Repair WSL Windows interop when the current shell inherited a stale socket.
# This avoids hangs/failures when launching cmd.exe or powershell.exe from WSL.
#
# This file may be *sourced* from shell startup files. Keep that safe:
# - do not leave stricter shell options enabled in the caller
# - return from sourced execution instead of exiting the parent shell

__wsl_interop_sourced=0
(return 0 2>/dev/null) && __wsl_interop_sourced=1
__wsl_interop_restore_opts="$(set +o)"
set -euo pipefail

is_live_interop() {
  local candidate="${1:-}"
  [[ -n "$candidate" && -S "$candidate" ]] || return 1
  env WSL_INTEROP="$candidate" cmd.exe /c exit 0 >/dev/null 2>&1
}

main() {
  if [[ -z "${WSL_DISTRO_NAME:-}" ]]; then
    return 0
  fi

  local current candidate
  current="${WSL_INTEROP:-}"
  if is_live_interop "$current"; then
    return 0
  fi

  for candidate in /run/WSL/*_interop; do
    [[ -e "$candidate" ]] || continue
    if is_live_interop "$candidate"; then
      export WSL_INTEROP="$candidate"
      return 0
    fi
  done

  return 0
}

main "$@"
__wsl_interop_status=$?
eval "$__wsl_interop_restore_opts"
unset __wsl_interop_restore_opts
unset -f is_live_interop
unset -f main

if [ "$__wsl_interop_sourced" -eq 1 ]; then
  unset __wsl_interop_sourced
  return "$__wsl_interop_status"
fi

unset __wsl_interop_sourced
exit "$__wsl_interop_status"
