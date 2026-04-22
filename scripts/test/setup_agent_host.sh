#!/bin/sh
set -eu

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)

RUNNER_USER="${RUNNER_USER:-continuum-smoke}"
CALLER_USER="${CALLER_USER:-${SUDO_USER:-${USER:-}}}"
INSTALL_PATH="${INSTALL_PATH:-/usr/local/bin/run-continuum-smoke}"
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

usage() {
  cat <<EOF
Usage:
  $0 show-config
  $0 install [dedicated|live]
  $0 sync-repo
  $0 verify
  $0 print-agent-command [scenario]

Compatibility commands:
  $0 create-user
  $0 grant-live-repo-access
  $0 create-dedicated-repo
  $0 sync-dedicated-repo
  $0 prepare-base-root
  $0 install-host-prereqs
  $0 create-venv [dedicated|live]
  $0 install-wrapper [dedicated|live]
  $0 install-sudoers
  $0 all-live
  $0 all-dedicated

Canonical setup:
  $0 install

Environment overrides:
  RUNNER_USER             default: $RUNNER_USER
  CALLER_USER             default: $CALLER_USER
  INSTALL_PATH            default: $INSTALL_PATH
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

write_wrapper() {
  wrapper_repo_root=$1

  run_root install -d -m 0755 "$(dirname "$INSTALL_PATH")"
  tmp_wrapper=$(mktemp)
  cat >"$tmp_wrapper" <<EOF
#!/bin/sh
set -eu
umask 022

REPO_ROOT=$wrapper_repo_root
RUNNER_HOME=$RUNNER_HOME
BASE_ROOT=$SMOKE_BASE_ROOT
PYTHON_BIN=$VENV_ROOT/bin/python3
VENV_BIN=\$(dirname "\$PYTHON_BIN")
LIBVIRT_URI=$LIBVIRT_URI
QEMU_BRIDGE_NAME=$QEMU_BRIDGE_NAME
QEMU_BRIDGE_GATEWAY=$QEMU_BRIDGE_GATEWAY
SCENARIO="\${1:-infra_one_vm}"
RUN_MODE="config"

if [ ! -x "\$PYTHON_BIN" ]; then
  echo "Could not find Continuum smoke Python interpreter: \$PYTHON_BIN" >&2
  echo "Run the host setup install step first." >&2
  exit 2
fi

case "\$SCENARIO" in
  infra_one_vm)
    CONFIG="configs/experiments/smoke/infra_one_vm.yaml"
    BASE_PATH="\$BASE_ROOT/infra_one_vm"
    ;;
  software_k8s_two_vm)
    CONFIG="configs/experiments/smoke/software_k8s_two_vm.yaml"
    BASE_PATH="\$BASE_ROOT/software_k8s_two_vm"
    ;;
  network_netperf_two_vm)
    CONFIG="configs/experiments/smoke/network_netperf_two_vm.yaml"
    BASE_PATH="\$BASE_ROOT/network_netperf_two_vm"
    ;;
  benchmark_k8s_resume_infra)
    CONFIG="configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml"
    BASE_PATH="\$BASE_ROOT/benchmark_k8s_resume"
    ;;
  benchmark_k8s_resume_software)
    CONFIG="configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml"
    BASE_PATH="\$BASE_ROOT/benchmark_k8s_resume"
    ;;
  benchmark_k8s_resume_application)
    CONFIG="configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml"
    BASE_PATH="\$BASE_ROOT/benchmark_k8s_resume"
    ;;
  benchmark_k8s_resume)
    RUN_MODE="suite"
    SUITE="benchmark_smoke"
    BASE_PATH="\$BASE_ROOT/benchmark_k8s_resume"
    ;;
  check-prereqs)
    BASE_PATH="\$BASE_ROOT/prereqs"
    ;;
  list-suites)
    BASE_PATH="\$BASE_ROOT/prereqs"
    ;;
  *)
    echo "Unsupported smoke scenario: \$SCENARIO" >&2
    echo "Allowed values: infra_one_vm, software_k8s_two_vm, network_netperf_two_vm, benchmark_k8s_resume_infra, benchmark_k8s_resume_software, benchmark_k8s_resume_application, benchmark_k8s_resume, check-prereqs, list-suites" >&2
    exit 2
    ;;
