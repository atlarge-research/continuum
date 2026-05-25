# Phase D Handoff

This document is the clean handoff note for the completed Phase-D runtime state.
Phase-E resume/state integrity and Phase-F test architecture closure have since
landed, so use this file as historical evidence for application and retained
benchmark behavior rather than as the active implementation queue.

This historical handoff does not define release support status. Exact supported
module combinations and certification status are tracked in
`docs/release_certification_matrix.md`.

## 0. Phase-D Closure Snapshot

The retained benchmark application leg is closed, and the explicit
retained-resume prep API is now the intended contract for benchmark-smoke
infrastructure preparation.

Current reality:

1. the dedicated runner and root-owned maintenance helper now exist and are the
   right security shape,
2. the narrow helper and runner prefixes now work from the agent,
3. `continuum-hostctl` can sync the dedicated repo and reinstall the wrapper,
4. stale retained Job cleanup now works,
5. retained infrastructure, software, and application legs all pass on the
   dedicated host-backed `benchmark_k8s_resume_*` path,
6. the retained application closure required repo fixes for registry wiring,
   base-image invalidation, Mosquitto worker prep, endpoint Docker reruns,
   publisher completion, and Kubernetes worker-log collection.

The completed consolidation slice leaves this contract in place:

1. application launch playbooks are thin wrappers around application roles,
   not places for benchmark-specific task duplication,
2. application runtime helpers own benchmark launch timing, worker output, and
   Kubernetes pod completion,
3. retained host-backed smoke should be rerun when a change affects the
   benchmark execution or teardown contract,
4. retained smoke artifacts and generated reports stay uncommitted.

For work that touches application or retained benchmark behavior, the minimum
read set is still:

1. `docs/rework_kickoff.md`
2. this file (`docs/phase_d_handoff.md`)

Read after:

1. `docs/rework_kickoff.md`
2. `docs/rework_plan_stack.md`
3. `docs/ansible_restructuring_design.md`
4. `docs/runtime_execution_pipeline.md`

## 1. What Landed In Phase D

1. The explicit application runtime gate is removed.
   - `input/configuration/runtime_phase_targets.py` now resolves `run.targets: application` normally.
   - `continuum.py` can reach the application phase and persist `phase_completed=application` again.
2. Direct runtime coverage now exists for application-phase control flow.
   - `scripts/test/unit/test_continuum_runtime.py` covers application-only resume from `phase_completed=software`.
   - It also covers resumed `software + application` execution from `phase_completed=infrastructure`.
3. Earlier Phase-D prep remains active and should be treated as already landed.
   - `application/runtime_helpers.py` owns extracted Kubernetes launch timing, worker-output collection, plus Mist/Baremetal worker runtime helpers.
   - shared MQTT worker launch vars/envs for `image_classification` and `text_translation` now also live in `application/runtime_helpers.py`, so those application modules no longer duplicate Kubernetes/Mist/Baremetal runtime shaping logic.
   - application-phase callsites now consume worker output through `application/runtime_helpers.py` rather than through Kubernetes-specific ownership.
   - QEMU infra-only topology now preserves a Kubernetes control-plane VM for resumable cloud deployments instead of collapsing all cloud VMs into worker nodes, which fixes resumed software-phase inventory/control-plane mismatches for `benchmark_k8s_resume`.
   - infra-only bootstrap loads the orchestrator resource-manager module only when `run.prepare_for_resume: true`, so base-image preparation can include orchestrator prereq installs for retained-resume prep without broadening generic infrastructure-only runs.
   - bootstrap imports the application module, sets benchmark images, and validates benchmark-stage options during YAML startup when the primary benchmark stage maps to a runnable application module; planner-only stage types may still parse without one.
   - actual application execution now fails fast with an explicit error if phase 3 is reached without a runnable application module implementation.
   - optional orchestrator booleans such as `cache_worker` now read safely during bootstrap/validation, so parser fixtures without that key still reach the intended benchmark-stage contract checks.
4. A dedicated resumed benchmark smoke slice now exists.
   - New suite: `benchmark_smoke` in `scripts/test/test_config.json`
   - New configs:
     - `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`
     - `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`
     - `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml`
   - New environment profile:
     - `configs/profiles/environment/local-qemu-delete-on-exit.yaml`
   - The repo-local and installed smoke wrappers now expose:
     - `benchmark_k8s_resume_infra`
     - `benchmark_k8s_resume_software`
     - `benchmark_k8s_resume_application`
     - `benchmark_k8s_resume`
5. Runtime option validation is aligned with canonical benchmark-stage contracts.
   - Shared benchmark sizing keys such as `applications_per_worker` and `application_worker_*` are now accepted and validated during application bootstrap instead of being rejected as unknown options.
6. Generated infrastructure temp assets no longer depend on the repo-local `.tmp` directory.
   - Active provider/runtime paths now use a canonical `base_path/.continuum/tmp` workspace.
   - This removes the shared-worktree permission failure that blocked the first host-backed benchmark smoke attempt.
