#!/usr/bin/env bash
# pfs - bootstrap a self-contained Python (python-build-standalone) inside the repo.
#
# Downloads a relocatable CPython into ./.python, creates ./.venv from it, and
# installs the server dependencies. Nothing is written outside the project and
# the system Python is never touched.
#
# Usage:
#   ./sh/0_bootstrap.sh
#
# Environment overrides:
#   PFS_PBS_VERSION    CPython minor version to fetch (default 3.11)
#   PFS_PBS_TRIPLE     force a platform triple, e.g. x86_64-unknown-linux-musl
#   PFS_PBS_MUSL=1     on Linux, prefer the musl (fully static) build
#   PFS_PBS_URL        use an explicit tarball URL (offline / pinned)
#   PFS_PBS_DIR        interpreter directory (default <repo>/.python)
#   PFS_VENV_DIR       virtualenv directory (default <repo>/.venv)
#   PFS_PBS_FORCE=1    re-download even if an interpreter already exists
#   PFS_PBS_FULL=1     install the full [gui,server,dev] extras (needs aiortc)
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"

PBS_VERSION="${PFS_PBS_VERSION:-3.11}"
PBS_DIR="${PFS_PBS_DIR:-$REPO/.python}"
VENV_DIR="${PFS_VENV_DIR:-$REPO/.venv}"
API="https://api.github.com/repos/astral-sh/python-build-standalone/releases/latest"

fetch() {
  if command -v curl >/dev/null 2>&1; then
    curl -fL "$1" -o "$2"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$2" "$1"
  else
    echo "[pfs] Need curl or wget to download." >&2
    exit 1
  fi
}

fetch_stdout() {
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$1"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$1"
  else
    echo "[pfs] Need curl or wget to download." >&2
    exit 1
  fi
}

detect_triple() {
  if [ -n "${PFS_PBS_TRIPLE:-}" ]; then
    echo "$PFS_PBS_TRIPLE"
    return 0
  fi
  local os arch machine libc
  os="$(uname -s)"
  machine="$(uname -m)"
  case "$machine" in
    x86_64 | amd64) arch="x86_64" ;;
    aarch64 | arm64) arch="aarch64" ;;
    *)
      echo "[pfs] Unsupported architecture: $machine (set PFS_PBS_TRIPLE)" >&2
      exit 1
      ;;
  esac
  case "$os" in
    Linux)
      libc="gnu"
      [ "${PFS_PBS_MUSL:-0}" = "1" ] && libc="musl"
      echo "${arch}-unknown-linux-${libc}"
      ;;
    Darwin)
      echo "${arch}-apple-darwin"
      ;;
    *)
      echo "[pfs] Unsupported OS: $os (set PFS_PBS_TRIPLE)" >&2
      exit 1
      ;;
  esac
}

resolve_url() {
  local json urls
  json="$(fetch_stdout "$API")" || return 1
  urls="$(printf '%s' "$json" \
    | grep -oE '"browser_download_url":[[:space:]]*"[^"]+"' \
    | sed -E 's/.*"(https:[^"]+)"/\1/' \
    | grep -E "cpython-${PBS_VERSION}\.[0-9]+([+]|%2B)[0-9A-Za-z]*-${TRIPLE}-install_only[.]tar[.]gz$")" || true
  [ -n "$urls" ] || return 1
  printf '%s\n' "$urls" | sed -n '1p'
}

TRIPLE="$(detect_triple)"
echo "[pfs] Target: cpython-${PBS_VERSION} · ${TRIPLE}"
echo "[pfs] Interpreter dir: ${PBS_DIR}"
echo "[pfs] Venv dir: ${VENV_DIR}"

pybin=""
if [ -x "$PBS_DIR/bin/python3" ]; then
  pybin="$PBS_DIR/bin/python3"
elif [ -x "$PBS_DIR/bin/python" ]; then
  pybin="$PBS_DIR/bin/python"
fi

if [ -n "$pybin" ] && [ "${PFS_PBS_FORCE:-0}" != "1" ]; then
  echo "[pfs] Reusing existing interpreter at ${pybin}"
else
  url="${PFS_PBS_URL:-}"
  if [ -z "$url" ]; then
    echo "[pfs] Looking up the latest python-build-standalone release..."
    if ! url="$(resolve_url)"; then
      echo "[pfs] No matching release found for ${PBS_VERSION} / ${TRIPLE}." >&2
      echo "[pfs] Set PFS_PBS_URL to a tarball URL and retry." >&2
      exit 1
    fi
  fi

  echo "[pfs] Downloading: ${url}"
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  fetch "$url" "$tmp/pbs.tar.gz"

  rm -rf "$PBS_DIR"
  mkdir -p "$PBS_DIR"
  tar -xzf "$tmp/pbs.tar.gz" -C "$PBS_DIR" --strip-components=1

  if [ -x "$PBS_DIR/bin/python3" ]; then
    pybin="$PBS_DIR/bin/python3"
  elif [ -x "$PBS_DIR/bin/python" ]; then
    pybin="$PBS_DIR/bin/python"
  else
    echo "[pfs] Extraction did not produce a python binary under ${PBS_DIR}/bin" >&2
    exit 1
  fi
fi

if ! "$pybin" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
  echo "[pfs] Interpreter is older than 3.10; refusing to use it." >&2
  exit 1
fi
echo "[pfs] Interpreter: $("$pybin" --version 2>&1)"

if [ ! -x "$VENV_DIR/bin/python" ]; then
  echo "[pfs] Creating venv at ${VENV_DIR}"
  "$pybin" -m venv "$VENV_DIR"
fi
VPY="$VENV_DIR/bin/python"

echo "[pfs] Upgrading pip"
"$VPY" -m pip install --upgrade pip

if [ "${PFS_PBS_FULL:-0}" = "1" ]; then
  echo "[pfs] Installing full extras [gui,server,dev]"
  "$VPY" -m pip install -e "${REPO}[gui,server,dev]"
else
  echo "[pfs] Installing server dependencies"
  "$VPY" -m pip install fastapi uvicorn websockets
  # Install the pfs package itself without pulling aiortc (server-only deploy).
  "$VPY" -m pip install --no-deps -e "$REPO"
fi

echo
echo "[pfs] Bootstrap complete."
echo "[pfs] Start the signal server with either:"
echo "[pfs]   ./sh/1_signal_server.sh"
echo "[pfs]   ${VPY} -m uvicorn server.signal_server:app --host 0.0.0.0 --port 18765"
echo "[pfs] This venv is server-only (no aiortc). For CLI/GUI add:"
echo "[pfs]   ${VPY} -m pip install -e \"${REPO}[gui,dev]\""