esac

CONTINUUM_HOME="\$BASE_PATH/.continuum"
TEST_RESULTS_DIR="\$CONTINUUM_HOME/test_results"
MPLCONFIGDIR_PATH="\$CONTINUUM_HOME/mplconfig"
mkdir -p "\$BASE_PATH" "\$CONTINUUM_HOME" "\$TEST_RESULTS_DIR" "\$MPLCONFIGDIR_PATH"
chmod 0755 "\$BASE_PATH" "\$CONTINUUM_HOME" "\$TEST_RESULTS_DIR" "\$MPLCONFIGDIR_PATH"

cd "\$REPO_ROOT"
if [ "\$SCENARIO" = "check-prereqs" ]; then
  exec env -i \\
    HOME=\$RUNNER_HOME \\
    PATH=\$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \\
    PYTHONPATH=. \\
    PYTHONDONTWRITEBYTECODE=1 \\
    MPLCONFIGDIR="\$MPLCONFIGDIR_PATH" \\
    CONTINUUM_SMOKE_PYTHON="\$PYTHON_BIN" \\
    CONTINUUM_TEST_RESULTS_DIR="\$TEST_RESULTS_DIR" \\
    LIBVIRT_DEFAULT_URI="\$LIBVIRT_URI" \\
    \${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME=\$QEMU_BRIDGE_NAME} \\
    \${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY=\$QEMU_BRIDGE_GATEWAY} \\
    "\$PYTHON_BIN" scripts/test/run_tests.py --suite smoke --check-prereqs
fi

if [ "\$SCENARIO" = "list-suites" ]; then
  exec env -i \\
    HOME=\$RUNNER_HOME \\
    PATH=\$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \\
    PYTHONPATH=. \\
    PYTHONDONTWRITEBYTECODE=1 \\
    MPLCONFIGDIR="\$MPLCONFIGDIR_PATH" \\
    CONTINUUM_SMOKE_PYTHON="\$PYTHON_BIN" \\
    CONTINUUM_TEST_RESULTS_DIR="\$TEST_RESULTS_DIR" \\
    LIBVIRT_DEFAULT_URI="\$LIBVIRT_URI" \\
    \${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME=\$QEMU_BRIDGE_NAME} \\
    \${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY=\$QEMU_BRIDGE_GATEWAY} \\
    "\$PYTHON_BIN" scripts/test/run_tests.py --list-suites
fi

if [ "\$RUN_MODE" = "suite" ]; then
  exec env -i \\
    HOME=\$RUNNER_HOME \\
    PATH=\$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \\
    PYTHONPATH=. \\
    PYTHONDONTWRITEBYTECODE=1 \\
    MPLCONFIGDIR="\$MPLCONFIGDIR_PATH" \\
    CONTINUUM_SMOKE_BASE_ROOT="\$BASE_ROOT" \\
    CONTINUUM_SMOKE_PYTHON="\$PYTHON_BIN" \\
    CONTINUUM_TEST_RESULTS_DIR="\$TEST_RESULTS_DIR" \\
    LIBVIRT_DEFAULT_URI="\$LIBVIRT_URI" \\
    \${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME=\$QEMU_BRIDGE_NAME} \\
    \${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY=\$QEMU_BRIDGE_GATEWAY} \\
    "\$PYTHON_BIN" scripts/test/run_tests.py \\
      --suite "\$SUITE" \\
      --base-path "\$BASE_PATH"
fi

exec env -i \\
  HOME=\$RUNNER_HOME \\
  PATH=\$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \\
  PYTHONPATH=. \\
  PYTHONDONTWRITEBYTECODE=1 \\
  MPLCONFIGDIR="\$MPLCONFIGDIR_PATH" \\
  CONTINUUM_SMOKE_BASE_ROOT="\$BASE_ROOT" \\
  CONTINUUM_SMOKE_PYTHON="\$PYTHON_BIN" \\
  CONTINUUM_TEST_RESULTS_DIR="\$TEST_RESULTS_DIR" \\
  LIBVIRT_DEFAULT_URI="\$LIBVIRT_URI" \\
  \${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME=\$QEMU_BRIDGE_NAME} \\
  \${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY=\$QEMU_BRIDGE_GATEWAY} \\
  "\$PYTHON_BIN" scripts/test/run_tests.py \\
    --config "\$CONFIG" \\
    --base-path "\$BASE_PATH"
