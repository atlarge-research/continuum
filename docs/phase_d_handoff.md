# Phase D Handoff

This document is the clean handoff note for the current Phase-D runtime state.
This is the primary continuation point for the next agent.

## 0. Immediate Next-Session Priority

The next session should start with the harness boundary, not with more
benchmark/application code changes.

Current reality:

1. the dedicated runner and root-owned maintenance helper now exist and are the
   right security shape,
2. the remaining reason a human still has to run commands is that this coding
   harness cannot execute any `sudo` invocation itself, even for the narrow
   allowlisted commands,
3. that harness limitation is now the main source of development slowdown.

So the first task next session is:

1. make the harness able to invoke only these prefixes directly:
   - `sudo -n /usr/local/bin/continuum-hostctl`
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke`
2. once that is working, resume the retained benchmark path from the installed
   wrapper without any human copy/paste loop.

For active implementation resume, the minimum read set is still:

1. `docs/rework_kickoff.md`
2. this file (`docs/phase_d_handoff.md`)

Read after:

1. `docs/rework_kickoff.md`
2. `docs/rework_plan_stack.md`
3. `docs/ansible_restructuring_design.md`
4. `docs/runtime_execution_pipeline.md`

## 1. What Landed In This Session

1. The explicit application runtime gate is removed.
   - `input/configuration/runtime_phase_targets.py` now resolves `run.targets: application` normally.
   - `continuum.py` can reach the application phase and persist `phase_completed=application` again.
2. Direct runtime coverage now exists for application-phase control flow.
   - `scripts/test/test_continuum_runtime.py` covers application-only resume from `phase_completed=software`.
   - It also covers resumed `software + application` execution from `phase_completed=infrastructure`.
3. Earlier Phase-D prep remains active and should be treated as already landed.
   - `application/runtime_helpers.py` owns extracted Kubernetes launch timing, worker-output collection, plus Mist/Baremetal worker runtime helpers.
   - shared MQTT worker launch vars/envs for `image_classification` and `text_translation` now also live in `application/runtime_helpers.py`, so those application modules no longer duplicate Kubernetes/Mist/Baremetal runtime shaping logic.
   - application-phase callsites now consume worker output through `application/runtime_helpers.py` rather than through Kubernetes-specific ownership.
   - QEMU infra-only topology now preserves a Kubernetes control-plane VM for resumable cloud deployments instead of collapsing all cloud VMs into worker nodes, which fixes resumed software-phase inventory/control-plane mismatches for `benchmark_k8s_resume`.
   - infra-only bootstrap now still loads the orchestrator resource-manager module for resumable stacks such as Kubernetes, so base-image preparation can include orchestrator prereq installs instead of leaving `config["module"]["resource_manager"] = False`.
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

## 2. Files Touched In This Session

1. `input/configuration/runtime_phase_targets.py`
2. `scripts/test/test_continuum_runtime.py`
3. `scripts/test/test_e2e_test_utils.py`
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
37. `scripts/test/test_application_runtime_helpers.py`
38. `scripts/test/test_config_access.py`
39. `scripts/test/test_yaml_parser.py`
40. `playbooks/debug/run_command.yml`
41. `roles/resource_manager/docker_setup/tasks/main.yml`
42. `roles/resource_manager/docker_setup/defaults/main.yml`
43. `roles/resource_manager/k8s_prereqs/tasks/main.yml`
44. `roles/resource_manager/k8s_control_plane/tasks/main.yml`
45. `playbooks/resource_manager/endpoint_install.yml`
46. `application/image_classification/launch_benchmark_kubernetes.yml`
47. `application/text_translation/launch_benchmark_kubernetes.yml`
48. `scripts/test/test_role_contracts.py`
49. `scripts/test/test_host_runner_scripts.py`

## 3. Validation Run

Passed:

1. `python3 -m py_compile input/configuration/runtime_phase_targets.py scripts/test/test_continuum_runtime.py`
2. `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime scripts.test.test_application_runtime_helpers scripts.test.test_kubernetes_runtime`
3. `python3 -m py_compile infrastructure/infrastructure.py infrastructure/ansible.py infrastructure/qemu/generate.py infrastructure/qemu/qemu.py infrastructure/aws/generate.py infrastructure/aws/aws.py infrastructure/gcp/generate.py infrastructure/gcp/gcp.py scripts/test/test_continuum_runtime.py scripts/test/test_e2e_test_utils.py scripts/test/run_tests.py`
4. `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime scripts.test.test_example_configs scripts.test.test_e2e_test_utils scripts.test.test_run_tests`
5. `env PYTHONPATH=. pytest -q scripts/test/test_continuum_runtime.py scripts/test/test_example_configs.py scripts/test/test_e2e_test_utils.py scripts/test/test_run_tests.py`
6. `env PYTHONPATH=. python3 scripts/test/run_tests.py --suite benchmark_smoke --check-prereqs`
7. `env HOME=/home/continuum-smoke sh scripts/test/run_smoke_host.sh list-suites`
8. `env PYTHONPATH=. python3 -m unittest scripts.test.test_yaml_parser scripts.test.test_config_access scripts.test.test_continuum_runtime`
9. `env PYTHONPATH=. pytest -q scripts/test/test_yaml_parser.py scripts/test/test_config_access.py scripts/test/test_continuum_runtime.py`
10. `env PYTHONPATH=. python3 -m unittest discover scripts/test`
11. `env PYTHONPATH=. pytest -q scripts/test`
12. `env PYTHONPATH=. python3 -m unittest scripts.test.test_application_runtime_helpers scripts.test.test_kubernetes_runtime scripts.test.test_continuum_runtime`
13. `env PYTHONPATH=. pytest -q scripts/test/test_application_runtime_helpers.py scripts/test/test_kubernetes_runtime.py scripts/test/test_continuum_runtime.py`
14. `sh -n scripts/test/setup_agent_host.sh scripts/test/run_smoke_host.sh`
15. `python3 -m py_compile continuum.py input/configuration/config_access.py application/empty/empty.py application/empty/plot.py application/empty_kata/empty_kata.py application/empty_kata/plot.py scripts/test/run_tests.py scripts/test/test_run_tests.py scripts/test/test_config_access.py scripts/test/test_continuum_runtime.py`
16. `env PYTHONPATH=. python3 -m unittest scripts.test.test_run_tests scripts.test.test_config_access scripts.test.test_continuum_runtime`
17. `env PYTHONPATH=. pytest -q scripts/test/test_run_tests.py scripts/test/test_config_access.py scripts/test/test_continuum_runtime.py`
18. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`299 tests OK`)
19. `env PYTHONPATH=. pytest -q scripts/test` (`299 passed`)
20. `sh scripts/test/setup_agent_host.sh show-config`
21. `python3 -m py_compile application/runtime_helpers.py application/image_classification/image_classification.py application/text_translation/text_translation.py scripts/test/test_application_runtime_helpers.py`
22. `env PYTHONPATH=. python3 -m unittest scripts.test.test_application_runtime_helpers scripts.test.test_continuum_runtime` (`102 tests OK`)
23. `env PYTHONPATH=. pytest -q scripts/test/test_application_runtime_helpers.py scripts/test/test_continuum_runtime.py` (`102 passed`)
24. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`303 tests OK`)
25. `env PYTHONPATH=. pytest -q scripts/test` (`303 passed`)
26. `python3 -m py_compile infrastructure/qemu/qemu.py scripts/test/test_continuum_runtime.py`
27. `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime` (`94 tests OK`)
28. `env PYTHONPATH=. pytest -q scripts/test/test_continuum_runtime.py` (`94 passed`)
29. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`305 tests OK`)
30. `env PYTHONPATH=. pytest -q scripts/test` (`305 passed`)
31. `python3 -m py_compile infrastructure/ansible.py scripts/test/test_continuum_runtime.py`
32. `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime` (`94 tests OK`)
33. `env PYTHONPATH=. pytest -q scripts/test/test_continuum_runtime.py` (`94 passed`)
34. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`305 tests OK`)
35. `env PYTHONPATH=. pytest -q scripts/test` (`305 passed`)
36. `python3 -m py_compile input/configuration/runtime_module_loader.py scripts/test/test_continuum_runtime.py`
37. `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime` (`96 tests OK`)
38. `env PYTHONPATH=. pytest -q scripts/test/test_continuum_runtime.py` (`96 passed`)
39. `env PYTHONPATH=. python3 -m unittest discover scripts/test` (`307 tests OK`)
40. `env PYTHONPATH=. pytest -q scripts/test` (`307 passed`)
41. `python3 -m py_compile infrastructure/infrastructure.py infrastructure/ansible.py scripts/test/test_continuum_runtime.py`
42. `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime.QemuMachinePlaybookEnvTests scripts.test.test_continuum_runtime.InfrastructureWorkspacePermissionTests scripts.test.test_continuum_runtime.MachineProcessDiagnosticsTests`
43. `python3 -m py_compile application/runtime_helpers.py application/application.py application/mem_usage/mem_usage.py resource_manager/kubernetes/kubernetes.py scripts/test/test_application_runtime_helpers.py`
44. `env PYTHONPATH=. python3 -m unittest scripts.test.test_application_runtime_helpers scripts.test.test_continuum_runtime`
45. `env PYTHONPATH=. python3 -m unittest scripts.test.test_example_configs`
46. `python3 -m py_compile scripts/test/test_host_runner_scripts.py scripts/test/test_role_contracts.py`
47. `env PYTHONPATH=. python3 -m unittest scripts.test.test_host_runner_scripts scripts.test.test_role_contracts`
48. `python3 -m py_compile infrastructure/ansible.py scripts/test/test_continuum_runtime.py scripts/test/test_role_contracts.py`
49. `env PYTHONPATH=. python3 -m unittest scripts.test.test_continuum_runtime.AnsibleCheckOutputDiagnosticsTests scripts.test.test_continuum_runtime.MachineProcessDiagnosticsTests scripts.test.test_role_contracts`
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
   - current remaining blocker in this harness is now the expected libvirt permission boundary:
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
   - however, the installed wrapper is still the older host copy and does not yet expose `benchmark_k8s_resume`
9. `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume`
   - currently fails with `Unsupported smoke scenario: benchmark_k8s_resume`
   - this is now an operational host-install drift issue, not a repo implementation issue
10. refreshing the installed wrapper from `scripts/test/setup_agent_host.sh` is blocked in this sandbox because the script's root-owned install/sync steps still require host-side `sudo` outside the current sandbox boundary
11. after the host install was refreshed and the dedicated repo was synced, `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume`
   - now completes the infrastructure leg on the prepared dedicated runner path
   - launches `cloud0_continuum-smoke`, `cloud1_continuum-smoke`, and `endpoint0_continuum-smoke`
   - successfully adds SSH host keys for `192.168.100.2`, `192.168.100.3`, and `192.168.100.4`
   - persists `/home/continuum-smoke/continuum_smoke/benchmark_k8s_resume/.continuum/state.json` with `phase_completed=infrastructure`
   - this clears the earlier guest-networking stall caused by hardcoded `ens2` netplan config
12. direct follow-up resume commands from this coding harness are still blocked by the sandboxed `sudo` binary itself
   - current harness error: `sudo: /usr/bin/sudo must be owned by uid 0 and have the setuid bit set`
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
   - infra-only resumable stacks still import the orchestrator resource-manager module unless the orchestrator type is the sentinel `none`
   - this allows the retained infra step to include orchestrator base-image preparation for resumed software/application validation
20. because the current retained infra state was created before that bootstrap fix, it should be refreshed once more before retrying `benchmark_k8s_resume_software`
21. important design clarification from the current debugging path
   - the fix does **not** mean “always install kubelet in base images”
   - current behavior remains scoped to the selected software profile for the run: if the software stack declares `kubernetes`, infra-only retained-state preparation may still bake Kubernetes prereqs into the base image for later resumed software/application phases
   - this is acceptable as a short-term compatibility fix for the resumed benchmark path, but the long-term design should make that intent explicit instead of overloading plain `run.targets: [infrastructure]`
22. follow-up design concern to carry forward
   - pure infrastructure-only runs and “prepare retained infra for later software/application resume” are not cleanly distinguished today
   - future cleanup should separate those intents, so software-shaped base-image preparation is opt-in and explicit rather than implied by the presence of a software profile during an infra-only run
23. the main operational annoyance is now outside Continuum itself
   - the human copy/paste loop is only still happening because this coding
     harness cannot execute `sudo`, even for the two narrow commands above
   - this is now the primary thing to fix next session
24. retained application debugging reached the point where the benchmark launch playbook itself was the only failing surface
   - the direct `debug-playbook` replay confirmed `python3-kubernetes` first
     missing, then present
   - to avoid repeating Python dependency churn, the K8s benchmark launch
     playbooks were switched from `kubernetes.core.k8s` to `kubectl apply -f`
25. after that playbook change landed, the retained application path was **not**
   rerun yet in this session
   - the next actual retained benchmark step is therefore to rerun
     `benchmark_k8s_resume_application` from the installed wrapper after syncing
     the dedicated repo copy
   - because `infrastructure/ansible.py` now logs the stdout/stderr tail on
     failure, that rerun should provide the real failing task directly if it
     still breaks

## 4. Current Phase-D State

1. benchmark/application execution is no longer blocked by runtime target resolution,
2. application-only runs require saved `phase_completed=software` state when infrastructure/software are skipped,
3. resumed `software + application` runs require saved `phase_completed=infrastructure` state,
4. the repository now has a concrete resumed `benchmark_smoke` suite and wrapper scenario for the K8s benchmark path,
5. the dedicated host-backed benchmark path now reaches a refreshed retained topology with the expected control-plane VM, but the currently retained base image still predates the infra-only resource-manager bootstrap fix,
6. retained infrastructure and retained software have both been rerun successfully on the dedicated host path after the recent fixes,
7. retained application is still the open benchmark leg, but the launch playbooks were just simplified to `kubectl apply -f` and have not been rerun yet,
8. full benchmark closure no longer primarily depends on Continuum code plumbing; it now depends on eliminating the harness-side inability to run the narrow `sudo` wrapper/helper commands from the agent,
9. the forever/canonical agent host setup path is now `scripts/test/setup_agent_host.sh`, with dedicated read-only repo execution as the default boundary,
10. do not generalize the current fix into unconditional orchestrator package installs for unrelated infra-only runs; the open design task is to make retained-resume preparation explicit.

## 5. Next Clean Start Point

Primary resume entry:

1. read `docs/rework_kickoff.md`
2. read this file (`docs/phase_d_handoff.md`)

Then continue here:

1. Fix the harness integration first.
   - goal: the agent itself must be able to run:
     - `sudo -n /usr/local/bin/continuum-hostctl ...`
     - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke ...`
   - do **not** widen that into arbitrary `sudo` or shell access
   - once this works, stop using the human copy/paste loop entirely
