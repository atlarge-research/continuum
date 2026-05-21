#!/bin/sh
set -eu
umask 022

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)

if [ -n "${CONTINUUM_REPO_ROOT:-}" ]; then
  REPO_ROOT=$CONTINUUM_REPO_ROOT
else
  REPO_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
fi

if [ ! -f "$REPO_ROOT/continuum.py" ] || [ ! -f "$REPO_ROOT/scripts/test/run_tests.py" ]; then
  echo "Could not resolve Continuum repository root." >&2
  echo "Set CONTINUUM_REPO_ROOT to the checkout path if this wrapper is installed outside the repo." >&2
  exit 2
fi

SCENARIO="${1:-infra_one_vm}"
BASE_ROOT="${CONTINUUM_SMOKE_BASE_ROOT:-${HOME:-/home/continuum-smoke}/continuum_smoke}"
PYTHON_BIN="${CONTINUUM_SMOKE_PYTHON:-${HOME:-/home/continuum-smoke}/venvs/continuum/bin/python3}"
VENV_BIN=$(dirname -- "$PYTHON_BIN")
ANSIBLE_PLAYBOOK_BIN="${CONTINUUM_SMOKE_ANSIBLE_PLAYBOOK:-$VENV_BIN/ansible-playbook}"
LIBVIRT_URI="${LIBVIRT_DEFAULT_URI:-qemu:///system}"
QEMU_BRIDGE_NAME="${CONTINUUM_QEMU_BRIDGE_NAME:-}"
QEMU_BRIDGE_GATEWAY="${CONTINUUM_QEMU_BRIDGE_GATEWAY:-}"
RUN_MODE="config"
REMOTE_TMP_TAG="${CONTINUUM_SMOKE_REMOTE_TMP_TAG:-$(basename -- "${HOME:-/home/continuum-smoke}")}"
DEBUG_PLAYBOOK=""

if [ "$SCENARIO" = "debug-playbook" ]; then
  if [ "$#" -lt 3 ]; then
    echo "Usage: $0 debug-playbook <scenario> <playbook> [ansible args...]" >&2
    exit 2
  fi
  RUN_MODE="debug_playbook"
  SCENARIO=$2
  DEBUG_PLAYBOOK=$3
  shift 3
fi

if [ ! -x "$PYTHON_BIN" ]; then
  echo "Could not find Continuum smoke Python interpreter: $PYTHON_BIN" >&2
  echo "Create the dedicated runner venv first." >&2
  exit 2
fi

if [ "$RUN_MODE" = "debug_playbook" ] && [ ! -x "$ANSIBLE_PLAYBOOK_BIN" ]; then
  echo "Could not find ansible-playbook in the runner venv: $ANSIBLE_PLAYBOOK_BIN" >&2
  echo "Create or refresh the dedicated runner venv first." >&2
  exit 2
fi

run_child_scenarios() {
  for child_scenario in "$@"; do
    printf '\n=== Running smoke scenario: %s ===\n' "$child_scenario"
    sh "$0" "$child_scenario"
  done
}