EOF
  run_root install -m 0755 "$tmp_wrapper" "$INSTALL_PATH"
  run_root chown root:root "$INSTALL_PATH"
  rm -f "$tmp_wrapper"
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
}

prepare_base_root() {
  run_root install -d -o "$RUNNER_USER" -g "$RUNNER_USER" -m 0755 "$SMOKE_BASE_ROOT"
  log "Prepared smoke base root at $SMOKE_BASE_ROOT"
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
  write_wrapper "$(repo_root_for_mode "$mode_arg")"
  log "Installed wrapper at $INSTALL_PATH for $(repo_root_for_mode "$mode_arg")"
}

install_sudoers() {
  if [ -z "$CALLER_USER" ]; then
    log "CALLER_USER is empty; set CALLER_USER before installing sudoers" >&2
    exit 1
  fi

  tmp_sudoers=$(mktemp)
  cat >"$tmp_sudoers" <<EOF
Cmnd_Alias CONTINUUM_SMOKE = $INSTALL_PATH *
$CALLER_USER ALL=($RUNNER_USER) NOPASSWD: CONTINUUM_SMOKE
EOF
  run_root install -m 0440 "$tmp_sudoers" "/etc/sudoers.d/${RUNNER_USER}-wrapper"
  run_root visudo -cf "/etc/sudoers.d/${RUNNER_USER}-wrapper"
  rm -f "$tmp_sudoers"
  log "Installed sudoers rule for $CALLER_USER -> $RUNNER_USER via $INSTALL_PATH"
}

verify() {
  mode_arg="${1:-$MODE}"
  repo_root=$(repo_root_for_mode "$mode_arg")

  require_cmd sudo
  require_cmd virsh

  log "Verifying libvirt access"
  runner_exec virsh list --all

  log "Verifying /dev/kvm readability"
  runner_exec test -r /dev/kvm

  log "Verifying runner repo readability"
  runner_exec test -r "$repo_root/continuum.py"

  if [ "$mode_arg" = "dedicated" ] && [ "$READONLY_DEDICATED_REPO" = "1" ]; then
    log "Verifying dedicated repo is not writable by $RUNNER_USER"
    if runner_exec test -w "$repo_root/continuum.py"; then
      log "Dedicated repo is unexpectedly writable by $RUNNER_USER" >&2
      exit 1
    fi
  fi

  log "Verifying wrapper prereqs"
  runner_exec "$INSTALL_PATH" check-prereqs
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
  install_sudoers
  verify "$mode_arg"
}

print_agent_command() {
  scenario="${1:-benchmark_k8s_resume}"
  printf 'sudo -n -u %s %s %s\n' "$RUNNER_USER" "$INSTALL_PATH" "$scenario"
}

show_config() {
  cat <<EOF
RUNNER_USER=$RUNNER_USER
CALLER_USER=$CALLER_USER
RUNNER_HOME=$RUNNER_HOME
SMOKE_BASE_ROOT=$SMOKE_BASE_ROOT
VENV_ROOT=$VENV_ROOT
INSTALL_PATH=$INSTALL_PATH
LIVE_REPO_ROOT=$LIVE_REPO_ROOT
DEDICATED_REPO_ROOT=$DEDICATED_REPO_ROOT
MODE=$MODE
READONLY_DEDICATED_REPO=$READONLY_DEDICATED_REPO
LIBVIRT_URI=$LIBVIRT_URI
QEMU_BRIDGE_NAME=$QEMU_BRIDGE_NAME
QEMU_BRIDGE_GATEWAY=$QEMU_BRIDGE_GATEWAY
EOF
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
  print-agent-command)
    print_agent_command "${2:-benchmark_k8s_resume}"
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
    install_wrapper "${2:-$MODE}"
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