2. Reuse the current hardening already landed here instead of re-debugging them:
   - best-effort `setfacl`
   - optional QEMU bridge overrides
   - Ansible local tmp pinning and env merge
   - interpreter-local `ansible-playbook` resolution
   - `scripts/test/setup_agent_host.sh install` as the canonical host bootstrap path
   - runtime/test outputs under `base_path/.continuum/...` rather than repo-local `./logs`
3. After harness integration is fixed, sync the dedicated repo copy through the
   installed helper and rerun only the retained application leg first.
   - `sudo -n /usr/local/bin/continuum-hostctl sync-repo`
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke benchmark_k8s_resume_application`
4. If retained application still fails, use the now-improved main-run logging
   first. Only if needed, use the dedicated debug replay entrypoint:
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke debug-playbook ...`
5. If retained application finally passes, then resume the remaining Phase-D
   cleanup work. The next best cleanup target after benchmark closure is the
   harness integration documentation plus any remaining explicit separation of
   pure infra-only intent vs retained-resume prep intent.
6. If the next real host run still fails, treat it as a post-infrastructure runtime/software/application issue, not as a parser/runtime-target or guest-bootstrap issue.
7. Update this file with the resumed application result and any benchmark-specific artifact assertions that need tightening.
8. Keep the design concern visible: if more fixes are needed in this area, prefer making retained-resume base-image prep explicit rather than broadening “infra-only” side effects.
   - the current Kubernetes prereq baking is a compatibility behavior for runs whose selected software profile already declares `kubernetes`; it is not the desired long-term meaning of generic infrastructure-only execution.

## 6. Things Not To Reconstruct Again

1. Do not re-add a runtime target gate for `application`; the explicit ungate slice is now landed.
2. Do not redo the earlier helper extraction from `resource_manager/kubernetes/kubernetes.py`; that prep work is already in the tree.
3. Do not treat Phase D as a parser/bootstrap-enablement task anymore; the active remaining work is runtime validation, cleanup, and host-backed benchmark smoke execution.
4. Do not move generated runtime assets back under repo-local `.tmp`; the active temp workspace is `base_path/.continuum/tmp`.
