#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

RUNNER_USER="${RUNNER_USER:-continuum-smoke}"
CALLER_USER="${CALLER_USER:-${SUDO_USER:-${USER:-}}}"
INSTALL_PATH="${INSTALL_PATH:-/usr/local/bin/run-continuum-smoke}"
HOSTCTL_PATH="${HOSTCTL_PATH:-/usr/local/bin/continuum-hostctl}"
LIVE_REPO_ROOT="${LIVE_REPO_ROOT:-$REPO_ROOT}"
DEDICATED_REPO_ROOT="${DEDICATED_REPO_ROOT:-/srv/continuum/repo}"
RUNNER_HOME="${RUNNER_HOME:-/home/$RUNNER_USER}"
SMOKE_BASE_ROOT="${SMOKE_BASE_ROOT:-$RUNNER_HOME/continuum_smoke}"
VENV_ROOT="${VENV_ROOT:-$RUNNER_HOME/venvs/continuum}"
MODE="${MODE:-dedicated}"
READONLY_DEDICATED_REPO="${READONLY_DEDICATED_REPO:-1}"
LIBVIRT_URI="${LIBVIRT_URI:-qemu:///system}"
QEMU_BRIDGE_NAME="${QEMU_BRIDGE_NAME:-}"
QEMU_BRIDGE_GATEWAY="${QEMU_BRIDGE_GATEWAY:-}"
SYNC_MARKER_NAME="${SYNC_MARKER_NAME:-.continuum-smoke-sync}"
SYNC_PROBE_FILES="${SYNC_PROBE_FILES:-continuum.py infrastructure/ansible.py infrastructure/qemu/qemu.py input/configuration/runtime_module_loader.py scripts/test/run_smoke_host.sh scripts/test/setup_agent_host.sh scripts/test/prime_local_registry_cache.py scripts/test/test_config.json}"
HOSTCTL_INTERFACE_VERSION="2026-05-30-wrapper-base-root"

usage() {
  cat <<EOF
Usage:
  $0 show-config
  $0 install [dedicated|live]
  $0 sync-repo
  $0 verify
  $0 prime-registry-cache [--suite SUITE | --config CONFIG ...]
  $0 install-hostctl
  $0 print-agent-command [scenario]
  $0 print-hostctl-command [subcommand...]
  $0 print-hostctl-script

Compatibility commands:
  $0 create-user
  $0 grant-live-repo-access
  $0 create-dedicated-repo
  $0 sync-dedicated-repo
  $0 prepare-base-root
  $0 install-host-prereqs
  $0 create-venv [dedicated|live]
  $0 install-wrapper [dedicated|live] [absolute/path/to/continuum_smoke]
  $0 install-sudoers
  $0 all-live
  $0 all-dedicated

Canonical setup:
  $0 install

Environment overrides:
  RUNNER_USER             default: $RUNNER_USER
  CALLER_USER             default: $CALLER_USER
  INSTALL_PATH            default: $INSTALL_PATH
  HOSTCTL_PATH            default: $HOSTCTL_PATH
  LIVE_REPO_ROOT          default: $LIVE_REPO_ROOT
  DEDICATED_REPO_ROOT     default: $DEDICATED_REPO_ROOT
  RUNNER_HOME             default: $RUNNER_HOME
  SMOKE_BASE_ROOT         default: $SMOKE_BASE_ROOT
  VENV_ROOT               default: $VENV_ROOT
  MODE                    default: $MODE
  READONLY_DEDICATED_REPO default: $READONLY_DEDICATED_REPO
  LIBVIRT_URI             default: $LIBVIRT_URI
  QEMU_BRIDGE_NAME        default: ${QEMU_BRIDGE_NAME:-<unset>}
  QEMU_BRIDGE_GATEWAY     default: ${QEMU_BRIDGE_GATEWAY:-<unset>}
EOF
}

log() {
  printf '%s\n' "$*"
}

sync_marker_path() {
  printf '%s/%s\n' "$DEDICATED_REPO_ROOT" "$SYNC_MARKER_NAME"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    log "Missing required command: $1" >&2
    exit 1
  fi
}

run_root() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

run_root_noninteractive() {
  if [ "$(id -u)" -eq 0 ]; then
    "$@"
  else
    sudo -n "$@"
  fi
}

runner_exec() {
  require_cmd sudo
  sudo -n -u "$RUNNER_USER" "$@"
}

repo_root_for_mode() {
  mode_arg=$1
  case "$mode_arg" in
    dedicated)
      printf '%s\n' "$DEDICATED_REPO_ROOT"
      ;;
    live)
      printf '%s\n' "$LIVE_REPO_ROOT"
      ;;
    *)
      log "Unsupported mode: $mode_arg" >&2
      exit 2
      ;;
  esac
}

