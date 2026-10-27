# Continuum Host Privilege Boundary

Current execution runs repository scripts as the normal user, never root.
See `docs/smoke_runner_isolation.md` for setup and commands and
`docs/rework_milestone_release_plan.md` for approved scope.
Factual runtime claims remain in `docs/release_certification_matrix.md`.

The previous separate smoke account, dedicated repo sync and installed
`continuum-hostctl`/`run-continuum-smoke` workflow is retired as an active
interface. Do not regenerate, reinstall or add replacement privileged wrappers.
Historical evidence keeps its original commands; it is not a current procedure.

## Ordinary runtime

Use `sh scripts/test/setup_agent_host.sh verify` and
`sh scripts/test/run_smoke_host.sh <scenario>` as your normal user.
These scripts create no account, sudoers rule or installed helper and perform
no privilege escalation. Libvirt/KVM and Docker group access are high trust;
normal-user execution is not isolation from the operator's home or credentials.

Do not grant blanket sudo, sudo shell/interpreter access, CAP_FOWNER or
automatic recursive ownership repair. Never execute mutable repository
Python/shell/Ansible code as root. Guest provisioning's existing privilege
model is distinct from controller-side script execution.

## Approved one-time migration

The user explicitly authorized migration to matthijs on node4 and node3,
private evidence preservation and removal of the old account/helpers after
replacement verification. Existing host administrative access was discovered,
not newly granted. Keep one-time administration bounded to reviewed exact
paths and identities, using trusted system commands with explicit arguments.
Do not turn it into product host-management or recovery machinery.

Before identity changes, freeze numeric path metadata, modes and ACLs, preserve
private old-home and helper snapshots, verify archive contents/checksums and
record excluded disks. Preserve valid peer disk metadata through runtime
validation. Before deleting an account, audit its remaining owned paths and
named/default ACLs, resolve only approved exact targets, and reconfirm that no
process/domain needs it. Removing account records while leaving live numeric
UID/ACL references risks future UID reuse.

## Sandbox differences

If host and sandbox disagree about ownership, groups, setuid or mount access,
inspect both contexts before changing host permissions. A sandbox denial is
not evidence that sudoers or filesystem permissions need broadening.
Use a narrowly justified host escalation only for actions already authorized.
Otherwise report the exact blocked action. Do not weaken sandbox or sudoers
policy to make an unattended goal proceed.

Private keys, archives, logs, generated runtime state and machine overrides
stay outside Git. Removal records must state exact targets and recoverability.