7. Host-backed benchmark prep is hardened further for restricted/sandboxed local execution.
   - `create_continuum_dir()` now treats local/remote `setfacl` application as best-effort instead of mandatory.
   - QEMU bridge discovery now accepts optional `CONTINUUM_QEMU_BRIDGE_NAME` / `CONTINUUM_QEMU_BRIDGE_GATEWAY` overrides, and `br0` gateway discovery also falls back to `/proc/net/route`.
   - `AnsibleRunner` now pins `ANSIBLE_LOCAL_TEMP` under `<base_path>/.continuum/ansible/tmp`, pins `ANSIBLE_REMOTE_TMP` under `/tmp/.continuum-ansible/tmp`, merges runner default env with per-call playbook env, and prefers the `ansible-playbook` executable located next to the active Python interpreter.
8. The canonical agent host-execution model is now a single-script install with a stricter default boundary.
   - New canonical setup script: `scripts/test/setup_agent_host.sh`
   - The default install path is now a dedicated synced repo copy that can stay non-writable for `continuum-smoke`.
   - Runtime logs and test-result artifacts now go under `base_path/.continuum/...` instead of repo-local `./logs`.
   - The smoke wrappers now preserve the explicit QEMU bridge override env when present and disable Python bytecode writes in the executed repo.
9. Host-maintenance and retained benchmark diagnostics are substantially tighter now.
   - Installed maintenance helper: `/usr/local/bin/continuum-hostctl`
   - The helper exposes only a tiny allowlist:
     - `show-config`
     - `sync-repo`
     - `install-wrapper`
     - `verify`
     - `print-agent-command`
   - The helper is intentionally separate from `run-continuum-smoke`, so root
     maintenance actions and runner-user execution stay distinct.
10. Retained benchmark debugging now requires fewer ad hoc host commands.
   - `playbooks/debug/run_command.yml` exists for allowlisted replay/debug.
   - It accepts `debug_hosts` and the compatibility alias `debug_host_pattern`.
   - `infrastructure/ansible.py` now logs useful stdout/stderr tails for failed
     playbooks instead of only surfacing the synthetic nonzero-return line.
11. The retained application path was hardened to remove Ansible Python-module fragility.
   - `application/image_classification/launch_benchmark_kubernetes.yml`
   - `application/text_translation/launch_benchmark_kubernetes.yml`
   - both now use `kubectl apply -f` instead of `kubernetes.core.k8s`
   - this avoids repeated failures caused by missing remote Python packages on
     resumed control-plane VMs.
12. Additional K8s runtime package hardening landed while debugging the retained application path.
   - `roles/resource_manager/k8s_prereqs/tasks/main.yml`
   - `roles/resource_manager/k8s_control_plane/tasks/main.yml`
   - both now install `python3-kubernetes` and `python3-jsonpatch`
   - these should remain useful for other Ansible K8s callsites even though the
     benchmark launch playbooks no longer depend on them directly.
13. Application launch playbooks are now role-owned.
   - `roles/application/k8s_job_deploy` renders all existing Kubernetes Job
     launch variants and can optionally apply them with `kubectl apply -f`.
   - `roles/application/openfaas_deploy` renders and deploys OpenFaaS
     functions, including the existing scale-limit variants.
   - The existing `application/*/launch_benchmark_*.yml` paths remain stable
     wrappers so runtime playbook resolution does not change.
14. The last application-specific Kubernetes completion loop moved out of the
    Kubernetes resource-manager module.
   - `application/runtime_helpers.py` now owns benchmark worker pod completion.
   - `resource_manager/kubernetes/kubernetes.py` stays focused on software-phase
     installation and cluster readiness.
15. Application-phase execution now fails fast consistently.
   - When `run.targets` includes `application`, `continuum.py` calls
     `application.start(runner)` unconditionally.
   - Missing runnable application modules therefore fail in the application
     boundary instead of being logged as a successful skip.
16. Benchmark-smoke success detection now has teardown evidence.
   - `benchmark_smoke` sets `require_teardown`.
   - For the final delete-on-exit application leg, the runner reads saved
     `state.json` machine names and verifies matching QEMU/libvirt domains no
     longer appear after teardown.
   - Remaining domains are classified as `teardown_failure`.

## 2. Historical Phase-D Change Surface

