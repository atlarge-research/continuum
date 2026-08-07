"""\
Define Machine object and functions to work with this object
The Machine object represents a physical machine used to run this benchmark
"""

import fcntl  # Linux-only, which is OK for Continuum deployments
import getpass
import logging
import os
import random
import re
import shlex
import subprocess
import sys
import threading
import time

# -----------------------------
# Helper utilities
# -----------------------------


def _shlex_join(argv):
    """Fallback for shlex.join() on Python <3.8

    Args:
        argv (list(str)): List of arguments to join

    Returns:
        str: Joined arguments
    """
    try:
        return shlex.join(argv)
    except AttributeError:
        return " ".join(shlex.quote(a) for a in argv)


def _normalize_commands(command, shell):
    """Normalize 'command' into a list of commands.

    Returned format:
      - list[str] if shell==True  (each element is a shell command string)
      - list[list[str]] if shell==False (each element is argv list)

    Args:
        command (str or list(str)): Command to normalize
        shell (bool): If True, return a list of shell commands

    Returns:
        list(str) or list(list(str)): Normalized command
    """
    if command is None:
        return []

    # Single command string
    if isinstance(command, str):
        if shell:
            return [command]
        # shell=False: split if needed (safe default; preserves single-word too)
        return [shlex.split(command) if any(c.isspace() for c in command) else [command]]

    # Already a list
    if not isinstance(command, list) or len(command) == 0:
        return []

    # A flat string list is one argv command. Token contents never determine command shape.
    if all(isinstance(x, str) for x in command) and not shell:
        return [command]

    # Otherwise it's a list of commands (each element either str or argv list)
    normalized = []
    for c in command:
        if isinstance(c, str):
            if shell:
                normalized.append(c)
            else:
                normalized.append(shlex.split(c) if any(ch.isspace() for ch in c) else [c])
        elif isinstance(c, list) and all(isinstance(x, str) for x in c):
            if shell:
                normalized.append(_shlex_join(c))
            else:
                normalized.append(c)
        else:
            raise TypeError(f"Unsupported command element type: {type(c)}")
    return normalized


def _ssh_target_host(target):
    """Return host/IP component from ssh target.

    Args:
        target (str): SSH target

    Returns:
        str: Host/IP component from ssh target
    """
    if not target:
        return None
    return target.split("@")[-1]


def _classify_ssh_error(stderr_lines, stdout_lines):
    """Classify SSH error type based primarily on stderr (fallback to stdout).

    Args:
        stderr_lines (list(str)): List of stderr lines
        stdout_lines (list(str)): List of stdout lines

    Returns:
        str: SSH error type
    """
    lines = (stderr_lines or []) + (stdout_lines or [])
    if not lines:
        return None

    combined = " ".join(lines).lower()

    # Host key issues
    hostkey_patterns = [
        "remote host identification has changed",
        "host key verification failed",
        "possible dns spoofing detected",
        "offending key",
        "offending ecdsa key",
        "offending ed25519 key",
    ]
    if any(p in combined for p in hostkey_patterns):
        return "hostkey"

    # Auth issues
    auth_patterns = [
        "permission denied",
        "publickey",
        "authentication failed",
        "too many authentication failures",
    ]
    if any(p in combined for p in auth_patterns):
        return "auth"

    # Transient connectivity issues
    transient_patterns = [
        "connection timed out",
        "connection reset by peer",
        "broken pipe",
        "no route to host",
        "connection closed",
        "connection refused",
        "network is unreachable",
        "could not resolve hostname",
        "operation timed out",
        "kex_exchange_identification",
        "connection aborted",
    ]
    if any(p in combined for p in transient_patterns):
        return "transient"

    return None


