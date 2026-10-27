#!/bin/sh
# Normal-user setup only. Host package/group administration is an operator task.
set -eu
umask 027
PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export PATH

usage() {
  echo "Usage: $0 {show-config|verify|create-venv|help}"
  echo "Run as your normal user; never sudo this script."
  echo "CONTINUUM_SMOKE_BASE_ROOT defaults to \$HOME/continuum_smoke."
  echo "CONTINUUM_SMOKE_PYTHON defaults to \$HOME/venvs/continuum/bin/python3."
}
COMMAND=${1:-help}
case "$COMMAND" in
  help|--help|-h) usage; exit 0 ;;
  show-config|verify|create-venv) ;;
  *) usage >&2; exit 2 ;;
esac
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
[ "$(id -u)" -ne 0 ] || { echo "Run as a normal user, not root." >&2; exit 2; }
case "${HOME:-}" in
  /*) ;;
  *) echo "HOME must be an existing canonical absolute directory." >&2; exit 2 ;;
esac
if [ "$HOME" = / ] || [ ! -d "$HOME" ] || [ "$(realpath -- "$HOME")" != "$HOME" ]; then
  echo "HOME must be an existing canonical absolute directory, not /." >&2
  exit 2
fi
REPO_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd -P)
BASE_ROOT=${CONTINUUM_SMOKE_BASE_ROOT:-$HOME/continuum_smoke}
PYTHON_BIN=${CONTINUUM_SMOKE_PYTHON:-$HOME/venvs/continuum/bin/python3}
for path in "$BASE_ROOT" "$(dirname -- "$PYTHON_BIN")"; do
  case "$path" in
    /*) ;;
    *) echo "Runtime paths must be canonical absolute paths: $path" >&2; exit 2 ;;
  esac
  if [ "$path" = / ] || [ "$(realpath -m -- "$path")" != "$path" ]; then
    echo "Runtime paths must be canonical and must not be /: $path" >&2
    exit 2
  fi
done
case "$PYTHON_BIN" in
  */bin/python3) ;;
  *) echo "Python must name a venv bin/python3: $PYTHON_BIN" >&2; exit 2 ;;
esac

case "$COMMAND" in
  show-config)
    printf 'RUNNER_USER=%s\nREPO_ROOT=%s\nBASE_ROOT=%s\nPYTHON_BIN=%s\n' \
      "$(id -un)" "$REPO_ROOT" "$BASE_ROOT" "$PYTHON_BIN"
    ;;
  create-venv)
    VENV_ROOT=$(dirname -- "$(dirname -- "$PYTHON_BIN")")
    if [ -e "$VENV_ROOT" ] || [ -L "$VENV_ROOT" ]; then
      echo "Refusing to overwrite existing venv path: $VENV_ROOT" >&2
      exit 2
    fi
    /usr/bin/python3 -m venv "$VENV_ROOT"
    echo "Created $VENV_ROOT; install reviewed requirements as your normal user."
    ;;
  verify)
    if [ ! -x "$PYTHON_BIN" ]; then
      echo "Python interpreter missing or not executable: $PYTHON_BIN" >&2
      exit 2
    fi
    "$PYTHON_BIN" -c 'import sys; assert sys.prefix != sys.base_prefix, "Python must be a venv"'
    [ -r /dev/kvm ] && [ -w /dev/kvm ] || {
      echo "Normal user needs read/write access to /dev/kvm; ask the host operator." >&2
      exit 1
    }
    virsh -c "${LIBVIRT_DEFAULT_URI:-qemu:///system}" list --all
    CONTINUUM_SMOKE_BASE_ROOT="$BASE_ROOT" CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      sh "$REPO_ROOT/scripts/test/run_smoke_host.sh" check-prereqs --suite smoke
    CONTINUUM_SMOKE_BASE_ROOT="$BASE_ROOT" CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      sh "$REPO_ROOT/scripts/test/run_smoke_host.sh" check-prereqs --suite benchmark_smoke
    echo "Normal-user host verification passed."
    ;;
esac