1. `input/configuration/runtime_phase_targets.py`
2. `scripts/test/unit/test_continuum_runtime.py`
3. `scripts/test/e2e/test_e2e_test_utils.py`
4. `scripts/test/test_config.json`
5. `scripts/test/run_smoke_host.sh`
6. `scripts/test/setup_agent_host.sh`
7. `configs/profiles/environment/local-qemu-delete-on-exit.yaml`
8. `configs/experiments/benchmark_smoke/01_infra_k8s_three_vm.yaml`
9. `configs/experiments/benchmark_smoke/02_software_k8s_three_vm.yaml`
10. `configs/experiments/benchmark_smoke/03_application_k8s_image_classification.yaml`
11. `input/configuration/runtime_option_validation.py`
12. `infrastructure/infrastructure.py`
13. `infrastructure/ansible.py`
14. `infrastructure/qemu/generate.py`
15. `infrastructure/qemu/qemu.py`
16. `infrastructure/aws/generate.py`
17. `infrastructure/aws/aws.py`
18. `infrastructure/gcp/generate.py`
19. `infrastructure/gcp/gcp.py`
20. `docs/runtime_execution_pipeline.md`
21. `docs/ansible_restructuring_design.md`
22. `docs/rework_kickoff.md`
23. `docs/rework_plan_stack.md`
24. `docs/phase_c_implementation_plan.md`
25. `docs/configuration_reference.md`
26. `docs/configuration_restructuring_design.md`
27. `docs/software_module_architecture_plan.md`
28. `docs/operational_testing_strategy.md`
29. `docs/smoke_runner_isolation.md`
30. `docs/phase_d_handoff.md`
31. `input/configuration/config_access.py`
32. `input/configuration/runtime_module_loader.py`
33. `application/application.py`
34. `application/runtime_helpers.py`
35. `application/image_classification/image_classification.py`
36. `application/text_translation/text_translation.py`
37. `scripts/test/unit/test_application_runtime_helpers.py`
38. `scripts/test/unit/test_config_access.py`
39. `scripts/test/unit/test_yaml_parser.py`
40. `playbooks/debug/run_command.yml`
41. `roles/resource_manager/docker_setup/tasks/main.yml`
42. `roles/resource_manager/docker_setup/defaults/main.yml`
43. `roles/resource_manager/k8s_prereqs/tasks/main.yml`
44. `roles/resource_manager/k8s_control_plane/tasks/main.yml`
45. `playbooks/resource_manager/endpoint_install.yml`
46. `playbooks/resource_manager/endpoint_base_install.yml`
47. `application/image_classification/launch_benchmark_kubernetes.yml`
48. `application/text_translation/launch_benchmark_kubernetes.yml`
49. `scripts/test/unit/test_role_contracts.py`
50. `scripts/test/e2e/test_host_runner_scripts.py`

## 3. Historical Validation Run

Latest Phase-D consolidation validation (May 20, 2026):

1. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_application_runtime_helpers scripts.test.unit.test_role_contracts scripts.test.unit.test_continuum_runtime scripts.test.e2e.test_e2e_test_utils scripts.test.e2e.test_run_tests`
   - `183 tests OK`
2. `env PYTHONPATH=. python3 -m unittest discover scripts/test`
   - `387 tests OK`
3. `scripts/test/run_cloud_static_audit.sh`
   - required gates passed
   - pytest: `387 passed`
   - docs path references: `TOTAL_MISSING_REFERENCES=0`
   - YAML and Ansible lint baselines OK
4. `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
5. `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated`
6. `sudo -n /usr/local/bin/continuum-hostctl verify`
7. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume`
   - infrastructure leg passed with `phase_completed=infrastructure`
   - software leg passed with `phase_completed=software`
   - application leg passed with `phase_completed=application, teardown_verified`

Passed:

1. `python3 -m py_compile input/configuration/runtime_phase_targets.py scripts/test/unit/test_continuum_runtime.py`
2. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime scripts.test.unit.test_application_runtime_helpers`
3. `python3 -m py_compile infrastructure/infrastructure.py infrastructure/ansible.py infrastructure/qemu/generate.py infrastructure/qemu/qemu.py infrastructure/aws/generate.py infrastructure/aws/aws.py infrastructure/gcp/generate.py infrastructure/gcp/gcp.py scripts/test/unit/test_continuum_runtime.py scripts/test/e2e/test_e2e_test_utils.py scripts/test/run_tests.py`
4. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime scripts.test.e2e.test_example_configs scripts.test.e2e.test_e2e_test_utils scripts.test.e2e.test_run_tests`
5. `env PYTHONPATH=. pytest -q scripts/test/unit/test_continuum_runtime.py scripts/test/e2e/test_example_configs.py scripts/test/e2e/test_e2e_test_utils.py scripts/test/e2e/test_run_tests.py`
6. `env PYTHONPATH=. python3 scripts/test/run_tests.py --suite benchmark_smoke --check-prereqs`
7. `env HOME=/home/continuum-smoke sh scripts/test/run_smoke_host.sh list-suites`
8. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_yaml_parser scripts.test.unit.test_config_access scripts.test.unit.test_continuum_runtime`
9. `env PYTHONPATH=. pytest -q scripts/test/unit/test_yaml_parser.py scripts/test/unit/test_config_access.py scripts/test/unit/test_continuum_runtime.py`
10. `env PYTHONPATH=. python3 -m unittest discover scripts/test`
11. `env PYTHONPATH=. pytest -q scripts/test`
12. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_application_runtime_helpers scripts.test.unit.test_continuum_runtime`
13. `env PYTHONPATH=. pytest -q scripts/test/unit/test_application_runtime_helpers.py scripts/test/unit/test_continuum_runtime.py`
14. `sh -n scripts/test/setup_agent_host.sh scripts/test/run_smoke_host.sh`
15. `python3 -m py_compile continuum.py input/configuration/config_access.py application/empty/empty.py application/empty/plot.py application/empty_kata/empty_kata.py application/empty_kata/plot.py scripts/test/run_tests.py scripts/test/e2e/test_run_tests.py scripts/test/unit/test_config_access.py scripts/test/unit/test_continuum_runtime.py`
16. `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_run_tests scripts.test.unit.test_config_access scripts.test.unit.test_continuum_runtime`
17. `env PYTHONPATH=. pytest -q scripts/test/e2e/test_run_tests.py scripts/test/unit/test_config_access.py scripts/test/unit/test_continuum_runtime.py`
18. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`299 tests OK`)
19. `env PYTHONPATH=. pytest -q scripts/test` (`299 passed`)
20. `sh scripts/test/setup_agent_host.sh show-config`
21. `python3 -m py_compile application/runtime_helpers.py application/image_classification/image_classification.py application/text_translation/text_translation.py scripts/test/unit/test_application_runtime_helpers.py`
22. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_application_runtime_helpers scripts.test.unit.test_continuum_runtime` (`102 tests OK`)
23. `env PYTHONPATH=. pytest -q scripts/test/unit/test_application_runtime_helpers.py scripts/test/unit/test_continuum_runtime.py` (`102 passed`)
24. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`303 tests OK`)
25. `env PYTHONPATH=. pytest -q scripts/test` (`303 passed`)
26. `python3 -m py_compile infrastructure/qemu/qemu.py scripts/test/unit/test_continuum_runtime.py`
27. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime` (`94 tests OK`)
28. `env PYTHONPATH=. pytest -q scripts/test/unit/test_continuum_runtime.py` (`94 passed`)
29. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`305 tests OK`)
30. `env PYTHONPATH=. pytest -q scripts/test` (`305 passed`)
31. `python3 -m py_compile infrastructure/ansible.py scripts/test/unit/test_continuum_runtime.py`
32. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime` (`94 tests OK`)
33. `env PYTHONPATH=. pytest -q scripts/test/unit/test_continuum_runtime.py` (`94 passed`)
34. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`305 tests OK`)
35. `env PYTHONPATH=. pytest -q scripts/test` (`305 passed`)
36. `python3 -m py_compile input/configuration/runtime_module_loader.py scripts/test/unit/test_continuum_runtime.py`
37. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime` (`96 tests OK`)
38. `env PYTHONPATH=. pytest -q scripts/test/unit/test_continuum_runtime.py` (`96 passed`)
39. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`307 tests OK`)
40. `env PYTHONPATH=. pytest -q scripts/test` (`307 passed`)
41. `python3 -m py_compile infrastructure/infrastructure.py infrastructure/ansible.py scripts/test/unit/test_continuum_runtime.py`
42. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime.QemuMachinePlaybookEnvTests scripts.test.unit.test_continuum_runtime.InfrastructureWorkspacePermissionTests scripts.test.unit.test_continuum_runtime.MachineProcessDiagnosticsTests`
43. `python3 -m py_compile application/runtime_helpers.py application/application.py application/mem_usage/mem_usage.py resource_manager/kubernetes/kubernetes.py scripts/test/unit/test_application_runtime_helpers.py`
44. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_application_runtime_helpers scripts.test.unit.test_continuum_runtime`
45. `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_example_configs`
46. `python3 -m py_compile scripts/test/e2e/test_host_runner_scripts.py scripts/test/unit/test_role_contracts.py`
47. `env PYTHONPATH=. python3 -m unittest scripts.test.e2e.test_host_runner_scripts scripts.test.unit.test_role_contracts`
48. `python3 -m py_compile infrastructure/ansible.py scripts/test/unit/test_continuum_runtime.py scripts/test/unit/test_role_contracts.py`
49. `env PYTHONPATH=. python3 -m unittest scripts.test.unit.test_continuum_runtime.AnsibleCheckOutputDiagnosticsTests scripts.test.unit.test_continuum_runtime.MachineProcessDiagnosticsTests scripts.test.unit.test_role_contracts`
50. `yamllint -c sysconfig/yamllint.yml application/image_classification/launch_benchmark_kubernetes.yml application/text_translation/launch_benchmark_kubernetes.yml roles/resource_manager/k8s_prereqs/tasks/main.yml roles/resource_manager/k8s_control_plane/tasks/main.yml`
51. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`342 tests OK`)
52. `env PYTHONPATH=. pytest -q scripts/test` (`342 passed`)
53. `scripts/test/run_cloud_static_audit.sh` (required gates passed; ansible-lint OK; YAML lint baseline still has existing findings)

Observed host-run attempts:

1. `env CONTINUUM_SMOKE_PYTHON=/home/matthijs/anaconda3/bin/python3 sh scripts/test/run_smoke_host.sh benchmark_k8s_resume`
   - first failed on repo-local `.tmp` permission cleanup; fixed by moving temp assets to `base_path/.continuum/tmp`
   - second progressed into QEMU/base-image creation, then failed on libvirt access to `/home/matthijs/continuum_smoke/...` because that ad-hoc base root was not the prepared dedicated-runner path
2. `env HOME=/home/continuum-smoke sh scripts/test/run_smoke_host.sh benchmark_k8s_resume`
   - wrapper and dedicated venv discovery worked
   - creating the benchmark base root failed because the command was still running as the current sandbox user rather than `continuum-smoke`
3. `sudo -n -u continuum-smoke sh scripts/test/run_smoke_host.sh benchmark_k8s_resume`
   - blocked in the sandbox because `sudo` is not usable here
4. `env HOME=/home/continuum-smoke CONTINUUM_SMOKE_PYTHON=/home/continuum-smoke/venvs/continuum/bin/python3 CONTINUUM_SMOKE_BASE_ROOT=/tmp/continuum_smoke sh scripts/test/run_smoke_host.sh benchmark_k8s_resume`
   - first failed because mandatory `setfacl` application on `/tmp/.../.continuum/images` returned `Invalid argument`
   - after the ACL fix, it progressed to QEMU bridge discovery and exposed that this harness cannot read the needed gateway details via the normal host discovery path
5. `env PYTHONPATH=. HOME=/home/continuum-smoke CONTINUUM_SMOKE_PYTHON=/home/continuum-smoke/venvs/continuum/bin/python3 CONTINUUM_QEMU_BRIDGE_NAME=br0 CONTINUUM_QEMU_BRIDGE_GATEWAY=192.168.1.99 LIBVIRT_DEFAULT_URI=qemu:///system /home/continuum-smoke/venvs/continuum/bin/python3 scripts/test/run_tests.py --suite benchmark_smoke --base-path /tmp/continuum_smoke/benchmark_k8s_resume_direct`
   - progressed through inventory generation, QEMU config generation, VM start orchestration, OS-image checks, and base-image preparation
   - exposed and fixed two additional local-run seams:
     - Ansible local tmp defaulting to a read-only home path
     - `ansible-playbook` resolving to an incompatible user-local install instead of the active interpreter-local executable
   - the remaining blocker in that ad hoc harness was the expected libvirt permission boundary:
     - `Failed to connect socket to '/var/run/libvirt/libvirt-sock': Operation not permitted`
