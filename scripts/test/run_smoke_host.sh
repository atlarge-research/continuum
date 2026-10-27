#!/bin/sh
set -eu
umask 027

SAFE_PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
PATH=$SAFE_PATH
export PATH

[ "$(id -u)" -ne 0 ] || { echo "Run as a normal user, not root." >&2; exit 2; }
case "${HOME:-}" in
  /*) ;;
  *) echo "HOME must be an existing canonical absolute directory." >&2; exit 2 ;;
esac
if [ "$HOME" = / ] || [ ! -d "$HOME" ] || [ "$(realpath -- "$HOME")" != "$HOME" ]; then
  echo "HOME must be an existing canonical absolute directory, not /." >&2
  exit 2
fi

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
BASE_ROOT="${CONTINUUM_SMOKE_BASE_ROOT:-$HOME/continuum_smoke}"
PYTHON_BIN="${CONTINUUM_SMOKE_PYTHON:-$HOME/venvs/continuum/bin/python3}"
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
VENV_BIN=$(dirname -- "$PYTHON_BIN")
ANSIBLE_PLAYBOOK_BIN="${CONTINUUM_SMOKE_ANSIBLE_PLAYBOOK:-$VENV_BIN/ansible-playbook}"
LIBVIRT_URI="${LIBVIRT_DEFAULT_URI:-qemu:///system}"
QEMU_BRIDGE_NAME="${CONTINUUM_QEMU_BRIDGE_NAME:-}"
QEMU_BRIDGE_GATEWAY="${CONTINUUM_QEMU_BRIDGE_GATEWAY:-}"
RUN_MODE="config"
REMOTE_TMP_TAG="${CONTINUUM_SMOKE_REMOTE_TMP_TAG:-$(basename -- "$HOME")}"
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
    infra_one_vm|software_k8s_two_vm|network_netperf_two_vm|benchmark_k8s_resume|network_validation|qemu_infra_parity|qemu_k8s_nobench_parity|qemu_k8s_image_parity|qemu_kubeedge_software_parity|qemu_kubeedge_image_parity|qemu_mist_software_parity|qemu_mist_image_parity|qemu_endpoint_software_parity|qemu_endpoint_image_parity|qemu_openfaas_software_parity|qemu_openfaas_image_parity|qemu_openfaas_image_local_parity|qemu_kubecontrol_empty_parity|qemu_kubecontrol_empty_trace_parity|qemu_kube_kata_empty_startup_parity|prereqs)
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
qemu_openfaas_image_local_parity
qemu_kubecontrol_empty_parity
qemu_kubecontrol_empty_trace_parity
qemu_kube_kata_empty_startup_parity
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

if [ "$SCENARIO" = "latest-result-summary" ]; then
  target_scenario="${2:-}"
  if [ -z "$target_scenario" ]; then
    echo "Usage: $0 latest-result-summary <scenario>" >&2
    echo "Known retained scenarios:" >&2
    print_retained_scenarios >&2
    exit 2
  fi
  validate_scenario_name "$target_scenario" || exit $?
  if ! scenario_path=$(retained_scenario_path "$target_scenario"); then
    echo "Unsupported retained scenario for result summary: $target_scenario" >&2
    echo "Known retained scenarios:" >&2
    print_retained_scenarios >&2
    exit 2
  fi
  results_dir="$scenario_path/.continuum/test_results"
  if [ ! -d "$results_dir" ]; then
    echo "No test-results directory for scenario: $target_scenario" >&2
    echo "Path: $results_dir" >&2
    exit 1
  fi
  latest_result=$(
    find "$results_dir" -maxdepth 1 -type f -name 'test_results_*.json' \
      -printf '%T@ %p\n' | sort -n | tail -n 1 | sed 's/^[^ ]* //'
  )
  if [ -z "$latest_result" ]; then
    echo "No retained test result found for scenario: $target_scenario" >&2
    echo "Path: $results_dir" >&2
    exit 1
  fi
  export LATEST_RESULT_PATH="$latest_result"
  "$PYTHON_BIN" - <<'PY'
import json
import os

path = os.environ["LATEST_RESULT_PATH"]
with open(path, "r", encoding="utf-8") as filep:
    payload = json.load(filep)

print("LATEST_RESULT=%s" % path)
for key in ("timestamp", "total_tests", "passed", "failed", "artifacts_dir"):
    if key in payload:
        print("%s=%s" % (key.upper(), payload[key]))

for index, result in enumerate(payload.get("results", []), 1):
    prefix = "RESULT_%02d" % index
    for key in (
        "config_path",
        "success",
        "exit_code",
        "success_reason",
        "failure_class",
        "execution_time",
        "timed_out",
        "stdout_artifact",
        "stderr_artifact",
        "metadata_artifact",
    ):
        if key in result:
            value = str(result[key]).replace("\n", "\\n")
            if len(value) > 1000:
                value = value[:1000] + "...<truncated>"
            print("%s_%s=%s" % (prefix, key.upper(), value))
PY
  exit $?
fi

if [ "$SCENARIO" = "latest-result-tail" ]; then
  if [ "$#" -lt 2 ] || [ "$#" -gt 5 ]; then
    echo "Usage: $0 latest-result-tail <scenario> [stdout|stderr|metadata] [result-index] [--full]" >&2
    exit 2
  fi
  target_scenario=$2
  validate_scenario_name "$target_scenario" || exit $?
  if ! scenario_path=$(retained_scenario_path "$target_scenario"); then
    echo "Unsupported retained scenario for result tail: $target_scenario" >&2
    echo "Known retained scenarios:" >&2
    print_retained_scenarios >&2
    exit 2
  fi
  if [ ! -x "$PYTHON_BIN" ]; then
    echo "Could not find Continuum smoke Python interpreter: $PYTHON_BIN" >&2
    exit 2
  fi
  results_dir="$scenario_path/.continuum/test_results"
  shift 2
  exec "$PYTHON_BIN" - "$results_dir" "$@" <<'PY'
from collections import deque
import json
from pathlib import Path
import re
import shutil
import sys

args = sys.argv[2:]
kind = "stdout"
index_text = "1"
if args and args[0] in ("stdout", "stderr", "metadata"):
    kind = args.pop(0)
if args and args[0] != "--full":
    index_text = args.pop(0)
if not re.fullmatch(r"[1-9][0-9]*", index_text) or args not in ([], ["--full"]):
    print("Usage: latest-result-tail <scenario> [stdout|stderr|metadata] "
          "[positive result-index] [--full]", file=sys.stderr)
    sys.exit(2)
full = bool(args)

try:
    result_index = int(index_text)
    results_dir = Path(sys.argv[1]).resolve(strict=True)
    if not results_dir.is_dir():
        raise ValueError("Not a test-results directory: %s" % results_dir)
    candidates = [
        path for path in results_dir.glob("test_results_*.json")
        if path.is_file() and not path.is_symlink()
    ]
    if not candidates:
        raise ValueError("No retained test result found in %s" % results_dir)
    latest_result = max(candidates, key=lambda path: (path.stat().st_mtime_ns, str(path)))
    latest_result = latest_result.resolve(strict=True)
    if latest_result.parent != results_dir:
        raise ValueError("Result JSON escapes retained results directory: %s" % latest_result)
    with latest_result.open("r", encoding="utf-8") as summary:
        payload = json.load(summary)
    if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
        raise ValueError("Result JSON must contain a results list: %s" % latest_result)
    entries = payload["results"]
    if not 1 <= result_index <= len(entries):
        raise ValueError("Result index %s out of range (1..%d)" % (index_text, len(entries)))
    entry = entries[result_index - 1]
    if not isinstance(entry, dict):
        raise ValueError("Selected result entry must be a mapping")
    recorded = entry.get("%s_artifact" % kind)
    if not isinstance(recorded, str) or not recorded:
        raise ValueError("Selected result has no %s artifact path" % kind)
    artifact = Path(recorded)
    if not artifact.is_absolute() or ".." in artifact.parts:
        raise ValueError("Refusing nonabsolute or parent-traversal artifact: %s" % artifact)
    artifact = artifact.resolve(strict=True)
    try:
        artifact.relative_to(results_dir)
    except ValueError:
        raise ValueError("Refusing result artifact outside retained results directory: %s" % artifact)
    if not artifact.is_file():
        raise ValueError("Result artifact is not a regular file: %s" % artifact)
    with artifact.open("rb") as source:
        print("LATEST_RESULT=%s" % latest_result)
        print("ARTIFACT=%s" % artifact, flush=True)
        if full:
            shutil.copyfileobj(source, sys.stdout.buffer)
        else:
            sys.stdout.buffer.writelines(deque(source, maxlen=120))
except (OSError, ValueError, RuntimeError) as exc:
    print("Cannot inspect retained result: %s" % exc, file=sys.stderr)
    sys.exit(1)
PY
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
  echo "Create the normal-user runner venv first." >&2
  exit 2
fi

if [ "$RUN_MODE" = "debug_playbook" ] && [ ! -x "$ANSIBLE_PLAYBOOK_BIN" ]; then
  echo "Could not find ansible-playbook in the runner venv: $ANSIBLE_PLAYBOOK_BIN" >&2
  echo "Create or refresh the normal-user runner venv first." >&2
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
  qemu_openfaas_image_local_parity)
    set_suite_scenario qemu_openfaas_image_local_parity qemu_openfaas_image_local_parity
    ;;
  qemu_kubecontrol_empty_parity)
    set_suite_scenario qemu_kubecontrol_empty_parity qemu_kubecontrol_empty_parity
    ;;
  qemu_kubecontrol_empty_trace_parity)
    set_suite_scenario qemu_kubecontrol_empty_trace_parity qemu_kubecontrol_empty_trace_parity
    ;;
  qemu_kube_kata_empty_startup_parity)
    set_suite_scenario qemu_kube_kata_empty_startup_parity qemu_kube_kata_empty_startup_parity
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
      HOME="$HOME" \
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
      HOME="$HOME" \
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
      HOME="$HOME" \
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
      HOME="$HOME" \
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
    echo "Allowed values: phase_smoke_matrix, operational_regression, infra_one_vm, software_k8s_two_vm, network_netperf_two_vm, network_validation, qemu_infra_parity, qemu_k8s_nobench_parity, qemu_k8s_image_parity, qemu_kubeedge_software_parity, qemu_kubeedge_image_parity, qemu_mist_software_parity, qemu_mist_image_parity, qemu_endpoint_software_parity, qemu_endpoint_image_parity, qemu_openfaas_software_parity, qemu_openfaas_image_parity, qemu_openfaas_image_local_parity, qemu_kubecontrol_empty_parity, qemu_kubecontrol_empty_trace_parity, qemu_kube_kata_empty_startup_parity, benchmark_k8s_resume_infra, benchmark_k8s_resume_software, benchmark_k8s_resume_application, benchmark_k8s_resume, release-artifact-audit, check-prereqs, list-suites, prime-registry-cache, debug-playbook, storage-report, latest-result-summary, latest-result-tail, prune-scenario" >&2
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
    HOME="$HOME" \
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
    HOME="$HOME" \
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
  HOME="$HOME" \
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