case "$SCENARIO" in
  phase_smoke_matrix)
    run_child_scenarios infra_one_vm software_k8s_two_vm network_netperf_two_vm
    exit 0
    ;;
  operational_regression)
    run_child_scenarios phase_smoke_matrix benchmark_k8s_resume
    exit 0
    ;;
  infra_one_vm)
    CONFIG="configs/experiments/smoke/infra_one_vm.yaml"
    BASE_PATH="$BASE_ROOT/infra_one_vm"
    ;;
  software_k8s_two_vm)
    CONFIG="configs/experiments/smoke/software_k8s_two_vm.yaml"
    BASE_PATH="$BASE_ROOT/software_k8s_two_vm"
    ;;
  network_netperf_two_vm)
    CONFIG="configs/experiments/smoke/network_netperf_two_vm.yaml"
    BASE_PATH="$BASE_ROOT/network_netperf_two_vm"
    ;;
  benchmark_k8s_resume_infra)
    CONFIG="configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml"
    BASE_PATH="$BASE_ROOT/benchmark_k8s_resume"
    ;;
  benchmark_k8s_resume_software)
    CONFIG="configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml"
    BASE_PATH="$BASE_ROOT/benchmark_k8s_resume"
    ;;
  benchmark_k8s_resume_application)
    CONFIG="configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml"
    BASE_PATH="$BASE_ROOT/benchmark_k8s_resume"
    ;;
  benchmark_k8s_resume)
    RUN_MODE="suite"
    SUITE="benchmark_smoke"
    BASE_PATH="$BASE_ROOT/benchmark_k8s_resume"
    ;;
  check-prereqs)
    BASE_PATH="$BASE_ROOT/prereqs"
    CONTINUUM_HOME="$BASE_PATH/.continuum"
    TEST_RESULTS_DIR="$CONTINUUM_HOME/test_results"
    MPLCONFIGDIR_PATH="$CONTINUUM_HOME/mplconfig"
    mkdir -p "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH"
    chmod 0755 "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH"
    cd "$REPO_ROOT"
    exec env -i \
      HOME="${HOME:-/home/continuum-smoke}" \
      PATH="$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
      PYTHONPATH=. \
      PYTHONDONTWRITEBYTECODE=1 \
      MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
      LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
      CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      CONTINUUM_TEST_RESULTS_DIR="$TEST_RESULTS_DIR" \
      ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
      ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
      "$PYTHON_BIN" scripts/test/run_tests.py --suite smoke --check-prereqs
    ;;
  list-suites)
    BASE_PATH="$BASE_ROOT/prereqs"
    CONTINUUM_HOME="$BASE_PATH/.continuum"
    TEST_RESULTS_DIR="$CONTINUUM_HOME/test_results"
    MPLCONFIGDIR_PATH="$CONTINUUM_HOME/mplconfig"
    mkdir -p "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH"
    chmod 0755 "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH"
    cd "$REPO_ROOT"
    exec env -i \
      HOME="${HOME:-/home/continuum-smoke}" \
      PATH="$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
      PYTHONPATH=. \
      PYTHONDONTWRITEBYTECODE=1 \
      MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
      LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
      CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      CONTINUUM_TEST_RESULTS_DIR="$TEST_RESULTS_DIR" \
      ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
      ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
      "$PYTHON_BIN" scripts/test/run_tests.py --list-suites
    ;;
  *)
    echo "Unsupported smoke scenario: $SCENARIO" >&2
    echo "Allowed values: phase_smoke_matrix, operational_regression, infra_one_vm, software_k8s_two_vm, network_netperf_two_vm, benchmark_k8s_resume_infra, benchmark_k8s_resume_software, benchmark_k8s_resume_application, benchmark_k8s_resume, check-prereqs, list-suites, debug-playbook" >&2
    exit 2
    ;;
esac

CONTINUUM_HOME="$BASE_PATH/.continuum"
TEST_RESULTS_DIR="$CONTINUUM_HOME/test_results"
MPLCONFIGDIR_PATH="$CONTINUUM_HOME/mplconfig"
ANSIBLE_LOCAL_TEMP_PATH="$CONTINUUM_HOME/ansible/tmp"
ANSIBLE_REMOTE_TMP_PATH="~/.continuum-ansible-$REMOTE_TMP_TAG/tmp"
mkdir -p "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH" \
  "$CONTINUUM_HOME/ansible" "$ANSIBLE_LOCAL_TEMP_PATH"
chmod 0755 "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH" \
  "$CONTINUUM_HOME/ansible" "$ANSIBLE_LOCAL_TEMP_PATH"

cd "$REPO_ROOT"
if [ "$RUN_MODE" = "debug_playbook" ]; then
  case "$DEBUG_PLAYBOOK" in
    /*)
      PLAYBOOK_PATH=$DEBUG_PLAYBOOK
      ;;
    *)
      PLAYBOOK_PATH="$REPO_ROOT/$DEBUG_PLAYBOOK"
      ;;
  esac

  exec env -i \
    HOME="${HOME:-/home/continuum-smoke}" \
    PATH="$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    PYTHONPATH=. \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
    ANSIBLE_CONFIG="$REPO_ROOT/ansible.cfg" \
    ANSIBLE_LOCAL_TEMP="$ANSIBLE_LOCAL_TEMP_PATH" \
    ANSIBLE_REMOTE_TMP="$ANSIBLE_REMOTE_TMP_PATH" \
    LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
    ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
    ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
    "$ANSIBLE_PLAYBOOK_BIN" \
      -i "$CONTINUUM_HOME/inventory_vms" \
      "$PLAYBOOK_PATH" \
      -vvv \
      "$@"
fi

if [ "$RUN_MODE" = "suite" ]; then
  exec env -i \
    HOME="${HOME:-/home/continuum-smoke}" \
    PATH="$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    PYTHONPATH=. \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
    CONTINUUM_SMOKE_BASE_ROOT="$BASE_ROOT" \
    CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
    CONTINUUM_TEST_RESULTS_DIR="$TEST_RESULTS_DIR" \
    LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
    ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
    ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
    "$PYTHON_BIN" scripts/test/run_tests.py \
      --suite "$SUITE" \
      --base-path "$BASE_PATH"
fi

exec env -i \
  HOME="${HOME:-/home/continuum-smoke}" \
  PATH="$VENV_BIN:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
  PYTHONPATH=. \
  PYTHONDONTWRITEBYTECODE=1 \
  MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
  CONTINUUM_SMOKE_BASE_ROOT="$BASE_ROOT" \
  CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
  CONTINUUM_TEST_RESULTS_DIR="$TEST_RESULTS_DIR" \
  LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
  ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
  ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
  "$PYTHON_BIN" scripts/test/run_tests.py \
    --config "$CONFIG" \
    --base-path "$BASE_PATH"