6. Canonical host setup is now `scripts/test/setup_agent_host.sh install`.
   - default mode is `dedicated`
   - dedicated repo sync is intended to stay non-writable for `continuum-smoke`
   - repo-local wrapper output no longer needs repo-local `logs/` writes
   - the generated wrapper now carries forward the explicit QEMU bridge override env when configured
7. `env HOME=/home/continuum-smoke sh scripts/test/run_smoke_host.sh list-suites`
   - now fails immediately with `Permission denied` when still executed as the current sandbox user
   - that is expected with the stricter workspace ownership model; the wrapper now correctly requires the actual `continuum-smoke` user for its default base root
8. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke list-suites`
   - now works again in this environment, confirming that the dedicated-user wrapper entrypoint itself is available
   - at that point, the installed wrapper was still the older host copy and did not yet expose `benchmark_k8s_resume`
9. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume`
   - failed at that point with `Unsupported smoke scenario: benchmark_k8s_resume`
   - this was an operational host-install drift issue, not a repo implementation issue
10. refreshing the installed wrapper from `scripts/test/setup_agent_host.sh` was blocked in that sandbox because the script's root-owned install/sync steps required host-side `sudo` outside the then-current sandbox boundary
11. after the host install was refreshed and the dedicated repo was synced, `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume`
   - now completes the infrastructure leg on the prepared dedicated runner path
   - launches `cloud0_continuum-smoke`, `cloud1_continuum-smoke`, and `endpoint0_continuum-smoke`
   - successfully adds SSH host keys for `192.168.100.2`, `192.168.100.3`, and `192.168.100.4`
   - persists `/home/continuum-smoke/continuum_smoke/benchmark_k8s_resume/.continuum/state.json` with `phase_completed=infrastructure`
   - this clears the earlier guest-networking stall caused by hardcoded `ens2` netplan config
12. direct follow-up resume commands from that coding harness were still blocked by the sandboxed `sudo` binary itself
   - historical harness error: `sudo: /usr/bin/sudo must be owned by uid 0 and have the setuid bit set`
   - treat this as a harness limitation, not as a Continuum runtime failure
13. once the dedicated wrapper exposed phase-specific benchmark commands, the resumed software failure became reproducible from retained state
   - `playbooks/resource_manager/k8s_cluster.yml` skipped the `cloudcontroller` play with `skipping: no hosts matched`
   - worker join then timed out for `600s` waiting for `/home/continuum-smoke/continuum_smoke/benchmark_k8s_resume/.continuum/join-command.txt`
   - root cause: the retained infra-only QEMU topology had provisioned `cloud0`/`cloud1` only and no control-plane VM because infra-only runs suppressed `cloud_controller_*` assignment
14. that topology bug is now fixed in-repo
   - infra-only QEMU runs for resumable Kubernetes cloud layouts now preserve a control-plane VM and one fewer worker VM on the first host
   - the pre-fix retained benchmark state under `/home/continuum-smoke/continuum_smoke/benchmark_k8s_resume` should be treated as stale for resumed software/application validation
15. rerunning `benchmark_k8s_resume_infra` after that fix now succeeds and refreshes retained state with:
   - `cloud_controller_continuum-smoke@192.168.100.2`
   - `cloud0_continuum-smoke@192.168.100.3`
   - `endpoint0_continuum-smoke@192.168.100.4`
