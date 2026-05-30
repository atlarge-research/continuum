# Agent Sudo Boundaries

This document records the safe pattern for giving an agent narrowly scoped host
permissions when Continuum work needs operations outside the repository
sandbox.

The default answer is still: do not give the agent blanket sudo access. Use a
root-owned wrapper with an explicit sudoers entry for exactly one command.

## Quick Response For Future Agents

When an agent asks for new sudo access, resolve it in this order:

1. Check whether the existing allowlisted commands already cover the task:

   ```bash
   sudo -n /usr/local/bin/continuum-hostctl ...
   sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke ...
   ```

2. If the task is not covered, do not add direct sudo access to a repo script,
   shell, Python, Ansible, package manager, service manager, or editor.
3. Add one root-owned wrapper outside the repo, normally under
   `/usr/local/sbin`, with strict internal argument validation.
4. If the wrapper uses a repo file, pin and verify that file's SHA-256 before
   using it.
5. Add one sudoers entry for that exact root-owned wrapper path.
6. Validate with `visudo -cf` and one `sudo -n <wrapper>` command.
7. Update this document and the relevant Continuum skill or handoff document.

The user does not need to call `skill-creator` for ordinary troubleshooting.
Agents should use the repo-local sudo guidance in this document, and create or
refresh `.codex/skills/continuum-safe-sudo/SKILL.md` only when `.codex/skills`
is writable.

## 1. Why This Exists

Some Continuum workflows need host privileges:

1. refreshing installed helpers under `/usr/local/bin`,
2. syncing a dedicated runner repository under `/srv/continuum/repo`,
3. using libvirt/KVM through a dedicated runner account,
4. priming host-local caches for VM-backed certification runs.

Those operations should not be exposed as arbitrary `sudo sh ...` on files in a
mutable checkout. A repository file can change between review and execution.
The safe boundary is a root-owned command outside the repo that performs a
small, audited action.

## 2. Required Pattern

Use this model for any new agent sudo capability:

1. The allowed command lives outside the repo, usually under `/usr/local/sbin`
   or `/usr/local/bin`.
2. The allowed command is owned by `root:root` and is not writable by the agent
   user.
3. The sudoers rule grants `NOPASSWD` for that exact path only. If arguments
   are needed, the target command must validate a small allowlisted argument
   set internally.
4. The command takes either no arguments or that small allowlisted argument set.
5. If the command consumes a repo script, it verifies the script checksum before
   executing or generating anything from it.
6. The command fails closed on checksum mismatch, unsupported arguments, missing
   prerequisites, or unexpected ownership.
7. The agent uses `sudo -n` so failures are noninteractive and visible.

Do not grant sudoers access to:

1. a shell, Python, Ansible, or editor binary,
2. a mutable repo-local script,
3. a command with arbitrary subcommands,
4. `sudoedit`,
5. wildcard paths or arguments to commands that do not perform their own
   strict allowlist checks,
6. package managers or service managers unless a root-owned wrapper constrains
   the exact operation.

## 3. Current Continuum Agent Sudo Contract

Continuum currently uses two installed host commands for agent-driven VM smoke
and certification work:

```bash
sudo -n /usr/local/bin/continuum-hostctl ...
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke ...
```

The sudoers rule may allow arguments after those two root-owned paths so the
agent can pass a scenario name or a host-helper subcommand. The safety boundary
is still narrow because the allowed path is fixed and the helper implements its
own subcommand allowlist. Do not interpret this as permission to add a wildcard
sudoers rule for a shell, interpreter, repo-local script, or arbitrary binary.

The host-helper subcommands intended for agent use are the ones exposed by:

```bash
sudo -n /usr/local/bin/continuum-hostctl show-config
sudo -n /usr/local/bin/continuum-hostctl sync-repo
sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated
sudo -n /usr/local/bin/continuum-hostctl install-wrapper dedicated /mnt/sdc/continuum_smoke
sudo -n /usr/local/bin/continuum-hostctl relocate-smoke-root /mnt/sdc/continuum_smoke --replace-source-with-symlink
sudo -n /usr/local/bin/continuum-hostctl verify
sudo -n /usr/local/bin/continuum-hostctl prime-registry-cache --suite <suite>
```

The runner command is intended for named suites and bounded diagnostics:

```bash
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke <suite>
sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke debug-playbook <suite> <playbook> ...
```

For `debug-playbook`, use only read-only diagnostics unless the user explicitly
approves the exact mutating command.

If the installed helper is stale, the operator can refresh it with:

```bash
sh /home/matthijs/continuum/scripts/test/setup_agent_host.sh install-hostctl
sudo -n /usr/local/bin/continuum-hostctl verify
```

