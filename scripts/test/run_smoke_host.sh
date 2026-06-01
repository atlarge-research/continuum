#!/bin/sh
set -eu
umask 027

SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
PATH=$SAFE_PATH
export PATH

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

invalid_name_pattern() {
  case "$1" in
    ""|/*|*..*|*/*|*';'*|*'&'*|*'|'*|*'`'*|*'$'*|*'\'*|*'<'*|*'>'*|*'('*|*')'*|*'{'*|*'}'*|*'['*|*']'*|*'!'*|*' '*|*'	'*)
      return 0
      ;;
    *)
      return 1
      ;;
  esac
}

validate_scenario_name() {
  scenario=$1
  if invalid_name_pattern "$scenario"; then
    echo "Invalid smoke scenario name: $scenario" >&2
    return 2
  fi
}

validate_debug_playbook_path() {
  playbook=$1
  case "$playbook" in
    playbooks/*.yml|playbooks/*.yaml)
      ;;
    *)
      echo "Debug playbook must be a repo-relative playbook path under playbooks/: $playbook" >&2
      return 2
      ;;
  esac
  case "$playbook" in
    /*|*..*|*';'*|*'&'*|*'|'*|*'`'*|*'$'*|*'\'*|*'<'*|*'>'*|*'('*|*')'*|*'{'*|*'}'*|*'['*|*']'*|*'!'*|*' '*|*'	'*)
      echo "Unsafe debug playbook path: $playbook" >&2
      return 2
      ;;
  esac
  if [ ! -f "$REPO_ROOT/$playbook" ]; then
    echo "Debug playbook does not exist: $playbook" >&2
    return 2
  fi
}

validate_prime_registry_args() {
  if [ "$#" -eq 0 ]; then
    echo "Usage: $0 prime-registry-cache [--check-only] [--suite SUITE | --config CONFIG ...]" >&2
    return 2
  fi

  mode=
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --check-only)
        shift
        ;;
      --suite)
        if [ "${mode:-}" = "config" ]; then
          echo "Cannot mix --suite and --config for prime-registry-cache" >&2
          return 2
        fi
        mode=suite
        shift
        if [ "$#" -eq 0 ]; then
          echo "Missing suite name after --suite" >&2
          return 2
        fi
        if invalid_name_pattern "$1"; then
          echo "Unsafe suite name for prime-registry-cache: $1" >&2
          return 2
        fi
        shift
        ;;
      --config)
        if [ "${mode:-}" = "suite" ]; then
          echo "Cannot mix --suite and --config for prime-registry-cache" >&2
          return 2
        fi
        mode=config
        shift
        if [ "$#" -eq 0 ]; then
          echo "Missing config path after --config" >&2
          return 2
        fi
        case "$1" in
          configs/experiments/*.yaml|configs/experiments/*.yml|configuration/tests/*.cfg)
            ;;
          *)
            echo "Unsupported config path for prime-registry-cache: $1" >&2
            return 2
            ;;
        esac
        case "$1" in
          /*|*..*|*';'*|*'&'*|*'|'*|*'`'*|*'$'*|*'\'*|*'<'*|*'>'*|*'('*|*')'*|*'{'*|*'}'*|*'['*|*']'*|*'!'*|*' '*|*'	'*)
            echo "Unsafe config path for prime-registry-cache: $1" >&2
            return 2
            ;;
        esac
        shift
        ;;
      *)
        echo "Unsupported prime-registry-cache argument: $1" >&2
        return 2
        ;;
    esac
  done
}

validate_check_prereqs_args() {
  CHECK_PREREQS_SUITE=smoke
  if [ "$#" -eq 0 ]; then
    return 0
  fi

  if [ "$#" -ne 2 ] || [ "$1" != "--suite" ]; then
    echo "Usage: $0 check-prereqs [--suite SUITE]" >&2
    return 2
  fi

  if invalid_name_pattern "$2"; then
    echo "Unsafe suite name for check-prereqs: $2" >&2
    return 2
  fi
  CHECK_PREREQS_SUITE=$2
}

retained_scenario_path() {
  case "$1" in
    infra_one_vm|software_k8s_two_vm|network_netperf_two_vm|benchmark_k8s_resume|network_validation|qemu_infra_parity|qemu_k8s_nobench_parity|qemu_k8s_image_parity|qemu_kubeedge_software_parity|qemu_kubeedge_image_parity|qemu_mist_software_parity|qemu_mist_image_parity|qemu_endpoint_software_parity|qemu_endpoint_image_parity|qemu_openfaas_software_parity|qemu_openfaas_image_parity|prereqs)
      printf '%s/%s\n' "$BASE_ROOT" "$1"
      ;;
    benchmark_k8s_resume_infra|benchmark_k8s_resume_software|benchmark_k8s_resume_application)
      printf '%s/benchmark_k8s_resume\n' "$BASE_ROOT"
      ;;
    *)
      return 1
      ;;
  esac
}

print_retained_scenarios() {
  cat <<EOF
infra_one_vm
software_k8s_two_vm
network_netperf_two_vm
benchmark_k8s_resume
network_validation
qemu_infra_parity
qemu_k8s_nobench_parity
qemu_k8s_image_parity
qemu_kubeedge_software_parity
qemu_kubeedge_image_parity
qemu_mist_software_parity
qemu_mist_image_parity
qemu_endpoint_software_parity
qemu_endpoint_image_parity
qemu_openfaas_software_parity
qemu_openfaas_image_parity
prereqs
EOF
}

storage_report() {
  printf 'SMOKE_BASE_ROOT=%s\n' "$BASE_ROOT"
  if [ ! -d "$BASE_ROOT" ]; then
    echo "No retained smoke state found."
    return 0
  fi

  echo "Retained scenario sizes:"
  find "$BASE_ROOT" -mindepth 1 -maxdepth 1 -type d -exec du -sh {} + | sort -h
  echo "Total retained smoke state:"
  du -sh "$BASE_ROOT"
}

prune_scenario() {
  scenario="${1:-}"
  confirmation="${2:-}"

  if [ -z "$scenario" ]; then
    echo "Usage: $0 prune-scenario <scenario> --yes-delete-retained-state" >&2
    echo "Known retained scenarios:" >&2
    print_retained_scenarios >&2
    return 2
  fi

  validate_scenario_name "$scenario" || return $?

  if ! scenario_path=$(retained_scenario_path "$scenario"); then
    echo "Unsupported retained scenario for pruning: $scenario" >&2
    echo "Known retained scenarios:" >&2
    print_retained_scenarios >&2
    return 2
  fi

  case "$scenario_path" in
    "$BASE_ROOT"/*)
      ;;
    *)
      echo "Refusing to prune path outside smoke base root: $scenario_path" >&2
      return 1
      ;;
  esac

  if [ "$confirmation" != "--yes-delete-retained-state" ]; then
    echo "Refusing to delete retained state without explicit confirmation." >&2
    echo "Would delete: $scenario_path" >&2
    echo "Retry with: $0 prune-scenario $scenario --yes-delete-retained-state" >&2
    return 2
  fi

  if [ ! -e "$scenario_path" ]; then
    echo "No retained state exists for scenario: $scenario"
    echo "Path: $scenario_path"
    return 0
  fi

  rm -rf "$scenario_path"
  echo "Deleted retained state for scenario: $scenario"
  echo "Path: $scenario_path"
}

if [ "$SCENARIO" = "debug-playbook" ]; then
  if [ "$#" -lt 3 ]; then
    echo "Usage: $0 debug-playbook <scenario> <playbook> [ansible args...]" >&2
    exit 2
  fi
  RUN_MODE="debug_playbook"
  SCENARIO=$2
  DEBUG_PLAYBOOK=$3
  validate_scenario_name "$SCENARIO"
  validate_debug_playbook_path "$DEBUG_PLAYBOOK"
  shift 3
fi

validate_scenario_name "$SCENARIO"

if [ "$SCENARIO" = "storage-report" ]; then
  storage_report
  exit 0
fi

if [ "$SCENARIO" = "prune-scenario" ]; then
  shift
  prune_scenario "$@"
  exit $?
fi

if [ "$SCENARIO" = "prime-registry-cache" ]; then
  shift
  validate_prime_registry_args "$@"
  set -- prime-registry-cache "$@"
fi

if [ "$SCENARIO" = "check-prereqs" ]; then
  shift
  validate_check_prereqs_args "$@"
  set -- check-prereqs "$@"
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

set_suite_scenario() {
  suite_name=$1
  scenario_path=$2
  if [ "$RUN_MODE" != "debug_playbook" ]; then
    RUN_MODE="suite"
    SUITE="$suite_name"
  fi
  BASE_PATH="$BASE_ROOT/$scenario_path"
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
    set_suite_scenario benchmark_smoke benchmark_k8s_resume
    ;;
  network_validation)
    set_suite_scenario network_validation network_validation
    ;;
  qemu_infra_parity)
    set_suite_scenario qemu_infra_parity qemu_infra_parity
    ;;
  qemu_k8s_nobench_parity)
    set_suite_scenario qemu_k8s_nobench_parity qemu_k8s_nobench_parity
    ;;
  qemu_k8s_image_parity)
    set_suite_scenario qemu_k8s_image_parity qemu_k8s_image_parity
    ;;
  qemu_kubeedge_software_parity)
    set_suite_scenario qemu_kubeedge_software_parity qemu_kubeedge_software_parity
    ;;
  qemu_kubeedge_image_parity)
    set_suite_scenario qemu_kubeedge_image_parity qemu_kubeedge_image_parity
    ;;
  qemu_mist_software_parity)
    set_suite_scenario qemu_mist_software_parity qemu_mist_software_parity
    ;;
  qemu_mist_image_parity)
    set_suite_scenario qemu_mist_image_parity qemu_mist_image_parity
    ;;
  qemu_endpoint_software_parity)
    set_suite_scenario qemu_endpoint_software_parity qemu_endpoint_software_parity
    ;;
  qemu_endpoint_image_parity)
    set_suite_scenario qemu_endpoint_image_parity qemu_endpoint_image_parity
    ;;
  qemu_openfaas_software_parity)
    set_suite_scenario qemu_openfaas_software_parity qemu_openfaas_software_parity
    ;;
  qemu_openfaas_image_parity)
    set_suite_scenario qemu_openfaas_image_parity qemu_openfaas_image_parity
    ;;
  release-artifact-audit)
    BASE_PATH="$BASE_ROOT/prereqs"
    CONTINUUM_HOME="$BASE_PATH/.continuum"
    MPLCONFIGDIR_PATH="$CONTINUUM_HOME/mplconfig"
    XDG_CACHE_HOME_PATH="$BASE_ROOT/.cache"
    mkdir -p "$BASE_PATH" "$CONTINUUM_HOME" "$MPLCONFIGDIR_PATH" "$XDG_CACHE_HOME_PATH"
    chmod 0750 "$BASE_PATH" "$CONTINUUM_HOME" "$MPLCONFIGDIR_PATH" "$XDG_CACHE_HOME_PATH"
    cd "$REPO_ROOT"
    exec env -i \
      HOME="${HOME:-/home/continuum-smoke}" \
      PATH="$VENV_BIN:$SAFE_PATH" \
      PYTHONPATH=. \
      PYTHONDONTWRITEBYTECODE=1 \
      XDG_CACHE_HOME="$XDG_CACHE_HOME_PATH" \
      MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
      CONTINUUM_RELEASE_AUDIT_ROOT="${CONTINUUM_RELEASE_AUDIT_ROOT:-$REPO_ROOT}" \
      CONTINUUM_SMOKE_BASE_ROOT="$BASE_ROOT" \
      CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
      "$PYTHON_BIN" scripts/test/check_release_evidence_artifacts.py
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
      PATH="$VENV_BIN:$SAFE_PATH" \
      PYTHONPATH=. \
      PYTHONDONTWRITEBYTECODE=1 \
      XDG_CACHE_HOME="$BASE_ROOT/.cache" \
      MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
      LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
      CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      CONTINUUM_TEST_RESULTS_DIR="$TEST_RESULTS_DIR" \
      ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
      ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
      "$PYTHON_BIN" scripts/test/run_tests.py --suite "$CHECK_PREREQS_SUITE" --check-prereqs
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
      PATH="$VENV_BIN:$SAFE_PATH" \
      PYTHONPATH=. \
      PYTHONDONTWRITEBYTECODE=1 \
      XDG_CACHE_HOME="$BASE_ROOT/.cache" \
      MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
      LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
      CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      CONTINUUM_TEST_RESULTS_DIR="$TEST_RESULTS_DIR" \
      ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
      ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
      "$PYTHON_BIN" scripts/test/run_tests.py --list-suites
    ;;
  prime-registry-cache)
    shift
    validate_prime_registry_args "$@"
    BASE_PATH="$BASE_ROOT/prereqs"
    CONTINUUM_HOME="$BASE_PATH/.continuum"
    TEST_RESULTS_DIR="$CONTINUUM_HOME/test_results"
    MPLCONFIGDIR_PATH="$CONTINUUM_HOME/mplconfig"
    XDG_CACHE_HOME_PATH="$BASE_ROOT/.cache"
    mkdir -p "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH" \
      "$XDG_CACHE_HOME_PATH"
    chmod 0750 "$BASE_PATH" "$CONTINUUM_HOME" "$TEST_RESULTS_DIR" "$MPLCONFIGDIR_PATH" \
      "$XDG_CACHE_HOME_PATH"
    cd "$REPO_ROOT"
    exec env -i \
      HOME="${HOME:-/home/continuum-smoke}" \
      PATH="$VENV_BIN:$SAFE_PATH" \
      PYTHONPATH=. \
      PYTHONDONTWRITEBYTECODE=1 \
      XDG_CACHE_HOME="$XDG_CACHE_HOME_PATH" \
      MPLCONFIGDIR="$MPLCONFIGDIR_PATH" \
      LIBVIRT_DEFAULT_URI="$LIBVIRT_URI" \
      CONTINUUM_SMOKE_PYTHON="$PYTHON_BIN" \
      CONTINUUM_TEST_RESULTS_DIR="$TEST_RESULTS_DIR" \
      ${QEMU_BRIDGE_NAME:+CONTINUUM_QEMU_BRIDGE_NAME="$QEMU_BRIDGE_NAME"} \
      ${QEMU_BRIDGE_GATEWAY:+CONTINUUM_QEMU_BRIDGE_GATEWAY="$QEMU_BRIDGE_GATEWAY"} \
      "$PYTHON_BIN" scripts/test/prime_local_registry_cache.py "$@"
    ;;
  *)
    echo "Unsupported smoke scenario: $SCENARIO" >&2
    echo "Allowed values: phase_smoke_matrix, operational_regression, infra_one_vm, software_k8s_two_vm, network_netperf_two_vm, network_validation, qemu_infra_parity, qemu_k8s_nobench_parity, qemu_k8s_image_parity, qemu_kubeedge_software_parity, qemu_kubeedge_image_parity, qemu_mist_software_parity, qemu_mist_image_parity, qemu_endpoint_software_parity, qemu_endpoint_image_parity, qemu_openfaas_software_parity, qemu_openfaas_image_parity, benchmark_k8s_resume_infra, benchmark_k8s_resume_software, benchmark_k8s_resume_application, benchmark_k8s_resume, release-artifact-audit, check-prereqs, list-suites, prime-registry-cache, debug-playbook, storage-report, prune-scenario" >&2
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
  PLAYBOOK_PATH="$REPO_ROOT/$DEBUG_PLAYBOOK"

  exec env -i \
    HOME="${HOME:-/home/continuum-smoke}" \
    PATH="$VENV_BIN:$SAFE_PATH" \
    PYTHONPATH=. \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME="$BASE_ROOT/.cache" \
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
    PATH="$VENV_BIN:$SAFE_PATH" \
    PYTHONPATH=. \
    PYTHONDONTWRITEBYTECODE=1 \
    XDG_CACHE_HOME="$BASE_ROOT/.cache" \
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
  PATH="$VENV_BIN:$SAFE_PATH" \
  PYTHONPATH=. \
  PYTHONDONTWRITEBYTECODE=1 \
  XDG_CACHE_HOME="$BASE_ROOT/.cache" \
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