16. the next resumed software attempt now fails much earlier on a different issue
   - `k8s_cluster.yml` starts with the corrected `cloudcontroller` inventory
   - Ansible then exits almost immediately after warning that guest-side `remote_tmp` resolved to `/root/.ansible/tmp`
   - this is now fixed in-repo by pinning `ANSIBLE_REMOTE_TMP=/tmp/.continuum-ansible/tmp`
17. the retained infra state itself is still usable after the remote-tmp fix
   - only the dedicated synced repo and installed wrapper need refreshing before rerunning `benchmark_k8s_resume_software`
18. after refreshing the topology fix and the remote-tmp fix, another retained-software failure exposed a deeper bootstrap seam
   - the refreshed infra-only run still logged `resource_manager = False` in the runtime module block
   - base-image preparation therefore skipped Kubernetes-family base-install playbooks entirely
   - resumed software then reached `k8s_control_plane` on the retained control-plane VM and failed with `Could not find the requested service kubelet`
19. that bootstrap seam is now fixed in-repo
   - infra-only resumable stacks import the orchestrator resource-manager module only when `run.prepare_for_resume: true`
   - this allows the retained infra step to include orchestrator base-image preparation for resumed software/application validation
20. retained infra should opt into that behavior explicitly through the benchmark-smoke infra config
21. important design clarification from the current debugging path
   - the fix does **not** mean “always install kubelet in base images”
   - current retained-resume behavior is scoped to `run.prepare_for_resume: true`
   - generic infrastructure-only runs should not bake Kubernetes prereqs merely because the selected software profile declares Kubernetes
22. follow-up design concern to carry forward
   - pure infrastructure-only runs and “prepare retained infra for later software/application resume” are now distinguished by config intent
   - future cleanup should preserve that separation rather than reintroducing software-shaped base-image preparation implied only by the presence of a software profile
23. the main operational annoyance was outside Continuum itself
   - the human copy/paste loop was only still happening because that coding
     harness could not execute `sudo`, even for the two narrow commands above
   - the dedicated host wrapper and allowlisted prefixes later closed this
     operational gap
24. retained application debugging reached the point where the benchmark launch playbook itself was the only failing surface
   - the direct `debug-playbook` replay confirmed `python3-kubernetes` first
     missing, then present
   - to avoid repeating Python dependency churn, the K8s benchmark launch
     playbooks were switched from `kubernetes.core.k8s` to `kubectl apply -f`
25. after that playbook change landed, the retained application path was **not**
   rerun yet in this session
   - the then-next actual retained benchmark step was to rerun
     `benchmark_k8s_resume_application` from the installed wrapper after syncing
     the dedicated repo copy
   - because `infrastructure/ansible.py` now logs the stdout/stderr tail on
     failure, that rerun should provide the real failing task directly if it
     still breaks
26. 2026-05-12 historical follow-up: the runner prefix worked from the agent,
    but the maintenance helper prefix still fell through to sandboxed `sudo`
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke list-suites`
     succeeds
   - `sudo -n /usr/local/bin/continuum-hostctl show-config` still fails before
     host sudoers are reached with:
     `sudo: /usr/bin/sudo must be owned by uid 0 and have the setuid bit set`
   - inside the sandbox, `/usr/bin/sudo` is visible as owned by `nobody:nogroup`;
     treat this as external harness allowlist behavior, not Continuum sudoers
     drift
27. because `hostctl sync-repo` is still unavailable from the agent, the live
    `debug-playbook` path was used to replay the current checkout against the
    retained benchmark inventory
   - that replay exposed a real benchmark launch bug: the Kubernetes job
     template is created on the remote control-plane VM, but the repeated job
     copy task was trying to read it as a controller-local `src`
   - both Kubernetes benchmark launch playbooks now set `remote_src: true` for
     that copy task, with regression coverage in
     `scripts/test/unit/test_role_contracts.py`
   - the live image-classification replay then completed the launch playbook and
     created `job.batch/image-classification-1`
28. the direct replay was not a full retained application closure
   - a bounded status check showed the created pod at `ErrImageNeverPull` for
     `192.168.1.104:5000/image_classification_subscriber` with
     `pull_policy=Never`
   - treat that as a direct-replay/image-availability boundary until the synced
     installed wrapper can rerun the full application leg
   - the then-open closure command sequence was:
     `sudo -n /usr/local/bin/continuum-hostctl sync-repo`, then
     `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_application`
29. because `hostctl` remained blocked, the working runner prefix was used as a
    temporary live-checkout bridge:
   - the command shape was:
     `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke debug-playbook benchmark_k8s_resume_application /home/matthijs/continuum/playbooks/debug/run_command.yml -e '{"debug_hosts":"localhost","debug_become":false,"debug_command":"cd /home/matthijs/continuum && env ... python3 scripts/test/run_tests.py ..."}'`
   - this runs the live checkout as the unprivileged `continuum-smoke` user and
     avoids `/srv/continuum/repo` sync for active debugging
   - prereqs passed through that route
   - the retained application run then exposed two live code issues:
     missing optional `kube_deployment` defaulting in runtime helpers, and a
     quoted remote readiness command that produced empty SSH output
30. retained runtime helper follow-up work after `bf345c1`
   - `application/runtime_helpers.py` now defaults missing `kube_deployment` to
     `pod` in the Kubernetes runtime helpers
   - `wait_kubernetes_workers_ready()` now sends the remote readiness command
     without wrapping the whole command in literal quotes and checks for empty
     output before indexing it
   - non-cache Kubernetes benchmark worker launches now use
     `pull_policy=IfNotPresent`; cached-worker launches still use `Never`
   - focused tests were added in `scripts/test/unit/test_application_runtime_helpers.py`
31. latest retained application status before wrapping
   - after the first two fixes, the retained application progressed to a real
     image availability failure
   - `kubectl describe pod image-classification-1-b2fbt` reported
     `ErrImageNeverPull` because image
     `192.168.1.104:5000/image_classification_subscriber` was not present on
     `cloud0continuum-smoke` while pull policy was `Never`
   - the `IfNotPresent` change is intended to let the normal non-cache path
     pull from the configured registry on the next rerun
   - delete the stale failed job before rerunning if the Kubernetes Job template
     has changed:
     `kubectl delete job image-classification-1 --ignore-not-found`
32. 2026-05-13 follow-up: the hostctl blocker is fixed
   - the generated maintenance helper now quotes `SYNC_PROBE_FILES`, avoiding
     the earlier startup failure where `/bin/sh` tried to execute
     `infrastructure/ansible.py`
   - these commands now work from the agent:
     `sudo -n /usr/local/bin/continuum-hostctl show-config`
     `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
     `sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated`
     `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke list-suites`