Do not add extra mode arguments to `install-hostctl`; `install` takes an
optional mode, but `install-hostctl` does not.

## 4. Continuum Host Helper Refresh

The host-helper refresh case uses this pattern:

1. Review the repo script that emits the helper:
   `scripts/test/setup_agent_host.sh`.
2. Compute its hash:

   ```bash
   sha256sum /home/matthijs/continuum/scripts/test/setup_agent_host.sh
   ```

3. Create a root-owned wrapper at
   `/usr/local/sbin/continuum-refresh-hostctl` with that hash pinned in
   `EXPECTED_SHA256`.
4. Add exactly this sudoers capability:

   ```text
   matthijs ALL=(root) NOPASSWD: /usr/local/sbin/continuum-refresh-hostctl
   ```

5. The agent may then run only:

   ```bash
   sudo -n /usr/local/sbin/continuum-refresh-hostctl
   ```

The wrapper should regenerate `/usr/local/bin/continuum-hostctl` by running:

```bash
sh /home/matthijs/continuum/scripts/test/setup_agent_host.sh print-hostctl-script
```

and then installing the generated file with `/usr/bin/install` and
`/usr/bin/chown`.

If `setup_agent_host.sh` changes, the wrapper must fail until an operator
reviews the change and updates the pinned hash. That is intentional.

After the refresh has been applied and `/usr/local/bin/continuum-hostctl`
contains the required stable verbs, `/usr/local/sbin/continuum-refresh-hostctl`
is optional bootstrap machinery rather than part of the normal agent workflow.
If the host no longer needs that refresh path, remove both the sudoers entry for
the refresh wrapper and the wrapper file itself from an operator shell. Agents
should keep using the stable `continuum-hostctl` verbs and should not request
broad sudo solely to delete bootstrap files.

## 5. Template

Use this as a starting point for similar one-command refresh wrappers:

```sh
#!/bin/sh
set -eu

REPO_ROOT=/home/matthijs/continuum
SOURCE_SCRIPT="$REPO_ROOT/path/to/reviewed-script.sh"
EXPECTED_SHA256=replace_with_reviewed_sha256

actual_sha256=$(/usr/bin/sha256sum "$SOURCE_SCRIPT" | /usr/bin/awk '{print $1}')
if [ "$actual_sha256" != "$EXPECTED_SHA256" ]; then
  echo "Refusing to run: source checksum mismatch" >&2
  echo "Expected: $EXPECTED_SHA256" >&2
  echo "Actual:   $actual_sha256" >&2
  exit 1
fi

# Perform one bounded operation here. Prefer absolute paths for host commands.
```

Install it as root:

```bash
sudo install -m 0755 wrapper.sh /usr/local/sbin/example-wrapper
sudo chown root:root /usr/local/sbin/example-wrapper
```

Add sudoers:

```bash
printf '%s\n' 'matthijs ALL=(root) NOPASSWD: /usr/local/sbin/example-wrapper' \
  | sudo tee /etc/sudoers.d/example-wrapper >/dev/null
sudo chmod 0440 /etc/sudoers.d/example-wrapper
sudo visudo -cf /etc/sudoers.d/example-wrapper
```

Agent-side verification:

```bash
sudo -n /usr/local/sbin/example-wrapper
```

## 6. Diagnosing Sandbox Differences

The operator shell and the agent sandbox can see different mount and executable
metadata. Check both contexts before changing host permissions.

For Git write problems:

```bash
findmnt -T /home/matthijs/continuum/.git -o TARGET,SOURCE,FSTYPE,OPTIONS
git add --dry-run <path>
```

In this repository, `.git` is expected to be the `.git/` directory at the
repository root, not a `.git` pointer file. Git needs write access inside that
directory, especially to `.git/index`, `.git/objects`, and refs for staging and
committing. If the operator shell shows the filesystem as writable but the
agent sandbox reports a read-only mount, that is a sandbox mount issue, not a
normal file-permission issue. If `git add` and `git commit` work, no `.git`
permission fix is needed.

For sudo problems:

```bash
stat -c '%u %g %a %A %n' /usr/bin/sudo
sudo -n /usr/local/bin/continuum-hostctl verify
```

If generic sudo reports invalid ownership in the agent sandbox, do not broaden
sudoers to compensate. Keep using the exact narrow helper commands that work,
or have the operator run the root-owned setup step manually.

## 7. Documentation Requirement

Any new sudo capability for agents must be documented with:

1. the exact command the agent may run,
2. the root-owned wrapper path,
3. the sudoers file path,
4. the reviewed source or generated artifact,
5. the verification command,
6. the failure mode when the reviewed source changes.

## 8. Suggested Agent Skill