def _locked_known_hosts_update(known_hosts_path, fn):
    """Acquire an exclusive lock on known_hosts while mutating it.

    Args:
        known_hosts_path (str): Path to known_hosts file
        fn (function): Function to execute with the lock
    """
    os.makedirs(os.path.dirname(known_hosts_path), exist_ok=True)
    # a+ ensures file exists
    with open(known_hosts_path, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            fn()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def _repair_known_hosts(known_hosts_path, host):
    """Remove stale known_hosts entry and re-scan host key.

    Note: We keep this as a pragmatic 'self-healing' step, but we do it under a file lock
    and without shell=True to reduce surprises/races.

    Args:
        known_hosts_path (str): Path to known_hosts file
        host (str): Host to remove and re-scan
    """
    if not host:
        return

    def _do():
        subprocess.run(
            ["ssh-keygen", "-f", known_hosts_path, "-R", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        scan = subprocess.run(
            ["ssh-keyscan", "-H", host],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if scan.stdout:
            with open(known_hosts_path, "a", encoding="utf-8") as out:
                out.write(scan.stdout.decode("utf-8", errors="replace"))

    _locked_known_hosts_update(known_hosts_path, _do)


def _async_reap(process, desc=""):
    """Reap a child process without blocking the caller.

    Args:
        process (subprocess.Popen): Process to reap
        desc (str): Description of the process
    """

    def _waiter():
        try:
            process.wait()
        except Exception as e:
            logging.debug("Async reap failed for %s: %s", desc, e)

    t = threading.Thread(target=_waiter, daemon=True)
    t.start()


def _backoff_seconds(attempt, cap=30.0):
    """Exponential backoff with jitter; attempt starts at 1.

    Args:
        attempt (int): Attempt number
        cap (float): Maximum backoff time

    Returns:
        float: Backoff time in seconds
    """
    base = min(cap, 2**attempt)
    jitter = random.uniform(0, 0.25 * base)
    return base + jitter


# -----------------------------
# Machine class
# -----------------------------


class Machine:
    """The Machine object represent one physical machine Continuum runs on.
    The object includes all information about the machine, mainly info on
    the virtual machines that run on that particular physical machine.
    """

    def __init__(self, name, is_local):
        """Initialize the object

        Args:
            name (str): Name of this node, also functions as ssh target
            is_local (bool): Is this the machine on which the benchmark is started by the user
        """
        self.name = name
        self.is_local = is_local

        # Name with only alphanumeric characters
        self.name_sanitized = re.sub(r"\W+", "", name)

        # Assume user@ip as name for remote nodes
        if is_local:
            self.user = str(getpass.getuser())
            self.ip = ""
        else:
            self.user = name.split("@")[0]
            self.ip = name.split("@")[1]

        # Cores on this machine
        self.cores = 0

        # VM info
        self.cloud_controller = 0
        self.clouds = 0
        self.edges = 0
        self.endpoints = 0

        self.cloud_controller_ips = []
        self.cloud_ips = []
        self.edge_ips = []
        self.endpoint_ips = []
        self.base_ips = []

        # Internal IPs, used for communication between VMs
        self.cloud_controller_ips_internal = []
        self.cloud_ips_internal = []
        self.edge_ips_internal = []
        self.endpoint_ips_internal = []

        self.cloud_controller_names = []
        self.cloud_names = []
        self.edge_names = []
        self.endpoint_names = []
        self.base_names = []

    def __repr__(self):
        """Returns this string when called as print(machine_object)"""
        return """
[ MACHINE NAME: %20s ]
IS_LOCAL                    %s
NAME_SANITIZED              %s
USER                        %s
IP                          %s
CORES                       %i
CLOUD_CONTROLLER            %i
CLOUDS                      %i
EDGES                       %i
ENDPOINTS                   %i
CLOUD_CONTROLLER_IPS (int)  %s (%s)
CLOUD_IPS (int)             %s (%s)
EDGE_IPS (int)              %s (%s)
ENDPOINT_IPS (int)          %s (%s)
BASE_IPS                    %s
CLOUD_CONTROLLER_NAMES      %s
CLOUD_NAMES                 %s
EDGE_NAMES                  %s
ENDPOINT_NAMES              %s
BASE_NAMES                  %s""" % (
            self.name,
            str(self.is_local),
            self.name_sanitized,
            self.user,
            self.ip,
            self.cores,
            self.cloud_controller,
            self.clouds,
            self.edges,
            self.endpoints,
            ", ".join(self.cloud_controller_ips),
            ", ".join(self.cloud_controller_ips_internal),
            ", ".join(self.cloud_ips),
            ", ".join(self.cloud_ips_internal),
            ", ".join(self.edge_ips),
            ", ".join(self.edge_ips_internal),
            ", ".join(self.endpoint_ips),
            ", ".join(self.endpoint_ips_internal),
            ", ".join(self.base_ips),
            ", ".join(self.cloud_controller_names),
            ", ".join(self.cloud_names),
            ", ".join(self.edge_names),
            ", ".join(self.endpoint_names),
            ", ".join(self.base_names),
        )

    def process(
        self,
        config,
        command,
        shell=False,
        env=None,
        ssh=None,
        ssh_key=True,
        retryonoutput=False,
        wait=True,
    ):
        """Execute a process using subprocess, return the output/error of the process.

        Args:
            command (str or list): command(s) to be executed
            config (dict): Parsed configuration
            shell (bool): run locally via /bin/bash if True
            env (dict): env vars
            ssh (str or list[str]): SSH target(s) for running inside VM(s)
            ssh_key (bool): Use the custom SSH key for VMs
            retryonoutput (bool): Retry on empty output
            wait (bool): If False, return immediately (used for nohup/& patterns)

        Returns:
            list([output_lines, error_lines]) one per command
        """
        executable = "/bin/bash" if shell else None

        commands = _normalize_commands(command, shell=shell)
        if not commands:
            return [] if not wait else []

        # Expand ssh targets to per-command list
        ssh_targets = [None] * len(commands)
        if ssh is not None:
            if isinstance(ssh, str):
                ssh = [ssh]
            if len(ssh) == 1 and len(commands) > 1:
                ssh = ssh * len(commands)
            if len(commands) == 1 and len(ssh) > 1:
                commands = commands * len(ssh)
                ssh_targets = [None] * len(commands)

            # known_hosts handling (default: user's file, to stay compatible with Ansible/SSH behavior)
            home = config.get("home", os.path.expanduser("~"))
            known_hosts = config.get(
                "ssh_known_hosts_file",
                os.path.join(home, ".ssh", "known_hosts"),
            )

            # SSH options
            connect_timeout = str(config.get("ssh_connect_timeout", 10))
            alive_interval = str(config.get("ssh_server_alive_interval", 5))
            alive_count = str(config.get("ssh_server_alive_count_max", 3))

            strict_hkc = config.get("ssh_strict_host_key_checking", "accept-new")

            for i, (c, s) in enumerate(zip(commands, ssh)):
                if s is None:
                    continue
                if self.is_local and s == self.name:
                    # can't ssh to the machine you're already on
                    continue

                # IMPORTANT: options MUST come before destination
                ssh_argv = [
                    "ssh",
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    f"ConnectTimeout={connect_timeout}",
                    "-o",
                    f"ServerAliveInterval={alive_interval}",
                    "-o",
                    f"ServerAliveCountMax={alive_count}",
                    "-o",
                    f"UserKnownHostsFile={known_hosts}",
                    "-o",
                    f"StrictHostKeyChecking={strict_hkc}",
                ]
                if ssh_key and s != self.name:
                    ssh_argv += ["-i", config["ssh_key"]]

                # remote command portion
                if shell:
                    # local shell=True => entire local command must be a string
                    remote_cmd = c if isinstance(c, str) else _shlex_join(c)
                    full_argv = ssh_argv + [s, remote_cmd]
                    commands[i] = _shlex_join(full_argv)  # safe string for local bash
                else:
                    # local shell=False => argv list
                    remote_argv = (
                        c
                        if isinstance(c, list)
                        else (shlex.split(c) if any(ch.isspace() for ch in c) else [c])
                    )
                    commands[i] = ssh_argv + [s] + remote_argv

                ssh_targets[i] = s

        # Execute all commands, max 100 at a time
        batchsize = 100
        outputs = [None] * len(commands)
        rcs = [None] * len(commands)

        def _run_indices(indices, do_wait):
            """Run a batch of commands.

            Args:
                indices (list(int)): List of indices to run
                do_wait (bool): If True, wait for the commands to complete
            """
            for i in range(0, len(indices), batchsize):
                batch_indices = indices[i : i + batchsize]
                processes = []

                for idx in batch_indices:
                    c = commands[idx]
                    logging.debug("Start subprocess: %s", c)
                    p = subprocess.Popen(
                        c,
                        shell=shell,
                        executable=executable,
                        env=env,
                        stdout=subprocess.PIPE if do_wait else subprocess.DEVNULL,
                        stderr=subprocess.PIPE if do_wait else subprocess.DEVNULL,
                    )
                    processes.append((idx, p))

                if not do_wait:
                    # Do not block, but ensure children are reaped eventually
                    for idx, p in processes:
                        _async_reap(p, desc=str(commands[idx])[:80])
                    continue

                for idx, p in processes:
                    stdout, stderr = p.communicate()
                    rcs[idx] = p.returncode

                    out_lines = (
                        stdout.decode("utf-8", errors="replace").split("\n") if stdout else []
                    )
                    err_lines = (
                        stderr.decode("utf-8", errors="replace").split("\n") if stderr else []
                    )

                    if out_lines and out_lines[-1] == "":
                        out_lines = out_lines[:-1]
                    if err_lines and err_lines[-1] == "":
                        err_lines = err_lines[:-1]

                    outputs[idx] = [out_lines, err_lines]

        all_indices = list(range(len(commands)))
        _run_indices(all_indices, do_wait=wait)

        if not wait:
            # preserve current semantics: fire-and-forget returns empty list
            return []

        # Retry policy (configurable via config keys, but defaults keep behavior compact)
        max_transient_retries = int(config.get("ssh_transient_retries", 3))
        max_hostkey_retries = int(config.get("ssh_hostkey_retries", 2))
        max_auth_retries = int(config.get("ssh_auth_retries", 1))
        max_output_retries = int(config.get("output_retries", 5))

        transient_counts = {i: 0 for i in all_indices}
        hostkey_counts = {i: 0 for i in all_indices}
        auth_counts = {i: 0 for i in all_indices}
        output_counts = {i: 0 for i in all_indices}

        while True:
            retry_indices = []
            max_attempt_for_sleep = 0
            any_sleep = False

            for idx in all_indices:
                out, err = outputs[idx]
                rc = rcs[idx]

                # Only retry failures (except retryonoutput behaviour)
                is_failure = (rc is None) or (rc != 0)

                # Retry on empty output (even if rc==0) when explicitly requested
                if retryonoutput and (not out) and output_counts[idx] < max_output_retries:
                    output_counts[idx] += 1
                    retry_indices.append(idx)
                    any_sleep = True
                    max_attempt_for_sleep = max(max_attempt_for_sleep, output_counts[idx])
                    continue

                # SSH-specific retries
                target = ssh_targets[idx]
                if not target or not is_failure:
                    continue

                err_type = _classify_ssh_error(err, out)
                if not err_type:
                    continue

                host = _ssh_target_host(target)

                if err_type == "transient" and transient_counts[idx] < max_transient_retries:
                    transient_counts[idx] += 1
                    retry_indices.append(idx)
                    any_sleep = True
                    max_attempt_for_sleep = max(max_attempt_for_sleep, transient_counts[idx])

                elif err_type == "hostkey" and hostkey_counts[idx] < max_hostkey_retries:
                    hostkey_counts[idx] += 1
                    # Repair known_hosts for this host and retry
                    home = config.get("home", os.path.expanduser("~"))
                    known_hosts = config.get(
                        "ssh_known_hosts_file",
                        os.path.join(home, ".ssh", "known_hosts"),
                    )
                    logging.warning("SSH hostkey issue for %s; repairing %s", host, known_hosts)
                    _repair_known_hosts(known_hosts, host)
                    retry_indices.append(idx)
                    any_sleep = True
                    max_attempt_for_sleep = max(max_attempt_for_sleep, hostkey_counts[idx])

                elif err_type == "auth" and auth_counts[idx] < max_auth_retries:
                    auth_counts[idx] += 1
                    # One retry only; if it keeps failing, surface it clearly.
                    logging.warning(
                        "SSH auth issue for %s; retrying (%d/%d)",
                        host,
                        auth_counts[idx],
                        max_auth_retries,
                    )
                    retry_indices.append(idx)
                    any_sleep = True
                    max_attempt_for_sleep = max(max_attempt_for_sleep, auth_counts[idx])

            if not retry_indices:
                break

            sleep_s = _backoff_seconds(max_attempt_for_sleep, cap=30.0) if any_sleep else 0.0
            logging.warning(
                "Retrying %d command(s) in %.1fs (attempt=%d)",
                len(retry_indices),
                sleep_s,
                max_attempt_for_sleep,
            )
            time.sleep(sleep_s)

            _run_indices(retry_indices, do_wait=True)

        for idx in all_indices:
            out, err = outputs[idx]
            rc = rcs[idx]
            if rc in (None, 0):
                continue

            has_explicit_failure = any("FAILED!" in line for line in out)
            if has_explicit_failure:
                continue

            command_text = commands[idx] if shell else _shlex_join(commands[idx])
            err = list(err)
            synthetic = "Command exited with non-zero return code %s: %s" % (rc, command_text)
            if synthetic not in err:
                err.append(synthetic)
            outputs[idx] = [out, err]

        return outputs

    def check_hardware(self, config):
        """Get the amount of physical cores for this machine. This automatically functions as
        reachability check for this machine.

        Args:
            config (dict): Parsed configuration
        """
        # Cloud providers have seemingly unlimited cores
        if config["infrastructure"]["provider"] in ["gcp", "aws"]:
            self.cores = 100000
            return

        logging.info("Check hardware of node %s", self.name)
        cmd = "lscpu"

        if self.is_local:
            output, error = self.process(config, [cmd])[0]
        else:
            output, error = self.process(config, [cmd], ssh=self.name, ssh_key=False)[0]

        if not output:
            logging.error("".join(error))
            sys.exit(1)

        threads = -1
        threads_per_core = -1
        for line in output:
            if line.startswith("CPU(s):"):
                threads = int(line.split(":")[-1])
            if line.startswith("Thread(s) per core:"):
                threads_per_core = int(line.split(":")[-1])

        if threads == -1 or threads_per_core == -1:
            logging.error("Command did not produce the expected output: %s", "".join(output))
            sys.exit(1)

        logging.debug("Threads: %s | Threads_per_core: %s", threads, threads_per_core)
        self.cores = int(threads / threads_per_core)

    def copy_files(self, config, source, dest, recursive=False):
        """Copy files from host machine to destination machine.

        Args:
            config (dict): Parsed configuration
            source (str): Source file or directory
            dest (str): Destination file or directory
            recursive (bool, optional): Copy recursively. Defaults to False

        Returns:
            list(list(str), list(str)): Return a list of [output, error] lists, one per command.
        """
        rec = ""
        if recursive:
            rec = "-r "

        if self.is_local:
            command = ["cp " + rec + source + " " + dest]
        else:
            command = ["scp " + rec + source + " " + dest]

        return self.process(config, command, shell=True)[0]


def make_machine_objects(config):
    """Initialize machine objects

    Args:
        config (dict): Parsed configuration

    Returns:
        list(Machine object): List of machine objects representing physical machines
    """
    logging.info("Initialize machine objects")
    names = ["local"] + config["infrastructure"]["external_physical_machines"]
    return [Machine(name, "local" in name) for name in names]


def remove_idle(machines, nodes_per_machine):
    """Remove (physical) machines that won't be used.

    Args:
        machines (list(Machine object)): List of machine objects representing physical machines
        nodes_per_machine (list(set)): List of 'cloud', 'edge', 'endpoint' sets containing
            the number of those machines per physical node

    Returns:
        tuple(list(Machine object), list(set)): Tuple containing the updated list of physical
            machines and the updated list of 'cloud', 'edge', 'endpoint' sets containing the number
            of those machines per physical node
    """
    logging.info("Update machine list based on whether they will actually be used")
    new_machines = []
    new_nodes_per_machine = []
    for machine, nodes in zip(machines, nodes_per_machine):
        if nodes["cloud"] + nodes["edge"] + nodes["endpoint"] > 0:
            new_machines.append(machine)
            new_nodes_per_machine.append(nodes)

    m1 = "" if len(machines) <= 1 else "s"
    m2 = "" if len(new_machines) <= 1 else "s"
    logging.debug(
        "User offered %i machine%s, we will use %i machine%s",
        len(machines),
        m1,
        len(new_machines),
        m2,
    )
    return (new_machines, new_nodes_per_machine)


def gather_ssh(config, machines):
    """Get a list of all VM name@ip for SSH, save to config for easy access

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.debug("Get SSH targets of controllers/workers")

    config["cloud_ssh"] = []
    config["edge_ssh"] = []
    config["endpoint_ssh"] = []

    for machine in machines:
        for name, ip in zip(
            machine.cloud_controller_names + machine.cloud_names,
            machine.cloud_controller_ips + machine.cloud_ips,
        ):
            config["cloud_ssh"].append(name + "@" + ip)

        for name, ip in zip(machine.edge_names, machine.edge_ips):
            config["edge_ssh"].append(name + "@" + ip)

        for name, ip in zip(machine.endpoint_names, machine.endpoint_ips):
            config["endpoint_ssh"].append(name + "@" + ip)

    logging.debug("Cloud SSH: %s", ", ".join(config["cloud_ssh"]))
    logging.debug("Edge SSH: %s", ", ".join(config["edge_ssh"]))
    logging.debug("Endpoint SSH: %s", ", ".join(config["endpoint_ssh"]))


def gather_ips(config, machines):
    """Get a list of all VM ips, save to config for easy access

    Args:
        config (dict): Parsed configuration
        machines (list(Machine object)): List of machine objects representing physical machines
    """
    logging.debug("Get IP addresses of controllers/workers")

    config["control_ips"] = [ip for machine in machines for ip in machine.cloud_controller_ips]
    config["cloud_ips"] = [ip for machine in machines for ip in machine.cloud_ips]
    config["edge_ips"] = [ip for machine in machines for ip in machine.edge_ips]
    config["endpoint_ips"] = [ip for machine in machines for ip in machine.endpoint_ips]
    config["base_ips"] = [ip for machine in machines for ip in machine.base_ips]

    config["control_ips_internal"] = [
        ip for machine in machines for ip in machine.cloud_controller_ips_internal
    ]
    config["cloud_ips_internal"] = [ip for machine in machines for ip in machine.cloud_ips_internal]
    config["edge_ips_internal"] = [ip for machine in machines for ip in machine.edge_ips_internal]
    config["endpoint_ips_internal"] = [
        ip for machine in machines for ip in machine.endpoint_ips_internal
    ]

    logging.debug("Control IPs: %s", ", ".join(config["control_ips"]))
    logging.debug("Cloud IPs: %s", ", ".join(config["cloud_ips"]))
    logging.debug("Edge IPs: %s", ", ".join(config["edge_ips"]))
    logging.debug("Endpoint IPs: %s", ", ".join(config["endpoint_ips"]))
    logging.debug("Base IPs: %s", ", ".join(config["base_ips"]))


def print_schedule(machines):
    """Print the VM to physical machine scheduling"""
    logging.info("-" * 78)
    logging.info("Schedule of VMs and containers on physical machines")
    logging.info("-" * 78)

    logging.info("%-30s %-15s %-15s %-15s", "Machine", "Cloud nodes", "Edge nodes", "Endpoints")

    for machine in machines:
        logging.info(
            "%-30s %-15s %-15s %-15s",
            machine.name,
            machine.cloud_controller + machine.clouds,
            machine.edges,
            machine.endpoints,
        )

    logging.info("-" * 78)