33. the retained Kubernetes runtime helper fixes are now committed
   - missing `kube_deployment` defaults to `pod` in Kubernetes runtime helpers
   - worker readiness polling no longer wraps the remote command in literal
     quotes and now fails explicitly on empty status output
   - non-cache worker launches use `pull_policy=IfNotPresent`, while
     cached-worker launches still use `Never`
34. the synced-wrapper retained application leg now reaches the Kubernetes apply
    task but fails on stale retained Job state
   - command:
     `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_application`
   - result: `failure_class=nonzero_exit`
   - Kubernetes rejected `image-classification-1` because the existing Job has
     an immutable pod template from the earlier retained replay
   - the follow-up at that point was to delete that Job through the retained debug-playbook path,
     then rerun `benchmark_k8s_resume_application`
35. 2026-05-13 follow-up: stale Job cleanup worked, exposing the next retained
    infrastructure issue
   - `sudo -n /usr/local/bin/continuum-hostctl sync-repo` succeeded
   - the first debug-playbook cleanup command using split `-e` args was parsed
     as bare `kubectl`; the JSON extra-vars form correctly deleted the Job:
     `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke debug-playbook benchmark_k8s_resume_application playbooks/debug/run_command.yml -e '{"debug_hosts":"cloud_controller_continuum-smoke","debug_command":"kubectl delete job image-classification-1 --ignore-not-found"}'`
   - `benchmark_k8s_resume_application` then timed out after 15.1 minutes in
     `wait_kubernetes_workers_ready()`
   - bounded diagnostics showed pod `image-classification-1-k27tk` in
     `ImagePullBackOff`; kubelet tried to pull
     `192.168.1.104:5000/image_classification_subscriber` over HTTPS and got
     `http: server gave HTTP response to HTTPS client`
   - the retained worker still had literal `REGISTRY-IP` entries in
     `/etc/containerd/config.toml`, so the infra-only retained prep had not
     written the local HTTP registry endpoint into containerd
36. the repo fix for that registry seam is now landed
   - `input/configuration/runtime_module_loader.py` sets `config["registry"]`
     for infra-only runs that load a resource-manager module, so retained K8s
     base-image prep can pass `registry_ip` into the Ansible inventory
   - `roles/resource_manager/containerd_setup/tasks/main.yml` now fails fast if
     `REGISTRY-IP` remains in `/etc/containerd/config.toml` after templating
   - `infrastructure/qemu/qemu.py` now fingerprints base-install playbooks and
     direct roles so retained base images rebuild when role content changes
   - `playbooks/resource_manager/k8s_base_install.yml` now includes Mosquitto,
     matching the benchmark worker broker dependency from the legacy K8s base
     install path
   - focused coverage exists in `scripts/test/unit/test_continuum_runtime.py` and
     `scripts/test/unit/test_role_contracts.py`
37. refreshed retained infrastructure/software passed after those fixes
   - `sudo -n /usr/local/bin/continuum-hostctl sync-repo` succeeded
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_infra`
     passed in 308.4 seconds
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_software`
     passed in 189.0 seconds
   - bounded debug check showed `systemctl is-active mosquitto` returned
     `active` on `cloud0_continuum-smoke`
38. retained application then exposed endpoint/runtime rerun issues, now fixed
   - endpoint `docker run` can emit normal pull progress and swap-limit warning
     text on stderr while still returning a container id; endpoint startup now
     treats that as nonfatal unless stderr contains a clear Docker failure
   - endpoint startup now removes stale same-name endpoint containers before
     launching a retained rerun
   - endpoint completion now uses remote-shell-safe `docker container ls`
     formatting rather than escaped quote literals