The `.codex/skills` directory may be read-only in some agent sessions. If this
file does not exist yet, future agents do not need the user to call the
system-level skill-creator explicitly; they can create the repo-local skill
from the body below when `.codex/skills` is writable. Until then, agents should
read this document and `.codex/skills/continuum-smoke-host-runner/SKILL.md`.

Target path:

```text
.codex/skills/continuum-safe-sudo/SKILL.md
```

Skill body:

````markdown
---
name: continuum-safe-sudo
description: Use when an agent needs, audits, documents, or troubleshoots narrow sudo access for Continuum host operations, including root-owned wrappers, sudoers allowlists, checksum-pinned repo scripts, sudo -n commands, and sandbox-versus-host permission differences.
---

# Continuum Safe Sudo

Use this skill when work might require host privileges. The default policy is:
do not request broad sudo. Use one root-owned wrapper with one exact sudoers
entry.

## First Read

1. `AGENTS.md`
2. `docs/agent_sudo_boundaries.md`
3. For smoke-runner work, also read `docs/smoke_runner_isolation.md` and
   `.codex/skills/continuum-smoke-host-runner/SKILL.md`.

## Rules

1. Never ask for blanket sudo, `sudo sh` on a mutable repo script, wildcard
   sudoers rules, or sudo access to shells/interpreters/editors.
2. Prefer an existing root-owned helper:
   - `sudo -n /usr/local/bin/continuum-hostctl ...`
   - `sudo -n -u continuum-smoke /usr/local/bin/run-continuum-smoke ...`
3. For a new capability, propose a root-owned wrapper outside the repo, usually
   under `/usr/local/sbin`.
4. If the wrapper depends on a repo file, require a pinned SHA-256 check before
   executing or generating anything from that repo file.
5. Use `sudo -n` only. Noninteractive failure is expected and should be reported.
6. Document the exact command, sudoers path, wrapper path, verification command,
   and failure mode.

## Wrapper Pattern

Use this shape:

```sh
#!/bin/sh
set -eu

SOURCE=/home/matthijs/continuum/path/to/reviewed-file
EXPECTED_SHA256=replace_with_reviewed_sha256

actual_sha256=$(/usr/bin/sha256sum "$SOURCE" | /usr/bin/awk '{print $1}')
if [ "$actual_sha256" != "$EXPECTED_SHA256" ]; then
  echo "Refusing to run: source checksum mismatch" >&2
  exit 1
fi

# One bounded root action with absolute command paths.
```

The sudoers entry should name exactly that wrapper:

```text
matthijs ALL=(root) NOPASSWD: /usr/local/sbin/example-wrapper
```

Validate with:

```bash
sudo visudo -cf /etc/sudoers.d/example-wrapper
sudo -n /usr/local/sbin/example-wrapper
```

## Continuum Host Helper Refresh

For refreshing `/usr/local/bin/continuum-hostctl`, the intended command is:

```bash
sudo -n /usr/local/sbin/continuum-refresh-hostctl
```

The wrapper should checksum-pin:

```text
/home/matthijs/continuum/scripts/test/setup_agent_host.sh
```

and install only the output of:

```bash
sh /home/matthijs/continuum/scripts/test/setup_agent_host.sh print-hostctl-script
```

Do not sudo the repo script directly.

After a successful refresh, this wrapper is not required for day-to-day smoke
execution. Prefer removing stale refresh wrappers and their sudoers entries
from an operator shell once the installed `continuum-hostctl` has the required
stable verbs.

## Diagnostics

If `.git` or sudo behavior differs between the user's shell and the agent:

```bash
findmnt -T /home/matthijs/continuum/.git -o TARGET,SOURCE,FSTYPE,OPTIONS
mount | rg ' on / '
git status --short
stat -c '%u %g %a %A %n' /usr/bin/sudo
```

Git needs `.git` writes for staging/committing. If `git add` works, no Git
permission fix is needed even if mount diagnostics are confusing.

If `sudo -n ...` fails before sudoers are evaluated with:

```text
sudo: /usr/bin/sudo must be owned by uid 0 and have the setuid bit set
```

check the agent mount namespace before changing sudoers:

```bash
mount | rg ' on / '
stat -c '%U %G %a %A %n' /usr/bin/sudo
```

When `/` is mounted with `nosuid` inside the agent session, the setuid bit on
`/usr/bin/sudo` is deliberately ignored. That is a session or harness boundary,
not evidence that the narrow sudoers rule is wrong. In that state, either run
the approved root-wrapper command from an operator shell that does not have
`nosuid`, or restart the agent session with a mount namespace that permits
setuid sudo. Do not broaden sudoers to compensate for a `nosuid` mount.
````
