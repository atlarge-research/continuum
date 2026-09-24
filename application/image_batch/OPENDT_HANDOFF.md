# OpenDC demo handoff

## Where to resume

Continue on `codex/opendc-readiness-20260924`, created from `873dc11982cc296ecebc1906ab299407d6a2aae3`. The overnight branch is for user review; do not merge it into the starting branch or main. Preserve subsequent user changes and all ignored evidence before further experiments.

The updated source-build integration, causal membership diagnostics, initial task pinning, complete represented-work cordon accounting, native action/sample batching, controlled physical admission checks, independent-workload-seed study and measured/forecast/replay report composition are implemented. These supersede the historical plans for worker capacity, control-plane placement, packing, provisional execution, initial configuration selection and report integration. The accepted branch-wide [lint cleanup](LINT_CLEANUP.md) remains complete; it is not a new prerequisite.

The authoritative overnight evidence is `/mnt/sdb/matthijs/fns-evidence/opendc-readiness-20260924T0051/`; the ignored repository [index](../../logs/fns-opendc-readiness/20260924T0051/EVIDENCE.md) points there. Read its `FINDINGS.md`, `COMMANDS.md` and `VALIDATION.md` before continuing. Exact configurations, commands, failed attempts, numerical results, source/image archives and raw observations live with those artifacts, not in this document. The final review found no actionable important correctness or scientific findings; delivery checks and their exact outcomes are recorded in `VALIDATION.md`.

Priorities after review are to explain remaining per-Job scheduling discrepancies, improve causal observation where state and arrival streams disagree, and obtain the developer's actual runnable distribution or source pin if binary equivalence matters. Startup timing, exhausted-work occupancy and physical energy calibration remain separate limitations. Do not add a scaling policy, SLO threshold or automatic actuator as a continuation of this work.

## Runtime provenance and supported boundary

