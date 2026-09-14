#!/usr/bin/env bash
# Shared helpers for the pfs shell scripts. Sourced, not executed directly.
# Requires bash and a working directory of the repo root.

_pfs_pick_python() {
  if [ -n "${PFS_PYTHON:-}" ]; then
    if command -v "$PFS_PYTHON" >/dev/null 2>&1; then
      echo "$PFS_PYTHON"
      return 0
    fi
    echo "[pfs] PFS_PYTHON=$PFS_PYTHON not found or not executable" >&2
    return 1
  fi

  local candidates=(python3.13 python3.12 python3.11 python3.10 python3 python)
  if [ -x ".venv/bin/python" ]; then
    candidates=(".venv/bin/python" "${candidates[@]}")
  fi

  local candidate
  for candidate in "${candidates[@]}"; do
    command -v "$candidate" >/dev/null 2>&1 || continue
    if "$candidate" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
      echo "$candidate"
      return 0
    fi
  done
  return 1
}

pfs_setup_python() {
  local py
  if ! py="$(_pfs_pick_python)"; then
    echo "[pfs] No Python >= 3.10 found." >&2
    if command -v python3 >/dev/null 2>&1; then
      echo "[pfs] 'python3' is: $(python3 --version 2>&1)" >&2
    fi
    echo "[pfs] Install Python 3.10+ (e.g. python3.11), or point PFS_PYTHON at one:" >&2
    echo "[pfs]   PFS_PYTHON=/usr/bin/python3.11 $0" >&2
    echo "[pfs] Recommended: python3.11 -m venv .venv && ./sh/0_install.sh" >&2
    exit 1
  fi
  PY="$py"
  export PY
}