39. retained application also exposed an image publisher completion bug
   - `image_classification` publisher could receive more responses than the
     requested image count and then hang forever waiting for exact equality
   - publisher completion now waits while `RECEIVED < MAX_IMGS`; the sibling
     `text_translation` publisher uses the same at-least-target condition
   - for the retained validation run, the patched image-classification
     publisher source was copied into the retained local-registry image and
     pushed as `192.168.1.104:5000/image_classification_publisher:latest`
40. retained application result collection exposed one more SSH shell quoting bug
   - Kubernetes worker log collection no longer wraps the whole batched
     `kubectl logs ...; echo DELIMITER01234` command in literal quotes
   - focused coverage exists in `scripts/test/unit/test_application_runtime_helpers.py`
41. final retained application closure passed
   - before the final run, the stale Job was deleted with:
     `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke debug-playbook benchmark_k8s_resume_application playbooks/debug/run_command.yml -e '{"debug_hosts":"cloud_controller_continuum-smoke","debug_command":"kubectl delete job image-classification-1 --ignore-not-found"}'`
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_application`
     passed in 64.6 seconds
   - result artifact:
     `/home/continuum-smoke/continuum_smoke/benchmark_k8s_resume/.continuum/test_results/test_results_2026-05-13_17-11-53.json`

## 4. Current Phase-D State

1. benchmark/application execution is no longer blocked by runtime target resolution,
2. application-only runs require saved `phase_completed=software` state when infrastructure/software are skipped,
3. resumed `software + application` runs require saved `phase_completed=infrastructure` state,
4. the repository now has a concrete resumed `benchmark_smoke` suite and wrapper scenario for the K8s benchmark path,
5. the dedicated host-backed benchmark path now reaches a refreshed retained topology with the expected control-plane VM,
6. retained infrastructure, retained software, and retained application have all
   passed on the dedicated host-backed path after the recent fixes,
7. retained application is no longer the open benchmark leg,
8. generic infrastructure-only execution is now separated from retained
   benchmark resume preparation via `run.prepare_for_resume`,
9. the forever/canonical agent host setup path is now `scripts/test/setup_agent_host.sh`, with dedicated read-only repo execution as the default boundary,
10. do not generalize retained-resume prep into unconditional orchestrator package installs for unrelated infra-only runs.
11. Phase-E resume integrity now treats `state.json` as schema v2 and rejects
    old retained state files; rerun the infrastructure leg to regenerate state
    after this boundary changes.
12. `experiment_lock.yaml` and `state.json` now carry matching
    `resume_contract` metadata, so compatible retained phases must keep
    topology/software/network intent stable while still allowing phase-local
    target/delete/base-path differences.
13. Network-validation NDJSON is a base-path runtime artifact under
    `<base_path>/.continuum/logs/network_validation/`, and the runner validates
    it as part of the `network_validation` suite success contract.
14. Benchmark-smoke success detection now checks lightweight stdout markers,
    structured benchmark metric artifacts, bounded statistical assertions over
    endpoint latency, and at least one numeric endpoint metric row for the
    resumed application leg.

## 5. Next Clean Start Point

Primary resume entry:

1. read `docs/rework_kickoff.md`
2. read this file (`docs/phase_d_handoff.md`)

Then continue here for application or retained benchmark work:

1. Reuse the explicit `run.prepare_for_resume` retained-resume contract instead
   of reintroducing implicit infra-only Kubernetes preparation.
2. Reuse the current hardening already landed here instead of re-debugging them:
   - best-effort `setfacl`
   - optional QEMU bridge overrides
   - Ansible local tmp pinning and env merge
   - interpreter-local `ansible-playbook` resolution
   - `scripts/test/setup_agent_host.sh install` as the canonical host bootstrap path
   - runtime/test outputs under `base_path/.continuum/...` rather than repo-local `./logs`
   - network-validation output under `<base_path>/.continuum/logs/network_validation/`
3. For follow-up prep or runtime slices, prioritize cloud-safe validation first:
   - config/runtime unit tests covering schema validation, config access,
     legacy projection, runtime loading, and example configs
   - `scripts/test/run_cloud_static_audit.sh`
4. Only rerun retained host-backed smoke if the next slice changes the
   retained benchmark execution contract.
5. Keep the design concern visible: if more fixes are needed in this area,
   prefer explicit retained-resume intent over broadening “infra-only” side
   effects.
6. For Phase-E state/resume work, use the contract boundary documented in
   `docs/runtime_execution_pipeline.md` and `docs/ansible_restructuring_design.md`;
   do not make the resume contract depend on benchmark pipeline content or
   cleanup/delete intent.

## 6. Things Not To Reconstruct Again

1. Do not re-add a runtime target gate for `application`; the explicit ungate slice is now landed.
2. Do not redo the earlier helper extraction from `resource_manager/kubernetes/kubernetes.py`; that prep work is already in the tree.
3. Do not treat Phase D as a parser/bootstrap-enablement task anymore; Phase-E resume/state validation and Phase-F test closure have since landed.
4. Do not move generated runtime assets back under repo-local `.tmp`; the active temp workspace is `base_path/.continuum/tmp`.
5. Do not try to salvage pre-Phase-E retained state; schema-v2 state is the
   compatibility boundary.