The supplied [FNS-demo example](https://github.com/atlarge-research/FNS-demo/tree/41aaa9e20a4e299329924454316e6c91eb39f42f) is pinned at `41aaa9e20a4e299329924454316e6c91eb39f42f`. The user confirmed that the developer supplied no updated JAR/distribution or engine source pin. Its initial-history ZIP predates the relevant features and is not a substitute.

The tested source-build fallback is OpenDC `cf10c06eb73c7e60e1076e376922b1201caf12d1`, source archive SHA-256 `b60208e517037eaeae10f5ef32f36716bda5500de9c9a89f4e8cfc240f5ccb25`. This is separately identified, not verified equivalent to the developer's unavailable binary. The preserved old-engine path uses `7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad`. Keep example, engine and Continuum wrapper provenance distinct. The original Task/Fragment and workload-producer contract follows OpenDT `c3e1f8cd56918d8c10c4013a8b8733011323f9d7`; current execution invokes OpenDC directly, not an OpenDT runtime.

The exercised image is `continuum/opendc:fns-native-batch-20260924-cf10c06`, ID `sha256:7df350c45aca2041fb9b29250757502e4b0f18dec03fbfb3a59a355ffa998afe`. Its actual `/app` archive and build/inspect records are under `build/`; do not assume this earlier image contains later host-side reporting code. Build recipes remain in the README. Existing calibrated worker and historical simulator images were archived before changes.

The native path validates assigned tasks on their observed hosts at zero, complete represented-work draining of a cordoned host, no ordinary admissions to that host, host-availability closure and complete datacenter energy accounting. The supplied single-experiment example and our action/sample matrices were exercised. Input order is a real precondition: pinned tasks must form the leading trace group. Only the adapted native copy is reordered; original tasks and timestamps remain preserved.

Host-specific CPU/RAM fit must be checked before execution: negative upstream probes with an undersized assigned host or oversubscribed pins timed out. A reordered pin trace with cordon failed. The adapter rejects unsupported inputs rather than patching upstream. Reproduction artifacts are in `experiments/pin-host-fit/`, `experiments/pin-overlap/` and `experiments/permuted-cordon/`; the findings index distinguishes negative probes from supported inputs.

The SDK expands cordons outside workload samples: action-major, sample-minor, with all other experiment dimensions constrained to singletons. Unique trace URIs prevent identical bytes being deduplicated. Shared process cost is recorded once, never divided into invented per-sample costs. Empty or incompatible suites use individual execution. The example's two trace directories have identical bytes, so they are not independent workload samples.

The pinned reader divides memory by 1,000; the native adaptation compensates without changing original MiB observations. Use datacenter cumulative energy rather than summing last host rows: removal can stop host telemetry before the last accounting interval. Float32 tolerance is explicit. These checks establish internal accounting, not physical energy accuracy.

## Observation and evaluation limits

Cutoff reconstruction distinguishes snapshot membership, arrivals already known before cutoff, completed profiles, classifier-finished inventory, unresolved state and later evidence. A missing known Job is exposed, never assigned an invented phase or worker. Snapshot-based classifier completion can supply retrospective outcomes before completed-profile emission; failed work is not a successful completion. Normal Kubernetes watch closures now resume from resource version; expired/error paths remain explicit capture failures.

Non-atomic Job/Pod snapshots and arrival watches still leave occasional unresolved membership. Model-exhausted Jobs remain visible and receive no fabricated tail, occupancy or completion. A selected removal worker with exhausted work is rejected because its drain boundary is unknown. Represented running remainders and startup requests occupy their pinned hosts immediately, but classifier startup delay and full exhausted occupancy are not restored. Correct placement does not establish complete live-state fidelity or accurate per-Job scheduling.

The unchanged comparison improved initial placement while leaving completion timing unchanged on the preserved old/new cases. New controlled captures validate busy/empty Kubernetes cordon and warm-reserve admission against their own observations. All initial assignments are checked, including work on the original workers during reserve admission. API-boundary bindings, missing final Pods and unmeasured clock alignment are inconclusive. These captures do not measure VM shutdown, boot delay, physical energy or a paired action-performance benefit.

The new configuration study uses workload seeds 46/47 for selection and 48 for held-out evaluation, with a separate scenario seed. It preserves the earlier H60/N10 reference. H60/N3 was frozen before seed48 started; no deployment settings were changed automatically. Candidate means give independent workload runs equal weight after matching cutoffs within each run. Overlapping cutoffs and nested scenario prefixes are dependent. The separate rising/busy-phase scenario-seed check shows that small configuration differences are not robust; it does not retune the held-out choice.

Main study profiles freeze after three 240-second warm-up cycles. Short controlled action replays instead freeze a completed-work profile after one fully covered 120-second cycle plus one bin, then discard forecast samples and use actual arrivals. This avoids making Poisson readiness a prerequisite for an oracle feature check. These are distinct protocols: action replays include H120 competing arrivals while scoring H60 arrivals plus backlog over E120. The actual API action follows the simulated cutoff by a recorded clock-bounded interval. Preserve that offset and all original Job creation times when interpreting response errors.

## Reports and preserved evidence

New reports lead with real measurements and keep arrival-model accuracy separate from simulator accuracy. The tracked composition layer reuses the existing physical and forecast analyzers; those generators were already tracked, although the older reports themselves are ignored evidence. Saved numerical payloads support offline regeneration. Different workload seeds are not aligned by batch index. Scenario ranges and between-run ranges are descriptive, not confidence intervals.

Current new artifacts under the evidence root are `reports/new-study-v2/report/report.pdf` (three measured runs, arrival-forecast accuracy and frozen study), `reports/controlled-v1/report.pdf` (physical assignments, actual-action completions and matched per-Job responses), and `reports/prototype-v2/report.pdf` (preserved historical physical/forecast evidence plus old/new/pinned replay). See final validation for any subsequent reviewed revisions.

Preserve the approved [four-page PDF](../../logs/fns-provisional/packing-validation-20260921/report-source-20260923/report.pdf), the [physical-run report](../../logs/fns-analysis-review/separate-reviewed/report.pdf), and the [intuitive forecast report](../../logs/fns-forecast-review/postmortem/intuitive-final-report/report.pdf) byte-for-byte. The historical action illustration has three futures, whereas its selected forecast configuration has ten; it is not measured execution of that configuration. Historical same-seed physical runs are execution repetitions, not independent workload seeds. Historical study commands and results remain in [packing-validation evidence](../../logs/fns-provisional/packing-validation-20260921/COMMANDS.md).

## Cluster setup reference

Kubernetes modernization was deferred: no tested OpenDC feature required it. The existing stack is Kubernetes 1.27.16, containerd 1.7.27 and Ubuntu 20.04. A future upgrade must update Continuum/Ansible and provision a fresh cluster, never upgrade this cluster in place. Recheck supported versions and runtime/networking/monitoring compatibility then. The inspected `pr-23-curated` ref is still 1.27-era provisioning. Inventory disk backing chains and preserve base images, captures and image provenance before any reprovisioning; the overnight work did not reprovision VMs.

SSH users match VM names: `cloud_controller_matthijs@192.168.210.2`, workers `cloud0_matthijs`/`.3`, `cloud1_matthijs`/`.4`, `cloud2_matthijs`/`.5`, and `endpoint0_matthijs@192.168.210.6`, using `~/.ssh/id_rsa_continuum`. Kubernetes node names omit underscores. Keep application Jobs worker-only and the control-plane NoSchedule taint intact. The simulator runner uses an explicit control-plane selector/toleration and real scheduler resource checks under one CPU/two GiB limits; do not bind it with nodeName or silently fall back to workers.

Preserve four images, 128 inference repetitions, five-second resource sampling and `continuum/image-batch-worker:fns-final-20260905`. Four configured VM cores mean three modeled application cores, applying C−1 once. Supply configured cores to worker preparation, not already-reduced cores. An explicitly excluded Ready, cordoned and empty worker can be a warm reserve; live assignments, including unrepresented ones, cannot be reclassified as an empty reserve.

Before deployment, install [scheduler-packing.yaml](manifests/scheduler-packing.yaml) as `/etc/kubernetes/fns-packing.yaml` and mount it in the existing kube-scheduler static Pod with `--config`. Back up the old manifest outside `/etc/kubernetes/manifests`; otherwise Kubernetes may run the backup as another static Pod. Preserve the scheduler kubeconfig mount. Verify actual packing and fit, not just the configured profile name.

Network replay uses KPN 5G traces and the existing static core profile. Run `sudo python3 /home/mahimahi/continuum_replay.py check` on the endpoint before a capture. Preserve the prior replay, routing and firewall state and restore it after isolated experiments.

### Capture and cleanup cautions

The original `fns-demo` deployment was preserved. Its long-lived observer had historical restarts and is not a valid new continuous capture. New experiments used isolated namespaces and archived source ConfigMaps containing the watch fix; use a fresh updated capture path for continuation. A healthy process at inspection does not retroactively validate an interrupted stream.

Archive `/var/lib/opendt` before removing the observer Pod: its emptyDir is ephemeral. Preserve workload, resource-snapshot, cluster-state and observer-event streams, endpoint stdout, adapter `/data`, original API Jobs/Pods/Nodes, images and source/configuration. Freeze file lengths before archiving a still-writing stream; ordinary tar can fail because active files grow. Retain incomplete trailing-record diagnostics and wait for completed-profile emission before cleanup.

Use new evidence directories and unique namespaces. A failed collector or monitor does not automatically invalidate independently continuous endpoint/observer data, but eligibility must be established from preserved restarts, coverage, complete profiles, workload fidelity and final cleanup. The failed/recovered seed46 and seed47 attempts document these distinctions. Never silently replace failed captures with successful ones under the same artifact path.

Use the large evidence volume for archives/build scratch. Root and controller disks have less headroom. Preserve source artifacts before deleting experiment Jobs, namespaces or dedicated remote directories. Final infrastructure and cleanup checks are recorded in the evidence validation. All five VMs remain running, the three workers are uncordoned and the control-plane taint remains. The endpoint replay was stopped before these experiments and is restored to that stopped state; start and check it explicitly before the next capture.

## Controlled OpenDC run reference

Use the [README](README.md#direct-controlled-opendc-execution) for builds and CLI entry points. Set `OPENDC_RUNTIME=fns-demo` for every host-side FNS step, including collection and evaluation; its default remains the preserved legacy engine. Omitting it caused a collector failure even though the native runner had succeeded.

Local Docker execution needs `--hostname opendc-controlled --add-host opendc-controlled:127.0.0.1`, executable scratch `--tmpfs /tmp:rw,exec,size=256m`, and the retained one-CPU/two-GiB limits. A noexec scratch mount breaks native Parquet compression. Run as the evidence directory's owner and mount inputs read-only. The synthetic controlled fixture is separate from the calibrated application workload.

For Kubernetes, use a dedicated `/var/tmp/fns-opendc-NAME` on the control-plane VM, inputs under `inputs`, and writable `results` owned by UID/GID 1000 with mode 0755. Verify exact staged image identity, placement, execution validation and collection before deleting resources. `collection.json` and native validated records matter in addition to process exit. Do not infer execution cost from the example CSV's maximum task timestamp.

## Manual run reference

Start with a ready forecast including simulation inputs, its original observer directory and explicit worker configuration. Use `opendc_scenarios.py prepare --initialization-mode pinned-trace` with the matching FNS runtime/image, then the batch runner or native single-experiment runner. `opendc_validation.py prepare/evaluate` is for unchanged observations; it rejects action variants rather than pooling them as forecast samples. Controlled action evidence has its own validator and report path.

The [README](README.md#manual-provisional-scenario-workflow) gives concise commands; overnight `COMMANDS.md` records the exact local preparation, native execution, physical capture and report recipes. Choose new paths when reproducing them. Do not execute an old evidence harness against its recorded original destination.

Use repository-pinned Black 22.12.0 at 100 columns and Pylint 2.15.8 on task-owned Python. The current analysis/forecast environment is `/tmp/fns-forecast-venv/bin/python` (system default Python is older); PDF inspection uses `/tmp/fns-analysis-venv/bin/python`. Tool paths and full verification commands are in the evidence. Review useful docstrings and real regressions; accepted historical lint findings do not authorize a new broad cleanup.