validate_smoke_base_root() {
  path=$1
  case "$path" in
    /*)
      ;;
    *)
      log "Smoke base root must be an absolute path: $path" >&2
      exit 2
      ;;
  esac

  case "$path" in
    /|/home|/mnt|*..*|*//*)
      log "Refusing unsafe smoke base root: $path" >&2
      exit 2
      ;;
  esac

  if [ "$(basename "$path")" != "continuum_smoke" ]; then
    log "Smoke base root must end in continuum_smoke: $path" >&2
    exit 2
  fi
}

emit_wrapper_script() {
  wrapper_repo_root=$1
  wrapper_mode=$2
  wrapper_base_root=${3:-$SMOKE_BASE_ROOT}
  validate_smoke_base_root "$wrapper_base_root"
  cat <<EOF
#!/bin/sh
set -eu
umask 022

REPO_ROOT=$wrapper_repo_root
HOSTCTL_PATH=$HOSTCTL_PATH
RUNNER_HOME=$RUNNER_HOME
BASE_ROOT=$wrapper_base_root
PYTHON_BIN=$VENV_ROOT/bin/python3
ANSIBLE_PLAYBOOK_BIN=$VENV_ROOT/bin/ansible-playbook
LIBVIRT_URI=$LIBVIRT_URI
QEMU_BRIDGE_NAME=$QEMU_BRIDGE_NAME
QEMU_BRIDGE_GATEWAY=$QEMU_BRIDGE_GATEWAY
WRAPPER_MODE=$wrapper_mode
SYNC_MARKER_PATH=$wrapper_repo_root/$SYNC_MARKER_NAME
REPO_SCRIPT=\$REPO_ROOT/scripts/test/run_smoke_host.sh

if [ ! -x "\$PYTHON_BIN" ]; then
  echo "Could not find Continuum smoke Python interpreter: \$PYTHON_BIN" >&2
  echo "Run the host setup install step first." >&2
  exit 2
fi

if [ ! -x "\$ANSIBLE_PLAYBOOK_BIN" ]; then
  echo "Could not find ansible-playbook in the runner venv: \$ANSIBLE_PLAYBOOK_BIN" >&2
  echo "Refresh the host runner venv with ./scripts/test/setup_agent_host.sh create-venv $wrapper_mode" >&2
  exit 2
fi

if [ ! -r "\$REPO_SCRIPT" ]; then
  echo "Could not find runner repo script: \$REPO_SCRIPT" >&2
  echo "Refresh the host runner repo with:" >&2
  echo "  sudo -n \$HOSTCTL_PATH sync-repo" >&2
  echo "  sudo -n \$HOSTCTL_PATH install-wrapper $wrapper_mode" >&2
  exit 2
fi

if [ "\$WRAPPER_MODE" = "dedicated" ] && [ ! -r "\$SYNC_MARKER_PATH" ]; then
  echo "Dedicated runner repo sync marker is missing or unreadable: \$SYNC_MARKER_PATH" >&2
  echo "Refresh the host runner with:" >&2
  echo "  sudo -n \$HOSTCTL_PATH sync-repo" >&2
  echo "  sudo -n \$HOSTCTL_PATH install-wrapper dedicated" >&2
  exit 2
fi

exec env -i \\
  HOME=\$RUNNER_HOME \\
  CONTINUUM_SMOKE_BASE_ROOT="\$BASE_ROOT" \\
  CONTINUUM_SMOKE_PYTHON="\$PYTHON_BIN" \\
  CONTINUUM_SMOKE_ANSIBLE_PLAYBOOK="\$ANSIBLE_PLAYBOOK_BIN" \\
  LIBVIRT_DEFAULT_URI="\$LIBVIRT_URI" \\
  CONTINUUM_REPO_ROOT="\$REPO_ROOT" \\
  \${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME=\$QEMU_BRIDGE_NAME} \\
  \${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY=\$QEMU_BRIDGE_GATEWAY} \\
  sh "\$REPO_SCRIPT" "\$@"
EOF
}

write_wrapper() {
  wrapper_repo_root=$1
  wrapper_mode=$2
  wrapper_base_root=${3:-$SMOKE_BASE_ROOT}

  run_root install -d -m 0755 "$(dirname "$INSTALL_PATH")"
  tmp_wrapper=$(mktemp)
  emit_wrapper_script "$wrapper_repo_root" "$wrapper_mode" "$wrapper_base_root" >"$tmp_wrapper"
  run_root install -m 0755 "$tmp_wrapper" "$INSTALL_PATH"
  run_root chown root:root "$INSTALL_PATH"
  rm -f "$tmp_wrapper"
}

emit_hostctl_script() {
  cat <<EOF
#!/bin/sh
set -eu
umask 022

RUNNER_USER=$RUNNER_USER
INSTALL_PATH=$INSTALL_PATH
HOSTCTL_PATH=$HOSTCTL_PATH
LIVE_REPO_ROOT=$LIVE_REPO_ROOT
DEDICATED_REPO_ROOT=$DEDICATED_REPO_ROOT
RUNNER_HOME=$RUNNER_HOME
SMOKE_BASE_ROOT=$SMOKE_BASE_ROOT
VENV_ROOT=$VENV_ROOT
READONLY_DEDICATED_REPO=$READONLY_DEDICATED_REPO
LIBVIRT_URI=$LIBVIRT_URI
QEMU_BRIDGE_NAME=$QEMU_BRIDGE_NAME
QEMU_BRIDGE_GATEWAY=$QEMU_BRIDGE_GATEWAY
SYNC_MARKER_NAME=$SYNC_MARKER_NAME
SYNC_PROBE_FILES="$SYNC_PROBE_FILES"
HOSTCTL_INTERFACE_VERSION=$HOSTCTL_INTERFACE_VERSION

usage() {
  cat <<EOF_HOSTCTL
Usage:
  \$0 show-config
  \$0 sync-repo
  \$0 install-wrapper [dedicated|live] [absolute/path/to/continuum_smoke]
  \$0 verify [dedicated|live]
  \$0 prime-registry-cache [--suite SUITE | --config CONFIG ...]
  \$0 print-agent-command [scenario]
EOF_HOSTCTL
}

log() {
  printf '%s\\n' "\$*"
}

require_cmd() {
  if ! command -v "\$1" >/dev/null 2>&1; then
    log "Missing required command: \$1" >&2
    exit 1
  fi
}

runner_exec() {
  require_cmd sudo
  sudo -n -u "\$RUNNER_USER" "\$@"
}

sync_marker_path() {
  printf '%s/%s\\n' "\$DEDICATED_REPO_ROOT" "\$SYNC_MARKER_NAME"
}

repo_root_for_mode() {
  mode_arg=\$1
  case "\$mode_arg" in
    dedicated)
      printf '%s\\n' "\$DEDICATED_REPO_ROOT"
      ;;
    live)
      printf '%s\\n' "\$LIVE_REPO_ROOT"
      ;;
    *)
      log "Unsupported mode: \$mode_arg" >&2
      exit 2
      ;;
  esac
}

validate_smoke_base_root() {
  path=\$1
  case "\$path" in
    /*)
      ;;
    *)
      log "Smoke base root must be an absolute path: \$path" >&2
      exit 2
      ;;
  esac

  case "\$path" in
    /|/home|/mnt|*..*|*//*)
      log "Refusing unsafe smoke base root: \$path" >&2
      exit 2
      ;;
  esac

  if [ "\$(basename "\$path")" != "continuum_smoke" ]; then
    log "Smoke base root must end in continuum_smoke: \$path" >&2
    exit 2
  fi
}

prepare_base_root_path() {
  target_base_root=\$1
  validate_smoke_base_root "\$target_base_root"
  install -d -o "\$RUNNER_USER" -g "\$RUNNER_USER" -m 0755 "\$target_base_root"
  if ! runner_exec test -w "\$target_base_root"; then
    log "Smoke base root is not writable by \$RUNNER_USER: \$target_base_root" >&2
    exit 1
  fi
  log "Prepared smoke base root at \$target_base_root"
}

write_wrapper() {
  wrapper_repo_root=\$1
  wrapper_mode=\$2
  wrapper_base_root=\${3:-\$SMOKE_BASE_ROOT}
  validate_smoke_base_root "\$wrapper_base_root"

  install -d -m 0755 "\$(dirname "\$INSTALL_PATH")"
  tmp_wrapper=\$(mktemp)
  cat >"\$tmp_wrapper" <<EOF_WRAPPER
#!/bin/sh
set -eu
umask 022

REPO_ROOT=\$wrapper_repo_root
HOSTCTL_PATH=\$HOSTCTL_PATH
RUNNER_HOME=\$RUNNER_HOME
BASE_ROOT=\$wrapper_base_root
PYTHON_BIN=\$VENV_ROOT/bin/python3
ANSIBLE_PLAYBOOK_BIN=\$VENV_ROOT/bin/ansible-playbook
LIBVIRT_URI=\$LIBVIRT_URI
QEMU_BRIDGE_NAME=\$QEMU_BRIDGE_NAME
QEMU_BRIDGE_GATEWAY=\$QEMU_BRIDGE_GATEWAY
WRAPPER_MODE=\$wrapper_mode
SYNC_MARKER_PATH=\$wrapper_repo_root/\$SYNC_MARKER_NAME
REPO_SCRIPT=\\\$REPO_ROOT/scripts/test/run_smoke_host.sh

if [ ! -x "\\\$PYTHON_BIN" ]; then
  echo "Could not find Continuum smoke Python interpreter: \\\$PYTHON_BIN" >&2
  echo "Run the host setup install step first." >&2
  exit 2
fi

if [ ! -x "\\\$ANSIBLE_PLAYBOOK_BIN" ]; then
  echo "Could not find ansible-playbook in the runner venv: \\\$ANSIBLE_PLAYBOOK_BIN" >&2
  echo "Refresh the host runner venv with ./scripts/test/setup_agent_host.sh create-venv \$wrapper_mode" >&2
  exit 2
fi

if [ ! -r "\\\$REPO_SCRIPT" ]; then
  echo "Could not find runner repo script: \\\$REPO_SCRIPT" >&2
  echo "Refresh the host runner repo with:" >&2
  echo "  sudo -n \\\$HOSTCTL_PATH sync-repo" >&2
  echo "  sudo -n \\\$HOSTCTL_PATH install-wrapper \$wrapper_mode" >&2
  exit 2
fi

if [ "\\\$WRAPPER_MODE" = "dedicated" ] && [ ! -r "\\\$SYNC_MARKER_PATH" ]; then
  echo "Dedicated runner repo sync marker is missing or unreadable: \\\$SYNC_MARKER_PATH" >&2
  echo "Refresh the host runner with:" >&2
  echo "  sudo -n \\\$HOSTCTL_PATH sync-repo" >&2
  echo "  sudo -n \\\$HOSTCTL_PATH install-wrapper dedicated" >&2
  exit 2
fi

exec env -i \\
  HOME=\\\$RUNNER_HOME \\
  CONTINUUM_SMOKE_BASE_ROOT="\\\$BASE_ROOT" \\
  CONTINUUM_SMOKE_PYTHON="\\\$PYTHON_BIN" \\
  CONTINUUM_SMOKE_ANSIBLE_PLAYBOOK="\\\$ANSIBLE_PLAYBOOK_BIN" \\
  LIBVIRT_DEFAULT_URI="\\\$LIBVIRT_URI" \\
  CONTINUUM_REPO_ROOT="\\\$REPO_ROOT" \\
  \\\${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME=\\\$QEMU_BRIDGE_NAME} \\
  \\\${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY=\\\$QEMU_BRIDGE_GATEWAY} \\
  sh "\\\$REPO_SCRIPT" "\\\$@"
EOF_WRAPPER
  install -m 0755 "\$tmp_wrapper" "\$INSTALL_PATH"
  chown root:root "\$INSTALL_PATH"
  rm -f "\$tmp_wrapper"
}

sync_dedicated_repo() {
  require_cmd rsync

  rsync -a --delete \\
    --exclude '.git' \\
    --exclude '__pycache__' \\
    --exclude '.pytest_cache' \\
    --exclude 'logs' \\
    "\$LIVE_REPO_ROOT"/ \\
    "\$DEDICATED_REPO_ROOT"/

  if [ "\$READONLY_DEDICATED_REPO" = "1" ]; then
    chown -R root:"\$RUNNER_USER" "\$DEDICATED_REPO_ROOT"
    find "\$DEDICATED_REPO_ROOT" -type d -exec chmod 0750 {} +
    find "\$DEDICATED_REPO_ROOT" -type f -exec chmod 0640 {} +
    log "Synced \$LIVE_REPO_ROOT to read-only dedicated repo \$DEDICATED_REPO_ROOT"
  else
    chown -R "\$RUNNER_USER:\$RUNNER_USER" "\$DEDICATED_REPO_ROOT"
    log "Synced \$LIVE_REPO_ROOT to writable dedicated repo \$DEDICATED_REPO_ROOT"
  fi

  tmp_marker=\$(mktemp)
  live_head=\$(git -C "\$LIVE_REPO_ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')
  if git -C "\$LIVE_REPO_ROOT" diff --quiet --ignore-submodules HEAD -- 2>/dev/null; then
    live_tree_state=clean
  else
    live_tree_state=dirty_or_unknown
  fi
  {
    printf 'SYNCED_FROM=%s\\n' "\$LIVE_REPO_ROOT"
    printf 'SYNCED_AT_UTC=%s\\n' "\$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'LIVE_HEAD=%s\\n' "\$live_head"
    printf 'LIVE_TREE_STATE=%s\\n' "\$live_tree_state"
  } >"\$tmp_marker"
  install -o root -g "\$RUNNER_USER" -m 0640 \\
    "\$tmp_marker" "\$(sync_marker_path)"
  rm -f "\$tmp_marker"
}

verify_wrapper_target() {
  expected_repo_root=\$1
  if [ ! -r "\$INSTALL_PATH" ]; then
    log "Installed wrapper is not readable: \$INSTALL_PATH" >&2
    exit 1
  fi

  wrapper_repo_root=\$(awk -F= '/^REPO_ROOT=/{print \$2; exit}' "\$INSTALL_PATH")
  if [ "\$wrapper_repo_root" != "\$expected_repo_root" ]; then
    log "Installed wrapper points at \$wrapper_repo_root but expected \$expected_repo_root" >&2
    log "Refresh the host wrapper with: sudo -n \$HOSTCTL_PATH install-wrapper dedicated" >&2
    exit 1
  fi

  if ! grep -q 'scripts/test/run_smoke_host.sh' "\$INSTALL_PATH"; then
    log "Installed wrapper is not using the canonical repo smoke runner script" >&2
    exit 1
  fi

  wrapper_base_root=\$(awk -F= '/^BASE_ROOT=/{print \$2; exit}' "\$INSTALL_PATH")
  validate_smoke_base_root "\$wrapper_base_root"
  if ! runner_exec test -w "\$wrapper_base_root"; then
    log "Installed wrapper smoke base root is not writable by \$RUNNER_USER: \$wrapper_base_root" >&2
    exit 1
  fi
}

verify_dedicated_repo_sync() {
  marker_path=\$(sync_marker_path)
  if ! test -r "\$marker_path"; then
    log "Dedicated repo sync marker is missing: \$marker_path" >&2
    log "Refresh the dedicated repo with: sudo -n \$HOSTCTL_PATH sync-repo" >&2
    exit 1
  fi

  marker_source=\$(awk -F= '/^SYNCED_FROM=/{print \$2; exit}' "\$marker_path")
  if [ -n "\$marker_source" ] && [ "\$marker_source" != "\$LIVE_REPO_ROOT" ]; then
    log "Dedicated repo was last synced from \$marker_source, not \$LIVE_REPO_ROOT" >&2
    log "Refresh the dedicated repo with: sudo -n \$HOSTCTL_PATH sync-repo" >&2
    exit 1
  fi

  for rel_path in \$SYNC_PROBE_FILES; do
    live_path="\$LIVE_REPO_ROOT/\$rel_path"
    dedicated_path="\$DEDICATED_REPO_ROOT/\$rel_path"

    if [ ! -r "\$live_path" ]; then
      log "Live repo probe file is unreadable: \$live_path" >&2
      exit 1
    fi
    if ! test -r "\$dedicated_path"; then
      log "Dedicated repo probe file is unreadable: \$dedicated_path" >&2
      exit 1
    fi

    live_cksum=\$(cksum "\$live_path" | awk '{print \$1 ":" \$2}')
    dedicated_cksum=\$(cksum "\$dedicated_path" | awk '{print \$1 ":" \$2}')
    if [ "\$live_cksum" != "\$dedicated_cksum" ]; then
      log "Dedicated repo drift detected for \$rel_path" >&2
      log "Live repo checksum: \$live_cksum" >&2
      log "Dedicated repo checksum: \$dedicated_cksum" >&2
      log "Refresh the dedicated repo with: sudo -n \$HOSTCTL_PATH sync-repo" >&2
      exit 1
    fi
  done
}

verify_hostctl_interface() {
  setup_script="\$LIVE_REPO_ROOT/scripts/test/setup_agent_host.sh"
  if [ ! -r "\$setup_script" ]; then
    log "Host setup script is unreadable: \$setup_script" >&2
    exit 1
  fi
  if [ ! -r "\$HOSTCTL_PATH" ]; then
    log "Installed maintenance helper is unreadable: \$HOSTCTL_PATH" >&2
    exit 1
  fi

  source_version=\$(awk -F= '/^HOSTCTL_INTERFACE_VERSION=/{gsub(/"/, "", \$2); print \$2; exit}' "\$setup_script")
  if [ -z "\$source_version" ]; then
    log "Host setup script does not declare HOSTCTL_INTERFACE_VERSION: \$setup_script" >&2
    exit 1
  fi
  installed_version=\$(awk -F= '/^HOSTCTL_INTERFACE_VERSION=/{gsub(/"/, "", \$2); print \$2; exit}' "\$HOSTCTL_PATH")
  if [ -z "\$installed_version" ]; then
    log "Installed maintenance helper does not declare HOSTCTL_INTERFACE_VERSION: \$HOSTCTL_PATH" >&2
    exit 1
  fi

  if [ "\$installed_version" != "\$source_version" ]; then
    log "Installed maintenance helper is stale: interface \$installed_version, expected \$source_version" >&2
    log "Refresh the helper from the live checkout, then rerun verify:" >&2
    log "  \$setup_script install-hostctl" >&2
    log "  sudo -n \$HOSTCTL_PATH verify" >&2
    exit 1
  fi

  if ! grep -q 'prime-registry-cache)' "\$HOSTCTL_PATH"; then
    log "Installed maintenance helper does not expose prime-registry-cache" >&2
    log "Refresh the helper from the live checkout with: \$setup_script install-hostctl" >&2
    exit 1
  fi
}

verify() {
  mode_arg="\${1:-dedicated}"
  repo_root=\$(repo_root_for_mode "\$mode_arg")

  require_cmd virsh

  log "Verifying maintenance helper interface"
  verify_hostctl_interface

  log "Verifying installed wrapper target"
  verify_wrapper_target "\$repo_root"

  log "Verifying libvirt access"
  runner_exec virsh list --all

  log "Verifying /dev/kvm readability"
  runner_exec test -r /dev/kvm

  log "Verifying runner repo readability"
  runner_exec test -r "\$repo_root/continuum.py"

  if [ "\$mode_arg" = "dedicated" ] && [ "\$READONLY_DEDICATED_REPO" = "1" ]; then
    log "Verifying dedicated repo is synced to the live checkout"
    verify_dedicated_repo_sync

    log "Verifying dedicated repo is not writable by \$RUNNER_USER"
    if runner_exec test -w "\$repo_root/continuum.py"; then
      log "Dedicated repo is unexpectedly writable by \$RUNNER_USER" >&2
      exit 1
    fi
  fi

  log "Verifying wrapper prereqs"
  runner_exec "\$INSTALL_PATH" check-prereqs
}

prime_registry_cache() {
  if [ "\$#" -eq 0 ]; then
    log "Usage: \$0 prime-registry-cache [--suite SUITE | --config CONFIG ...]" >&2
    exit 2
  fi

  require_cmd curl
  require_cmd docker

  repo_root="\$DEDICATED_REPO_ROOT"
  if [ "\$READONLY_DEDICATED_REPO" = "1" ]; then
    verify_dedicated_repo_sync
  fi

  if [ ! -x "\$VENV_ROOT/bin/python3" ]; then
    log "Could not find Continuum smoke Python interpreter: \$VENV_ROOT/bin/python3" >&2
    exit 2
  fi

  cd "\$repo_root"
  PYTHONPATH=. "\$VENV_ROOT/bin/python3" scripts/test/prime_local_registry_cache.py "\$@"
}

print_agent_command() {
  scenario="\${1:-benchmark_k8s_resume}"
  printf 'sudo -n -u %s %s %s\\n' "\$RUNNER_USER" "\$INSTALL_PATH" "\$scenario"
}

show_config() {
  marker_path=\$(sync_marker_path)
  marker_dir=\$(dirname "\$marker_path")
  cat <<EOF_SHOW
RUNNER_USER=\$RUNNER_USER
RUNNER_HOME=\$RUNNER_HOME
SMOKE_BASE_ROOT=\$SMOKE_BASE_ROOT
VENV_ROOT=\$VENV_ROOT
INSTALL_PATH=\$INSTALL_PATH
HOSTCTL_PATH=\$HOSTCTL_PATH
LIVE_REPO_ROOT=\$LIVE_REPO_ROOT
DEDICATED_REPO_ROOT=\$DEDICATED_REPO_ROOT
READONLY_DEDICATED_REPO=\$READONLY_DEDICATED_REPO
LIBVIRT_URI=\$LIBVIRT_URI
QEMU_BRIDGE_NAME=\$QEMU_BRIDGE_NAME
QEMU_BRIDGE_GATEWAY=\$QEMU_BRIDGE_GATEWAY
DEDICATED_SYNC_MARKER=\$marker_path
EOF_SHOW

  if [ -r "\$marker_path" ]; then
    printf 'DEDICATED_SYNC_MARKER_STATUS=present\\n'
    cat "\$marker_path"
  elif [ -x "\$marker_dir" ] || [ -r "\$marker_dir" ]; then
    printf 'DEDICATED_SYNC_MARKER_STATUS=missing\\n'
  else
    printf 'DEDICATED_SYNC_MARKER_STATUS=unreadable\\n'
  fi

  if [ -r "\$INSTALL_PATH" ]; then
    wrapper_base_root=\$(awk -F= '/^BASE_ROOT=/{print \$2; exit}' "\$INSTALL_PATH")
    if [ -n "\$wrapper_base_root" ]; then
      printf 'INSTALLED_WRAPPER_BASE_ROOT=%s\\n' "\$wrapper_base_root"
    fi
  fi
}

if [ "\$(id -u)" -ne 0 ]; then
  echo "Run this helper via sudo." >&2
  exit 2
fi

cmd="\${1:-}"

case "\$cmd" in
  show-config)
    show_config
    ;;
  sync-repo)
    sync_dedicated_repo
    ;;
  install-wrapper)
    mode_arg="\${2:-dedicated}"
    target_base_root="\${3:-\$SMOKE_BASE_ROOT}"
    prepare_base_root_path "\$target_base_root"
    write_wrapper "\$(repo_root_for_mode "\$mode_arg")" "\$mode_arg" "\$target_base_root"
    ;;
  verify)
    verify "\${2:-dedicated}"
    ;;
  prime-registry-cache)
    shift
    prime_registry_cache "\$@"
    ;;
  print-agent-command)
    print_agent_command "\${2:-benchmark_k8s_resume}"
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    log "Unknown command: \$cmd" >&2
    usage >&2
    exit 2
    ;;
esac
EOF
}

install_hostctl() {
  run_root install -d -m 0755 "$(dirname "$HOSTCTL_PATH")"
  tmp_hostctl=$(mktemp)
  emit_hostctl_script >"$tmp_hostctl"
  run_root install -m 0755 "$tmp_hostctl" "$HOSTCTL_PATH"
  run_root chown root:root "$HOSTCTL_PATH"
  rm -f "$tmp_hostctl"
  log "Installed maintenance helper at $HOSTCTL_PATH"
}

create_user() {
  if id "$RUNNER_USER" >/dev/null 2>&1; then
    log "User $RUNNER_USER already exists"
  else
    run_root useradd --system --create-home \
      --home-dir "$RUNNER_HOME" \
      --shell /usr/sbin/nologin \
      "$RUNNER_USER"
    log "Created user $RUNNER_USER"
  fi

  run_root usermod -aG libvirt,kvm "$RUNNER_USER"
  log "Ensured $RUNNER_USER is in groups: libvirt,kvm"
}

grant_live_repo_access() {
  require_cmd setfacl
  run_root setfacl -m "u:$RUNNER_USER:--x" "$(dirname "$LIVE_REPO_ROOT")"
  run_root setfacl -R -m "u:$RUNNER_USER:rX" "$LIVE_REPO_ROOT"
  run_root setfacl -dR -m "u:$RUNNER_USER:rX" "$LIVE_REPO_ROOT"
  log "Granted read-only live-worktree ACL access for $RUNNER_USER to $LIVE_REPO_ROOT"
}

create_dedicated_repo() {
  require_cmd rsync
  run_root install -d -o root -g "$RUNNER_USER" -m 0750 \
    "$(dirname "$DEDICATED_REPO_ROOT")"
  run_root install -d -o root -g "$RUNNER_USER" -m 0750 \
    "$DEDICATED_REPO_ROOT"
  log "Prepared dedicated repo directory at $DEDICATED_REPO_ROOT"
}

sync_dedicated_repo() {
  require_cmd rsync

  run_root rsync -a --delete \
    --exclude '.git' \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude 'logs' \
    "$LIVE_REPO_ROOT"/ \
    "$DEDICATED_REPO_ROOT"/

  if [ "$READONLY_DEDICATED_REPO" = "1" ]; then
    run_root chown -R root:"$RUNNER_USER" "$DEDICATED_REPO_ROOT"
    run_root find "$DEDICATED_REPO_ROOT" -type d -exec chmod 0750 {} +
    run_root find "$DEDICATED_REPO_ROOT" -type f -exec chmod 0640 {} +
    log "Synced $LIVE_REPO_ROOT to read-only dedicated repo $DEDICATED_REPO_ROOT"
  else
    run_root chown -R "$RUNNER_USER:$RUNNER_USER" "$DEDICATED_REPO_ROOT"
    log "Synced $LIVE_REPO_ROOT to writable dedicated repo $DEDICATED_REPO_ROOT"
  fi

  tmp_marker=$(mktemp)
  live_head=$(git -C "$LIVE_REPO_ROOT" rev-parse HEAD 2>/dev/null || printf 'unknown')
  if git -C "$LIVE_REPO_ROOT" diff --quiet --ignore-submodules HEAD -- 2>/dev/null; then
    live_tree_state=clean
  else
    live_tree_state=dirty_or_unknown
  fi
  {
    printf 'SYNCED_FROM=%s\n' "$LIVE_REPO_ROOT"
    printf 'SYNCED_AT_UTC=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    printf 'LIVE_HEAD=%s\n' "$live_head"
    printf 'LIVE_TREE_STATE=%s\n' "$live_tree_state"
  } >"$tmp_marker"
  run_root install -o root -g "$RUNNER_USER" -m 0640 \
    "$tmp_marker" "$(sync_marker_path)"
  rm -f "$tmp_marker"
}

prepare_base_root() {
  prepare_base_root_path "$SMOKE_BASE_ROOT"
}

prepare_base_root_path() {
  target_base_root=$1
  validate_smoke_base_root "$target_base_root"
  run_root install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0755 "$target_base_root"
  if ! runner_exec test -w "$target_base_root"; then
    log "Smoke base root is not writable by $RUNNER_USER: $target_base_root" >&2
    exit 1
  fi
  log "Prepared smoke base root at $target_base_root"
}

install_host_prereqs() {
  require_cmd apt-get
  run_root apt-get update
  run_root apt-get install -y acl curl qemu-utils cloud-image-utils
  log "Installed host prerequisites: acl, curl, qemu-utils, cloud-image-utils"
}

create_venv() {
  mode_arg="${1:-$MODE}"
  requirements_root=$(repo_root_for_mode "$mode_arg")

  require_cmd python3
  run_root install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0755 "$(dirname "$VENV_ROOT")"
  if ! runner_exec test -x "$VENV_ROOT/bin/python3"; then
    runner_exec python3 -m venv "$VENV_ROOT"
    log "Created runner venv at $VENV_ROOT"
  else
    log "Runner venv already exists at $VENV_ROOT"
  fi
  runner_exec "$VENV_ROOT/bin/pip" install -r "$requirements_root/requirements.txt"
  log "Installed Python dependencies into $VENV_ROOT"
}

install_wrapper() {
  mode_arg="${1:-$MODE}"
  target_base_root="${2:-$SMOKE_BASE_ROOT}"
  prepare_base_root_path "$target_base_root"
  write_wrapper "$(repo_root_for_mode "$mode_arg")" "$mode_arg" "$target_base_root"
  log "Installed wrapper at $INSTALL_PATH for $(repo_root_for_mode "$mode_arg") using $target_base_root"
}

install_sudoers() {
  if [ -z "$CALLER_USER" ]; then
    log "CALLER_USER is empty; set CALLER_USER before installing sudoers" >&2
    exit 1
  fi

  tmp_sudoers=$(mktemp)
  cat >"$tmp_sudoers" <<EOF
Cmnd_Alias CONTINUUM_SMOKE = $INSTALL_PATH *
Cmnd_Alias CONTINUUM_HOSTCTL = $HOSTCTL_PATH *
$CALLER_USER ALL=($RUNNER_USER) NOPASSWD: CONTINUUM_SMOKE
$CALLER_USER ALL=(root) NOPASSWD: CONTINUUM_HOSTCTL
EOF
  run_root install -m 0440 "$tmp_sudoers" "/etc/sudoers.d/${RUNNER_USER}-wrapper"
  run_root visudo -cf "/etc/sudoers.d/${RUNNER_USER}-wrapper"
  rm -f "$tmp_sudoers"
  log "Installed sudoers rules for $CALLER_USER via $INSTALL_PATH and $HOSTCTL_PATH"
}

verify_wrapper_target() {
  expected_repo_root=$1
  if [ ! -r "$INSTALL_PATH" ]; then
    log "Installed wrapper is not readable: $INSTALL_PATH" >&2
    exit 1
  fi

  wrapper_repo_root=$(awk -F= '/^REPO_ROOT=/{print $2; exit}' "$INSTALL_PATH")
  if [ "$wrapper_repo_root" != "$expected_repo_root" ]; then
    log "Installed wrapper points at $wrapper_repo_root but expected $expected_repo_root" >&2
    log "Refresh the host wrapper with: $0 install-wrapper ${MODE}" >&2
    exit 1
  fi

  if ! grep -q 'scripts/test/run_smoke_host.sh' "$INSTALL_PATH"; then
    log "Installed wrapper is not using the canonical repo smoke runner script" >&2
    exit 1
  fi

  wrapper_base_root=$(awk -F= '/^BASE_ROOT=/{print $2; exit}' "$INSTALL_PATH")
  validate_smoke_base_root "$wrapper_base_root"
  if ! runner_exec test -w "$wrapper_base_root"; then
    log "Installed wrapper smoke base root is not writable by $RUNNER_USER: $wrapper_base_root" >&2
    exit 1
  fi
}

verify_dedicated_repo_sync() {
  marker_path=$(sync_marker_path)
  if ! run_root_noninteractive test -r "$marker_path"; then
    log "Dedicated repo sync marker is missing: $marker_path" >&2
    log "Refresh the dedicated repo with: $0 sync-repo" >&2
    exit 1
  fi

  marker_source=$(
    run_root_noninteractive awk -F= '/^SYNCED_FROM=/{print $2; exit}' "$marker_path"
  )
  if [ -n "$marker_source" ] && [ "$marker_source" != "$LIVE_REPO_ROOT" ]; then
    log "Dedicated repo was last synced from $marker_source, not $LIVE_REPO_ROOT" >&2
    log "Refresh the dedicated repo with: $0 sync-repo" >&2
    exit 1
  fi

  for rel_path in $SYNC_PROBE_FILES; do
    live_path="$LIVE_REPO_ROOT/$rel_path"
    dedicated_path="$DEDICATED_REPO_ROOT/$rel_path"

    if [ ! -r "$live_path" ]; then
      log "Live repo probe file is unreadable: $live_path" >&2
      exit 1
    fi
    if ! run_root_noninteractive test -r "$dedicated_path"; then
      log "Dedicated repo probe file is unreadable: $dedicated_path" >&2
      exit 1
    fi

    live_cksum=$(cksum "$live_path" | awk '{print $1 ":" $2}')
    dedicated_cksum=$(
      run_root_noninteractive cksum "$dedicated_path" | awk '{print $1 ":" $2}'
    )
    if [ "$live_cksum" != "$dedicated_cksum" ]; then
      log "Dedicated repo drift detected for $rel_path" >&2
      log "Live repo checksum: $live_cksum" >&2
      log "Dedicated repo checksum: $dedicated_cksum" >&2
      log "Refresh the dedicated repo with: $0 sync-repo" >&2
      exit 1
    fi
  done
}

verify_hostctl_interface() {
  setup_script="$LIVE_REPO_ROOT/scripts/test/setup_agent_host.sh"
  if [ ! -r "$setup_script" ]; then
    log "Host setup script is unreadable: $setup_script" >&2
    exit 1
  fi
  if [ ! -r "$HOSTCTL_PATH" ]; then
    log "Installed maintenance helper is unreadable: $HOSTCTL_PATH" >&2
    exit 1
  fi

  source_version=$(awk -F= '/^HOSTCTL_INTERFACE_VERSION=/{gsub(/"/, "", $2); print $2; exit}' "$setup_script")
  if [ -z "$source_version" ]; then
    log "Host setup script does not declare HOSTCTL_INTERFACE_VERSION: $setup_script" >&2
    exit 1
  fi
  installed_version=$(awk -F= '/^HOSTCTL_INTERFACE_VERSION=/{gsub(/"/, "", $2); print $2; exit}' "$HOSTCTL_PATH")
  if [ -z "$installed_version" ]; then
    log "Installed maintenance helper does not declare HOSTCTL_INTERFACE_VERSION: $HOSTCTL_PATH" >&2
    exit 1
  fi

  if [ "$installed_version" != "$source_version" ]; then
    log "Installed maintenance helper is stale: interface $installed_version, expected $source_version" >&2
    log "Refresh the helper from the live checkout, then rerun verify:" >&2
    log "  $setup_script install-hostctl" >&2
    log "  sudo -n $HOSTCTL_PATH verify" >&2
    exit 1
  fi

  if ! grep -q 'prime-registry-cache)' "$HOSTCTL_PATH"; then
    log "Installed maintenance helper does not expose prime-registry-cache" >&2
    log "Refresh the helper from the live checkout with: $setup_script install-hostctl" >&2
    exit 1
  fi
}

verify() {
  mode_arg="${1:-$MODE}"
  repo_root=$(repo_root_for_mode "$mode_arg")

  require_cmd sudo
  require_cmd virsh

  log "Verifying maintenance helper interface"
  verify_hostctl_interface

  log "Verifying installed wrapper target"
  verify_wrapper_target "$repo_root"

  log "Verifying libvirt access"
  runner_exec virsh list --all

  log "Verifying /dev/kvm readability"
  runner_exec test -r /dev/kvm

  log "Verifying runner repo readability"
  runner_exec test -r "$repo_root/continuum.py"

  if [ "$mode_arg" = "dedicated" ] && [ "$READONLY_DEDICATED_REPO" = "1" ]; then
    log "Verifying dedicated repo is synced to the live checkout"
    verify_dedicated_repo_sync

    log "Verifying dedicated repo is not writable by $RUNNER_USER"
    if runner_exec test -w "$repo_root/continuum.py"; then
      log "Dedicated repo is unexpectedly writable by $RUNNER_USER" >&2
      exit 1
    fi
  fi

  log "Verifying wrapper prereqs"
  runner_exec "$INSTALL_PATH" check-prereqs
}

prime_registry_cache() {
  if [ "$#" -eq 0 ]; then
    log "Usage: $0 prime-registry-cache [--suite SUITE | --config CONFIG ...]" >&2
    exit 2
  fi
  if [ "$(id -u)" -ne 0 ]; then
    log "Run this helper via sudo, or run scripts/test/prime_local_registry_cache.py directly as a Docker-capable user." >&2
    exit 2
  fi

  require_cmd curl
  require_cmd docker

  repo_root=$(repo_root_for_mode "$MODE")
  if [ "$MODE" = "dedicated" ] && [ "$READONLY_DEDICATED_REPO" = "1" ]; then
    verify_dedicated_repo_sync
  fi

  if [ ! -x "$VENV_ROOT/bin/python3" ]; then
    log "Could not find Continuum smoke Python interpreter: $VENV_ROOT/bin/python3" >&2
    exit 2
  fi

  cd "$repo_root"
  PYTHONPATH=. "$VENV_ROOT/bin/python3" scripts/test/prime_local_registry_cache.py "$@"
}

install() {
  mode_arg="${1:-$MODE}"
  create_user
  case "$mode_arg" in
    dedicated)
      create_dedicated_repo
      sync_dedicated_repo
      ;;
    live)
      grant_live_repo_access
      ;;
    *)
      log "Unsupported install mode: $mode_arg" >&2
      exit 2
      ;;
  esac
  prepare_base_root
  install_host_prereqs
  create_venv "$mode_arg"
  install_wrapper "$mode_arg"
  install_hostctl
  install_sudoers
  verify "$mode_arg"
}

print_agent_command() {
  scenario="${1:-benchmark_k8s_resume}"
  printf 'sudo -n -u %s %s %s\n' "$RUNNER_USER" "$INSTALL_PATH" "$scenario"
}

is_installed_hostctl_command() {
  case "$1" in
    show-config|sync-repo|install-wrapper|verify|prime-registry-cache|print-agent-command)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

print_hostctl_command() {
  if [ "$#" -eq 0 ]; then
    set -- sync-repo
  fi

  if ! is_installed_hostctl_command "$1"; then
    log "Unsupported installed hostctl command for print-hostctl-command: $1" >&2
    if [ "$1" = "install-hostctl" ]; then
      log "Refresh the helper with: $LIVE_REPO_ROOT/scripts/test/setup_agent_host.sh install-hostctl" >&2
    fi
    return 2
  fi

  printf 'sudo -n %s' "$HOSTCTL_PATH"
  for arg in "$@"; do
    printf ' %s' "$arg"
  done
  printf '\n'
}

show_config() {
  marker_path=$(sync_marker_path)
  marker_dir=$(dirname "$marker_path")
  cat <<EOF
RUNNER_USER=$RUNNER_USER
CALLER_USER=$CALLER_USER
RUNNER_HOME=$RUNNER_HOME
SMOKE_BASE_ROOT=$SMOKE_BASE_ROOT
VENV_ROOT=$VENV_ROOT
INSTALL_PATH=$INSTALL_PATH
HOSTCTL_PATH=$HOSTCTL_PATH
LIVE_REPO_ROOT=$LIVE_REPO_ROOT
DEDICATED_REPO_ROOT=$DEDICATED_REPO_ROOT
MODE=$MODE
READONLY_DEDICATED_REPO=$READONLY_DEDICATED_REPO
HOSTCTL_INTERFACE_VERSION=$HOSTCTL_INTERFACE_VERSION
LIBVIRT_URI=$LIBVIRT_URI
QEMU_BRIDGE_NAME=$QEMU_BRIDGE_NAME
QEMU_BRIDGE_GATEWAY=$QEMU_BRIDGE_GATEWAY
DEDICATED_SYNC_MARKER=$marker_path
EOF

  if [ -r "$marker_path" ]; then
    printf 'DEDICATED_SYNC_MARKER_STATUS=present\n'
    cat "$marker_path"
  elif [ -x "$marker_dir" ] || [ -r "$marker_dir" ]; then
    printf 'DEDICATED_SYNC_MARKER_STATUS=missing\n'
  else
    printf 'DEDICATED_SYNC_MARKER_STATUS=unreadable\n'
  fi

  if [ -r "$INSTALL_PATH" ]; then
    wrapper_base_root=$(awk -F= '/^BASE_ROOT=/{print $2; exit}' "$INSTALL_PATH")
    if [ -n "$wrapper_base_root" ]; then
      printf 'INSTALLED_WRAPPER_BASE_ROOT=%s\n' "$wrapper_base_root"
    fi
  fi
}

cmd="${1:-}"

case "$cmd" in
  show-config)
    show_config
    ;;
  install)
    install "${2:-$MODE}"
    ;;
  sync-repo|sync-dedicated-repo)
    sync_dedicated_repo
    ;;
  verify)
    verify "${2:-$MODE}"
    ;;
  prime-registry-cache)
    shift
    prime_registry_cache "$@"
    ;;
  install-hostctl)
    install_hostctl
    ;;
  print-agent-command)
    print_agent_command "${2:-benchmark_k8s_resume}"
    ;;
  print-hostctl-command)
    shift
    print_hostctl_command "$@"
    ;;
  print-hostctl-script)
    emit_hostctl_script
    ;;
  create-user)
    create_user
    ;;
  grant-live-repo-access)
    grant_live_repo_access
    ;;
  create-dedicated-repo)
    create_dedicated_repo
    ;;
  prepare-base-root)
    prepare_base_root
    ;;
  install-host-prereqs)
    install_host_prereqs
    ;;
  create-venv)
    create_venv "${2:-$MODE}"
    ;;
  install-wrapper)
    install_wrapper "${2:-$MODE}" "${3:-$SMOKE_BASE_ROOT}"
    ;;
  install-sudoers)
    install_sudoers
    ;;
  all-live)
    install live
    ;;
  all-dedicated)
    install dedicated
    ;;
  ""|-h|--help|help)
    usage
    ;;
  *)
    log "Unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
