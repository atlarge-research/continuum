from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml


class QemuImageRoleTests(unittest.TestCase):
    def _load_tasks(self, role_name):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/infrastructure" / role_name / "tasks/main.yml"
        return yaml.safe_load(task_path.read_text(encoding="utf-8"))

    def _task_names(self, tasks):
        names = []
        for task in tasks:
            names.append(task.get("name"))
            names.extend(self._task_names(task.get("block", [])))
        return names

    def test_qemu_os_image_grants_libvirt_access_to_generated_qcow2(self):
        tasks = self._load_tasks("qemu_os_image")
        names = self._task_names(tasks)

        self.assertIn("Set Ubuntu qcow2 mode for libvirt access", names)
        self.assertIn("Grant kvm group ACL on Ubuntu qcow2 image", names)

    def test_qemu_base_image_grants_libvirt_access_to_generated_disks(self):
        tasks = self._load_tasks("qemu_base_image")
        names = self._task_names(tasks)

        self.assertIn("Set base qcow2 mode for libvirt access", names)
        self.assertIn("Grant kvm group ACL on base qcow2 image", names)
        self.assertIn("Set base cloud-init disk mode for libvirt access", names)
        self.assertIn("Grant kvm group ACL on base cloud-init disk", names)

    def test_qemu_vm_image_grants_libvirt_access_to_generated_disks(self):
        tasks = self._load_tasks("qemu_vm_image")
        names = self._task_names(tasks)

        self.assertIn("Set VM qcow2 modes for libvirt access", names)
        self.assertIn("Grant kvm group ACL on VM qcow2 images", names)
        self.assertIn("Set VM cloud-init disk modes for libvirt access", names)
        self.assertIn("Grant kvm group ACL on VM cloud-init disks", names)



@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class QemuBaseImageExecutionTests(unittest.TestCase):
    """Execute the role in a disposable local slot with strict, inert disk tools."""

    def _fixture(self, root, failure=""):
        slot = root / "slot"
        images = slot / ".continuum/images"
        images.mkdir(parents=True)
        (images / "ubuntu2004.qcow2").write_bytes(b"backing")
        (slot / ".continuum/user_data_base.yml").write_bytes(b"user-data")
        binaries = root / "bin"
        binaries.mkdir()
        log = root / "calls.jsonl"
        script = """#!%s
import json
import os
from pathlib import Path
import sys

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
images = Path(os.environ["TEST_SLOT"]) / ".continuum/images"
if tool == "qemu-img":
    assert args == ["create", "-f", "qcow2", "-F", "qcow2", "-b",
                    str(images / "ubuntu2004.qcow2"), str(images / "base.qcow2")], args
elif tool == "cloud-localds":
    assert args == [str(images / "user_data_base.img"),
                    str(images.parent / "user_data_base.yml")], args
elif tool == "setfacl":
    assert args[:2] == ["-m", "g:kvm:rw"] and len(args) == 3, args
    assert args[2] in [str(images / "base.qcow2"), str(images / "user_data_base.img")], args
else:
    raise AssertionError(tool)
with open(os.environ["TEST_CALLS"], "a") as filep:
    filep.write(json.dumps([tool, args]) + "\\n")
if tool == os.environ.get("TEST_FAILURE"):
    print("simulated " + tool + " failure", file=sys.stderr)
    sys.exit(7)
if tool != "setfacl":
    target = Path(args[-1] if tool == "qemu-img" else args[0])
    target.write_bytes(tool.encode())
    target.chmod(0o600)
""" % sys.executable
        for name in ("qemu-img", "cloud-localds", "setfacl"):
            binary = binaries / name
            binary.write_text(script, encoding="utf-8")
            binary.chmod(0o700)
        play = root / "play.yml"
        play.write_text(yaml.safe_dump([{
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "become": False,
            "vars": {"base_path": str(slot), "image_name": "base",
                     "ansible_python_interpreter": sys.executable},
            "environment": {
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                "TEST_SLOT": str(slot), "TEST_CALLS": str(log), "TEST_FAILURE": failure,
            },
            "roles": ["qemu_base_image"],
        }]), encoding="utf-8")
        env = dict(os.environ)
        config = root / "ansible.cfg"
        config.write_text("[defaults]\n", encoding="utf-8")
        env.update({
            "ANSIBLE_CONFIG": str(config), "ANSIBLE_BECOME": "False",
            "ANSIBLE_ROLES_PATH": str(Path(__file__).resolve().parents[3] / "roles/infrastructure"),
            "ANSIBLE_LOCAL_TEMP": str(root / "ansible-local"),
            "ANSIBLE_REMOTE_TMP": str(root / "ansible-remote"),
            "ANSIBLE_NOCOLOR": "1",
        })
        return images, log, play, env

    def _run(self, play, env):
        return subprocess.run(
            [shutil.which("ansible-playbook"), "-i", "localhost,", str(play)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=60, check=False,
        )

    def test_only_new_disks_receive_mode_and_acl_initialization(self):
        with tempfile.TemporaryDirectory() as tempdir:
            images, log, play, env = self._fixture(Path(tempdir))
            result = self._run(play, env)
            self.assertEqual(result.returncode, 0, result.stdout)
            disks = [images / "base.qcow2", images / "user_data_base.img"]
            for disk in disks:
                self.assertEqual(disk.stat().st_mode & 0o777, 0o664)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual([call[0] for call in calls],
                             ["qemu-img", "setfacl", "cloud-localds", "setfacl"])
            for disk, mode in zip(disks, (0o640, 0o600)):
                disk.chmod(mode)
            before = [(disk.read_bytes(), disk.stat()) for disk in disks]
            log.write_text("")
            result = self._run(play, env)
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(log.read_text(), "")
            for disk, (contents, metadata) in zip(disks, before):
                self.assertEqual(disk.read_bytes(), contents)
                after = disk.stat()
                self.assertEqual((after.st_uid, after.st_gid, after.st_mode),
                                 (metadata.st_uid, metadata.st_gid, metadata.st_mode))

    def test_creation_failures_report_original_operation_and_numeric_context(self):
        for failure in ("qemu-img", "cloud-localds"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tempdir:
                images, _log, play, env = self._fixture(Path(tempdir), failure)
                result = self._run(play, env)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                for token in ("simulated " + failure + " failure", str(images),
                              "uid", "gid", "mode", "operator", "ACL"):
                    self.assertIn(token, result.stdout)
                if failure == "cloud-localds":
                    self.assertEqual((images / "base.qcow2").stat().st_mode & 0o777, 0o664)


class DockerSetupRoleTests(unittest.TestCase):
    def _run_install_policy(self, root, scenario):
        """Run the real task retry policy with an inert apt-action boundary."""
        task_path = (Path(__file__).resolve().parents[3]
                     / "roles/resource_manager/docker_setup/tasks/main.yml")
        task = next(task for task in yaml.safe_load(task_path.read_text(encoding="utf-8"))
                    if task.get("name") == "Install docker engine package")
        production_retries = task.get("retries", 0)
        production_delay = task.get("delay", 0)
        task.pop("ansible.builtin.apt")
        calls = root / "calls"
        boundary = root / "inert_apt.py"
        boundary.write_text(r'''import sys
from pathlib import Path

calls = Path(sys.argv[1])
scenario = sys.argv[2]
attempt = int(calls.read_text()) + 1 if calls.exists() else 1
calls.write_text(str(attempt))
lock = ("E: Could not get lock /var/lib/dpkg/lock-frontend. "
        "It is held by process 2513 (unattended-upgr)\n"
        "E: Unable to acquire the dpkg frontend lock (/var/lib/dpkg/lock-frontend), "
        "is another process using it?")
if scenario == "success" or (scenario == "lock_once" and attempt > 1):
    print("inert installation succeeded")
    raise SystemExit(0)
errors = {
    "lock_once": (100, lock),
    "persistent_lock": (100, lock),
    "unrelated": (100, "E: Unable to locate package missing-docker"),
    "wrong_rc": (1, lock),
    "mixed_error": (100, lock + "\nE: Permission denied"),
    "other_holder": (100, lock.replace("unattended-upgr", "apt-get")),
    "other_path": (100, lock.replace("/var/lib/dpkg/lock-frontend", "/var/lib/apt/lists/lock")),
}
code, message = errors[scenario]
sys.stderr.write(message + "\n")
raise SystemExit(code)
''', encoding="utf-8")
        task["ansible.builtin.command"] = {
            "argv": [sys.executable, str(boundary), str(calls), scenario],
        }
        # Accelerate only timing/budget; retain the actual register/until policy.
        task["retries"] = min(production_retries, 2)
        task["delay"] = 0
        play = root / "play.yml"
        play.write_text(yaml.safe_dump([{
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "become": False, "vars": {"ansible_python_interpreter": sys.executable},
            "tasks": [task],
        }]), encoding="utf-8")
        config = root / "ansible.cfg"
        config.write_text("[defaults]\n", encoding="utf-8")
        env = dict(os.environ)
        env.pop("ANSIBLE_LOG_PATH", None)
        env.update({
            "ANSIBLE_CONFIG": str(config), "ANSIBLE_BECOME": "False",
            "ANSIBLE_LOCAL_TEMP": str(root / "ansible-local"),
            "ANSIBLE_REMOTE_TMP": str(root / "ansible-remote"),
            "ANSIBLE_STDOUT_CALLBACK": "default", "ANSIBLE_NOCOLOR": "1",
        })
        result = subprocess.run(
            [shutil.which("ansible-playbook"), "-i", "localhost,", str(play)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=60, check=False,
        )
        return result, int(calls.read_text()), production_retries, production_delay

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
    def test_docker_install_retries_observed_updater_lock_then_succeeds(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, calls, retries, delay = self._run_install_policy(Path(temporary), "lock_once")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(calls, 2)
            self.assertGreater(retries, 0)
            self.assertLessEqual(retries, 30)
            self.assertGreater(delay, 0)
            self.assertLessEqual(delay, 10)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
    def test_docker_install_success_does_not_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            result, calls, _retries, _delay = self._run_install_policy(Path(temporary), "success")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(calls, 1)

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
    def test_docker_install_preserves_fatal_errors_and_bounds_lock_retries(self):
        cases = (
            ("persistent_lock", 3, 100, "Could not get lock"),
            ("unrelated", 1, 100, "Unable to locate package"),
            ("wrong_rc", 1, 1, "Could not get lock"),
            ("mixed_error", 1, 100, "Permission denied"),
            ("other_holder", 1, 100, "apt-get"),
            ("other_path", 1, 100, "/var/lib/apt/lists/lock"),
        )
        for scenario, expected_calls, rc, diagnostic in cases:
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                result, calls, _retries, _delay = self._run_install_policy(
                    Path(temporary), scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertEqual(calls, expected_calls, result.stdout)
                self.assertIn(diagnostic, result.stdout)
                self.assertRegex(result.stdout, r'(?:"rc"\s*:\s*|rc:\s*)' + str(rc) + r'\b')

    def test_docker_setup_selects_engine_family_from_package_state(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/resource_manager/docker_setup/tasks/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))

        self.assertIsInstance(tasks, list)

        select_task = next(
            task
            for task in tasks
            if task.get("name") == "Select compatible docker engine packages"
        )
        set_fact = select_task["ansible.builtin.set_fact"]
        expression = set_fact["rm_docker_setup_engine_packages"]
        self.assertIn("rm_docker_setup_upstream_repo.stat.exists", expression)
        self.assertIn('"containerd.io" in (ansible_facts.packages | default({}))', expression)
        self.assertIn("rm_docker_setup_upstream_engine_packages", expression)
        self.assertIn("rm_docker_setup_ubuntu_engine_packages", expression)

        install_task = next(
            task for task in tasks if task.get("name") == "Install docker engine package"
        )
        self.assertEqual(
            install_task["ansible.builtin.apt"]["name"],
            "{{ rm_docker_setup_engine_packages }}",
        )

    def test_docker_setup_defaults_define_both_engine_package_sets(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/resource_manager/docker_setup/defaults/main.yml"
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))

        self.assertEqual(defaults["rm_docker_setup_ubuntu_engine_packages"], ["docker.io"])
        self.assertEqual(
            defaults["rm_docker_setup_upstream_engine_packages"],
            ["docker-ce", "docker-ce-cli"],
        )


class ContainerdSetupRoleTests(unittest.TestCase):
    def test_containerd_setup_fails_on_unreplaced_registry_placeholder(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/resource_manager/containerd_setup/tasks/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))

        self.assertIsInstance(tasks, list)

        check_task = next(
            task
            for task in tasks
            if task.get("name") == "Check containerd registry placeholder replacement"
        )
        self.assertEqual(
            check_task["ansible.builtin.command"]["cmd"],
            "grep -q REGISTRY-IP /etc/containerd/config.toml",
        )
        self.assertEqual(
            check_task["failed_when"],
            "rm_containerd_setup_registry_placeholder.rc > 1",
        )

        fail_task = next(
            task for task in tasks if task.get("name") == "Fail when containerd registry placeholder remains"
        )
        self.assertIn("REGISTRY-IP", fail_task["ansible.builtin.fail"]["msg"])
        self.assertEqual(fail_task["when"], "rm_containerd_setup_registry_placeholder.rc == 0")


class EndpointInstallPlaybookTests(unittest.TestCase):
    def test_endpoint_install_includes_mosquitto_before_endpoint_runtime(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/endpoint_install.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        self.assertIsInstance(playbook, list)
        self.assertEqual(len(playbook), 1)

        roles = [entry["role"] if isinstance(entry, dict) else entry for entry in playbook[0]["roles"]]
        self.assertIn("mosquitto", roles)
        self.assertLess(roles.index("mosquitto"), roles.index("endpoint_runtime"))
        self.assertEqual(playbook[0]["hosts"], "endpoints")

    def test_endpoint_base_install_targets_only_base_endpoint_hosts(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/endpoint_base_install.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        self.assertIsInstance(playbook, list)
        self.assertEqual(len(playbook), 1)

        roles = [entry["role"] if isinstance(entry, dict) else entry for entry in playbook[0]["roles"]]
        self.assertIn("mosquitto", roles)
        self.assertLess(roles.index("mosquitto"), roles.index("endpoint_runtime"))
        self.assertEqual(playbook[0]["hosts"], "base_endpoint")


class KubernetesBaseInstallPlaybookTests(unittest.TestCase):
    def test_k8s_base_install_includes_mosquitto_for_benchmark_workers(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/k8s_base_install.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        self.assertIsInstance(playbook, list)
        self.assertEqual(len(playbook), 1)

        roles = [entry["role"] if isinstance(entry, dict) else entry for entry in playbook[0]["roles"]]
        self.assertIn("containerd_setup", roles)
        self.assertIn("mosquitto", roles)
        self.assertLess(roles.index("containerd_setup"), roles.index("mosquitto"))


class KubernetesObservabilityRoleTests(unittest.TestCase):
    def test_observability_role_fetches_kube_prometheus_before_apply(self):
        repo_root = Path(__file__).resolve().parents[3]
        tasks_path = repo_root / "roles/resource_manager/k8s_observability/tasks/main.yml"
        defaults_path = repo_root / "roles/resource_manager/k8s_observability/defaults/main.yml"
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))

        self.assertIsInstance(tasks, list)
        self.assertGreaterEqual(len(tasks), 2)
        self.assertIn("ansible.builtin.git", tasks[0])
        self.assertIn("kube-prometheus", defaults["rm_k8s_observability_repo"])
        self.assertEqual(defaults["rm_k8s_observability_version"], "release-0.13")
        self.assertIn("manifests/setup", tasks[1]["ansible.builtin.command"])
        self.assertIn("--server-side", tasks[1]["ansible.builtin.command"])


@unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
class KubernetesObservabilityExecutionTests(unittest.TestCase):
    """Exercise the role policy without a cluster, sockets or shared Ansible state."""

    def _run_policy(self, root, scenario="success", external="192.0.2.2"):
        repo_root = Path(__file__).resolve().parents[3]
        source = repo_root / "roles/resource_manager/k8s_observability/tasks/main.yml"
        tasks = yaml.safe_load(source.read_text(encoding="utf-8"))[4:]
        trace = root / "calls.jsonl"
        binaries = root / "bin"
        actions = root / "actions"
        for path in (binaries, actions, root / "home", root / "tmp", root / "cp"):
            path.mkdir()
        boundary = r'''#!PYTHON
import json
import os
from pathlib import Path
import sys

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
trace = Path(os.environ["OBS_TRACE"])
scenario = os.environ["OBS_SCENARIO"]
events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
with trace.open("a") as out:
    out.write(json.dumps([tool, args, os.getpid()]) + "\n")
address = "192.0.2.2," + os.environ["OBS_EXTERNAL"]
commands = {
    "100": "kubectl port-forward --namespace=monitoring --address=" + address + " svc/grafana 3000:3000",
    "200": "kubectl port-forward --namespace=monitoring --address=" + address + " svc/prometheus-k8s 9090:9090",
}
if tool == "kubectl":
    if "wait" in args and "prometheus/k8s" in args and scenario in ("wait_failure", "diagnostic_failure"):
        print("original Prometheus readiness permission denied", file=sys.stderr)
        sys.exit(7)
    if "get" in args and scenario == "diagnostic_failure":
        print("diagnostic API unavailable", file=sys.stderr)
        sys.exit(8)
    print("condition met" if "wait" in args else "inert monitoring status")
elif tool == "pgrep":
    if scenario in ("spawn", "bind_failure"):
        sys.exit(1)
    print("100\n200" + ("\n300" if scenario == "duplicates" else ""))
elif tool == "ps":
    pid = args[args.index("-p") + 1]
    command = commands.get(pid, commands["100"] if pid == "300" else "")
    for event in events:
        if event[0] == "nohup" and str(event[2]) == pid:
            command = " ".join(event[1])
    owner = os.getuid()
    if scenario == "wrong_owner":
        owner += 1
    if scenario == "near_match":
        command += " --not-the-same-command"
    if scenario in ("vanished", "bind_failure") or not command:
        sys.exit(1)
    if "uid=" in args:
        print(str(owner) + " " + command)
    else:
        print(command)
elif tool == "nohup":
    print("bind: address already in use" if scenario == "bind_failure" else "inert forwarding log", file=sys.stderr)
elif tool == "tail":
    if scenario == "diagnostic_failure":
        print("diagnostic log unavailable", file=sys.stderr)
        sys.exit(9)
    path = Path(args[-1])
    print(path.read_text() if path.exists() else "no earlier forwarding log")
else:
    raise AssertionError(tool)
'''.replace("#!PYTHON", "#!" + sys.executable)
        for name in ("kubectl", "pgrep", "ps", "nohup", "tail"):
            path = binaries / name
            path.write_text(boundary, encoding="utf-8")
            path.chmod(0o700)
        (actions / "inert_uri.py").write_text(r'''import json
from pathlib import Path
from ansible.plugins.action import ActionBase

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        variables = task_vars or {}
        trace = Path(variables["obs_trace"])
        args = self._task.args
        scenario = variables["obs_scenario"]
        events = [json.loads(line) for line in trace.read_text().splitlines()] if trace.exists() else []
        previous = sum(event[0] == "uri" and event[1]["url"] == args["url"] for event in events)
        with trace.open("a") as out:
            out.write(json.dumps(["uri", args]) + "\n")
        grafana = ":3000/" in args["url"]
        status = 503 if ((scenario == "transient" and previous == 0)
                         or (scenario == "prometheus_http" and not grafana)
                         or (scenario == "grafana_http" and grafana)) else 200
        database = "failing" if scenario == "grafana_database" else "ok"
        return {"changed": False, "url": args["url"], "status": status,
                "json": {"database": database},
                "content": "inert health response", "msg": "inert HTTP status %s" % status,
                "failed": status != 200}
''', encoding="utf-8")

        def isolate(entries):
            for task in entries:
                for section in ("block", "rescue", "always"):
                    isolate(task.get(section, []))
                if "ansible.builtin.uri" in task:
                    self.assertEqual(task["ansible.builtin.uri"]["timeout"], 5)
                    self.assertEqual(task["retries"], 12)
                    self.assertEqual(task["delay"], 5)
                    task["inert_uri"] = task.pop("ansible.builtin.uri")
                    task["delay"] = 0

        isolate(tasks)
        # Redirect only the role's guest-local forwarding logs into the fixture.
        tasks = yaml.safe_load(yaml.safe_dump(tasks).replace(
            "/var/log/continuum-observability", str(root / "forward-logs")))
        play = root / "play.yml"
        play.write_text(yaml.safe_dump([{
            "hosts": "localhost", "connection": "local", "gather_facts": False,
            "become": False,
            "vars": {
                "ansible_python_interpreter": sys.executable,
                "rm_k8s_observability_cloud_ip": "192.0.2.2",
                "rm_k8s_observability_cloud_ip_external": external,
                "obs_trace": str(trace), "obs_scenario": scenario,
            },
            "environment": {
                "PATH": str(binaries) + os.pathsep + os.environ["PATH"],
                "OBS_TRACE": str(trace), "OBS_SCENARIO": scenario, "OBS_EXTERNAL": external,
            },
            "tasks": tasks,
        }]), encoding="utf-8")
        config = root / "ansible.cfg"
        config.write_text("[defaults]\n", encoding="utf-8")
        env = {
            "HOME": str(root / "home"), "TMPDIR": str(root / "tmp"),
            "PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1",
            "XDG_CACHE_HOME": str(root / "cache"),
            "ANSIBLE_CONFIG": str(config), "ANSIBLE_BECOME": "False",
            "ANSIBLE_LOCAL_TEMP": str(root / "ansible-local"),
            "ANSIBLE_REMOTE_TMP": str(root / "ansible-remote"),
            "ANSIBLE_SSH_CONTROL_PATH_DIR": str(root / "cp"),
            "ANSIBLE_ACTION_PLUGINS": str(actions),
            "ANSIBLE_LOG_PATH": str(root / "ansible.log"),
            "ANSIBLE_STDOUT_CALLBACK": "default", "ANSIBLE_NOCOLOR": "1",
        }
        ansible = Path(sys.executable).with_name("ansible-playbook")
        result = subprocess.run(
            [str(ansible) if ansible.exists() else shutil.which("ansible-playbook"),
             "-i", "localhost,", str(play)],
            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            timeout=60, check=False,
        )
        self.assertTrue(trace.exists(), result.stdout)
        events = [json.loads(line) for line in trace.read_text().splitlines()]
        return result, events

    def test_prometheus_wait_failure_cannot_report_success(self):
        """Missing Prometheus readiness must fail before forwarding or HTTP checks."""
        with tempfile.TemporaryDirectory() as temporary:
            result, events = self._run_policy(Path(temporary), "wait_failure")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("original Prometheus readiness permission denied", result.stdout)
            self.assertFalse(any(event[0] in ("nohup", "uri") for event in events))

    def test_readiness_checks_both_replicas_and_distinct_service_addresses(self):
        """Success requires each workload and each advertised health address."""
        for external, expected_urls in (("192.0.2.2", 2), ("192.0.2.3", 4)):
            with self.subTest(external=external), tempfile.TemporaryDirectory() as temporary:
                result, events = self._run_policy(Path(temporary), external=external)
                self.assertEqual(result.returncode, 0, result.stdout)
                waits = [event[1] for event in events if event[0] == "kubectl"
                         and "wait" in event[1]]
                self.assertEqual(len(waits), 2)
                self.assertIn("deployment/grafana", waits[0])
                self.assertIn("prometheus/k8s", waits[1])
                self.assertIn("--for=jsonpath={.status.availableReplicas}=2", waits[1])
                self.assertIn("--timeout=20m", waits[1])
                probes = [event[1] for event in events if event[0] == "uri"]
                self.assertEqual(len(probes), expected_urls)
                self.assertEqual(len({probe["url"] for probe in probes}), expected_urls)
                for probe in probes:
                    self.assertFalse(probe["use_proxy"])
                    self.assertEqual(probe["follow_redirects"], "none")
                self.assertFalse(any(event[0] == "nohup" for event in events))

    def test_http_failures_exhaust_attempt_budget_and_preserve_diagnostics(self):
        """HTTP success cannot substitute for a healthy Grafana database."""
        for scenario in ("grafana_http", "grafana_database", "prometheus_http"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                result, events = self._run_policy(Path(temporary), scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                probes = [event[1]["url"] for event in events if event[0] == "uri"]
                self.assertEqual(max(probes.count(url) for url in set(probes)), 13)
                self.assertIn("inert health response", result.stdout)
                self.assertTrue(any(event[0] == "tail" for event in events))

    def test_transient_health_failure_retries_then_succeeds(self):
        """Each service's independent policy retries a transient 503 once."""
        with tempfile.TemporaryDirectory() as temporary:
            result, events = self._run_policy(Path(temporary), "transient")
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual(sum(event[0] == "uri" for event in events), 4)

    def test_forward_identity_failures_cannot_be_hidden_by_healthy_http(self):
        """Reject duplicates, other users, near matches and vanished processes."""
        for scenario in ("duplicates", "wrong_owner", "near_match", "vanished"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                result, events = self._run_policy(Path(temporary), scenario)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                if scenario == "duplicates":
                    self.assertFalse(any(event[0] == "uri" for event in events))
                else:
                    self.assertEqual(sum(event[0] == "uri" for event in events), 2)
                if scenario in ("wrong_owner", "near_match"):
                    self.assertEqual(sum(event[0] == "nohup" for event in events), 2)

    def test_new_forward_logs_are_private_and_bind_failures_are_retained(self):
        """Spawn only missing forwards and retain startup stderr for diagnosis."""
        for scenario in ("spawn", "bind_failure"):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                logs = root / "forward-logs"
                logs.mkdir(mode=0o755)
                for name in ("grafana", "prometheus"):
                    (logs / (name + "-port-forward.log")).write_text("previous log\n")
                result, events = self._run_policy(root, scenario)
                if scenario == "spawn":
                    self.assertEqual(result.returncode, 0, result.stdout)
                    self.assertEqual(sum(event[0] == "nohup" for event in events), 2)
                else:
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("bind: address already in use", result.stdout)
                self.assertEqual(logs.stat().st_mode & 0o777, 0o700)
                self.assertEqual(len(list(logs.glob("*.log"))), 2)
                for log in logs.glob("*.log"):
                    self.assertEqual(log.stat().st_mode & 0o777, 0o600)
                    self.assertTrue(log.read_text().startswith("previous log\n"))
                    self.assertGreater(len(log.read_text()), len("previous log\n"))

    def test_diagnostic_failures_do_not_replace_original_error(self):
        """Unavailable API/log diagnostics cannot erase the readiness failure."""
        with tempfile.TemporaryDirectory() as temporary:
            result, _events = self._run_policy(Path(temporary), "diagnostic_failure")
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertIn("original Prometheus readiness permission denied", result.stdout)
            self.assertIn("diagnostic API unavailable", result.stdout)
            self.assertIn("diagnostic log unavailable", result.stdout)


class KubernetesPrereqsRoleTests(unittest.TestCase):
    def test_k8s_prereqs_installs_python_client_for_ansible_modules(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/resource_manager/k8s_prereqs/tasks/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))

        self.assertIsInstance(tasks, list)

        python_client_task = next(
            task
            for task in tasks
            if task.get("name") == "Install Kubernetes Python client for Ansible modules"
        )
        self.assertEqual(
            python_client_task["ansible.builtin.apt"]["name"],
            ["python3-kubernetes", "python3-jsonpatch"],
        )


class KubernetesControlPlaneRoleTests(unittest.TestCase):
    def test_k8s_control_plane_installs_python_client_for_runtime_k8s_tasks(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/resource_manager/k8s_control_plane/tasks/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))

        self.assertIsInstance(tasks, list)

        python_client_task = next(
            task
            for task in tasks
            if task.get("name")
            == "Install Kubernetes Python client for Ansible modules on control plane"
        )
        self.assertEqual(
            python_client_task["ansible.builtin.apt"]["name"],
            ["python3-kubernetes", "python3-jsonpatch"],
        )

    def test_k8s_control_plane_waits_for_cri_before_kubeadm_init(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/resource_manager/k8s_control_plane/tasks/main.yml"
        defaults_path = repo_root / "roles/resource_manager/k8s_control_plane/defaults/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        task_names = [task.get("name") for task in tasks]

        cri_task = next(
            task
            for task in tasks
            if task.get("name") == "Wait for containerd CRI endpoint before kubeadm init"
        )
        self.assertEqual(cri_task["ansible.builtin.command"], "crictl info")
        self.assertLess(
            task_names.index("Wait for containerd CRI endpoint before kubeadm init"),
            task_names.index("Initialize Kubernetes cluster with default kubeadm options"),
        )
        default_init_task = next(
            task
            for task in tasks
            if task.get("name") == "Initialize Kubernetes cluster with default kubeadm options"
        )
        default_init_command = default_init_task["ansible.builtin.command"]
        self.assertIn(
            "--kubernetes-version=v{{ rm_k8s_control_plane_kubeversion }}",
            default_init_command,
        )
        self.assertIn(
            "--image-repository={{ rm_k8s_control_plane_image_repository }}",
            default_init_command,
        )
        self.assertIn(
            "registry_ip | default(continuum_registry_ip | default(''))",
            defaults["rm_k8s_control_plane_registry_ip"],
        )
        self.assertIn(
            "continuum_resource_manager_type | default('')) in ['kubecontrol', 'kube_kata']",
            defaults["rm_k8s_control_plane_image_repository"],
        )

    def test_k8s_worker_join_waits_for_cri_before_join(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/resource_manager/k8s_worker_join/tasks/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))
        task_names = [task.get("name") for task in tasks]

        cri_task = next(
            task
            for task in tasks
            if task.get("name") == "Wait for containerd CRI endpoint before kubeadm join"
        )
        self.assertEqual(cri_task["ansible.builtin.command"], "crictl info")
        self.assertLess(
            task_names.index("Wait for containerd CRI endpoint before kubeadm join"),
            task_names.index("Execute cluster join command"),
        )

        join_task = next(
            task for task in tasks if task.get("name") == "Execute cluster join command"
        )
        self.assertIn("kubeadm reset --force", join_task["ansible.builtin.shell"])

    def test_k8s_cluster_playbook_serializes_worker_joins(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/k8s_cluster.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        worker_play = next(play for play in playbook if play.get("name") == "Join Kubernetes worker nodes")
        self.assertEqual(worker_play["serial"], 1)

    def test_kata_setup_installs_runtime_on_workers_and_runtimeclasses_on_controller(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/kata_setup.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        install_play = next(
            play for play in playbook if play.get("name") == "Install Kata runtime components"
        )
        runtimeclass_play = next(
            play for play in playbook if play.get("name") == "Register Kata runtime classes"
        )

        self.assertEqual(install_play["hosts"], "clouds:edges")
        self.assertEqual(
            [role["role"] for role in install_play["roles"]],
            ["kata_containers"],
        )
        self.assertEqual(runtimeclass_play["hosts"], "cloudcontroller")
        self.assertEqual(
            [role["role"] for role in runtimeclass_play["roles"]],
            ["kata_runtime_classes"],
        )

    def test_kata_containers_role_starts_legacy_jaeger_all_in_one(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/resource_manager/kata_containers/defaults/main.yml"
        task_path = repo_root / "roles/resource_manager/kata_containers/tasks/main.yml"
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))

        self.assertEqual(defaults["rm_kata_containers_jaeger_image"], "jaegertracing/all-in-one:1.47")

        include_docker = next(
            task for task in tasks if task.get("name") == "Include Docker setup for Jaeger tracing"
        )
        self.assertEqual(include_docker["ansible.builtin.include_role"]["name"], "docker_setup")

        resolve_task = next(task for task in tasks if task.get("name") == "Resolve Jaeger image reference")
        image_ref_expr = resolve_task["ansible.builtin.set_fact"]["rm_kata_containers_jaeger_image_ref"]
        self.assertIn("regex_replace('^[^/]+/', '')", image_ref_expr)

        run_task = next(task for task in tasks if task.get("name") == "Start Jaeger tracing container")
        argv = run_task["ansible.builtin.command"]["argv"]
        self.assertIn("COLLECTOR_ZIPKIN_HOST_PORT=:9411", argv)
        self.assertIn("COLLECTOR_OTLP_ENABLED=true", argv)
        for port in (
            "6831:6831/udp",
            "6832:6832/udp",
            "5778:5778",
            "16686:16686",
            "4317:4317",
            "4318:4318",
            "14250:14250",
            "14268:14268",
            "14269:14269",
            "9411:9411",
        ):
            self.assertIn(port, argv)
        self.assertIn("--query.max-clock-skew-adjustment=20s", argv)

        wait_task = next(task for task in tasks if task.get("name") == "Wait for Jaeger query API")
        self.assertEqual(wait_task["ansible.builtin.uri"]["url"], "http://127.0.0.1:16686/api/services")


class KubeEdgeRoleTests(unittest.TestCase):
    def test_kubeedge_prereqs_follow_profile_kubernetes_major_version(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/resource_manager/kubeedge_prereqs/defaults/main.yml"
        tasks_path = repo_root / "roles/resource_manager/kubeedge_prereqs/tasks/main.yml"
        defaults_text = defaults_path.read_text(encoding="utf-8")
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))

        self.assertIn("continuum_kubeversion_major", defaults_text)

        install_task = next(
            task for task in tasks if task.get("name") == "Install Kubernetes binaries for KubeEdge"
        )
        self.assertEqual(
            install_task["ansible.builtin.apt"]["name"],
            ["kubelet", "kubeadm", "kubectl"],
        )

    def test_kubeedge_prereqs_configure_containerd_registry_for_edgecore(self):
        repo_root = Path(__file__).resolve().parents[3]
        tasks_path = repo_root / "roles/resource_manager/kubeedge_prereqs/tasks/main.yml"
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))

        containerd_task = next(
            task
            for task in tasks
            if task.get("name") == "Include containerd setup role for KubeEdge image pulls"
        )
        self.assertEqual(containerd_task["ansible.builtin.include_role"]["name"], "containerd_setup")
        self.assertEqual(
            containerd_task["vars"]["rm_containerd_setup_registry_ip"],
            "{{ rm_kubeedge_prereqs_registry_ip }}",
        )
        self.assertEqual(
            containerd_task["vars"]["rm_containerd_setup_config_src"],
            "{{ continuum_repo_root }}/resource_manager/kubernetes/cloud/config.toml",
        )
        self.assertEqual(containerd_task["when"], "rm_kubeedge_prereqs_registry_ip | length > 0")

    def test_kubeedge_cluster_playbook_verifies_edge_readiness(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/kubeedge_cluster.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        edge_join_play = next(play for play in playbook if play.get("name") == "Join KubeEdge edge nodes")
        self.assertEqual(edge_join_play["serial"], 1)

        self.assertEqual(playbook[-1]["name"], "Verify KubeEdge edge readiness")
        readiness_task = playbook[-1]["tasks"][0]
        self.assertIn("kubectl get nodes", readiness_task["ansible.builtin.shell"])
        self.assertIn("expected_edges", readiness_task["ansible.builtin.shell"])
        self.assertEqual(readiness_task["environment"]["KUBECONFIG"], "/etc/kubernetes/admin.conf")

    def test_kubeedge_cloudcore_enables_edge_incluster_config_support(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/resource_manager/kubeedge_cloudcore/defaults/main.yml"
        tasks_path = repo_root / "roles/resource_manager/kubeedge_cloudcore/tasks/main.yml"
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))

        self.assertIs(defaults["rm_kubeedge_cloudcore_enable_incluster_config"], True)

        init_task = next(
            task for task in tasks if task.get("name") == "Initialize KubeEdge CloudCore"
        )
        init_command = init_task["ansible.builtin.command"]
        self.assertIn("cloudCore.modules.dynamicController.enable=true", init_command)
        self.assertIn("cloudCore.featureGates.requireAuthorization=true", init_command)

        flannel_configmap_task = next(
            task
            for task in tasks
            if task.get("name")
            == "Write KubeEdge flannel kubeconfig ConfigMap manifest"
        )
        flannel_configmap_content = flannel_configmap_task["ansible.builtin.copy"]["content"]
        self.assertIn("kubeconfig: |", flannel_configmap_content)
        self.assertIn("server: https://{{ rm_kubeedge_cloudcore_cloud_ip }}:6443", flannel_configmap_content)
        self.assertIn(
            "certificate-authority: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
            flannel_configmap_content,
        )
        self.assertIn("tokenFile: /var/run/secrets/kubernetes.io/serviceaccount/token", flannel_configmap_content)

        apply_configmap_task = next(
            task
            for task in tasks
            if task.get("name") == "Apply KubeEdge flannel kubeconfig ConfigMap"
        )
        self.assertEqual(
            apply_configmap_task["ansible.builtin.command"],
            "kubectl apply -f /tmp/continuum-kube-flannel-cfg.yaml",
        )

        flannel_api_task = next(
            task
            for task in tasks
            if task.get("name")
            == "Configure flannel kubeconfig file for KubeEdge edge pods"
        )
        flannel_api_argv = flannel_api_task["ansible.builtin.command"]["argv"]
        self.assertIn("patch", flannel_api_argv)
        self.assertIn("--type=json", flannel_api_argv)
        self.assertTrue(
            any("--kubeconfig-file=/etc/kube-flannel/kubeconfig" in arg for arg in flannel_api_argv)
        )
        self.assertFalse(any("--kube-api-url" in arg for arg in flannel_api_argv))

    def test_kubeedge_edge_join_enables_edge_incluster_config_support(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/resource_manager/kubeedge_edge_join/defaults/main.yml"
        tasks_path = repo_root / "roles/resource_manager/kubeedge_edge_join/tasks/main.yml"
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))
        task_names = {task.get("name") for task in tasks}
        join_task = next(task for task in tasks if task.get("name") == "Join edge node to CloudCore")

        self.assertIs(defaults["rm_kubeedge_edge_join_enable_incluster_config"], True)
        self.assertIn("--cgroupdriver=systemd", join_task["ansible.builtin.shell"])
        self.assertIn("keadm reset edge --force", join_task["ansible.builtin.shell"])
        self.assertIn("Enable requireAuthorization feature gate in edgecore config", task_names)
        self.assertIn("Enable metaServer in edgecore config", task_names)

    def test_kubeedge_edge_join_incluster_config_regexes_patch_generated_config(self):
        repo_root = Path(__file__).resolve().parents[3]
        tasks_path = repo_root / "roles/resource_manager/kubeedge_edge_join/tasks/main.yml"
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))
        tasks_by_name = {task.get("name"): task for task in tasks}
        config = """
apiVersion: edgecore.config.kubeedge.io/v1alpha2
kind: EdgeCore
featureGates:
  requireAuthorization: false
modules:
  edgeStream:
    enable: false
  metaManager:
    enable: true
    metaServer:
      enable: false
      server: 127.0.0.1:10550
"""

        for task_name in (
            "Enable requireAuthorization feature gate in edgecore config",
            "Enable metaServer in edgecore config",
        ):
            replace_args = tasks_by_name[task_name]["ansible.builtin.replace"]
            config = re.sub(replace_args["regexp"], replace_args["replace"], config)

        self.assertIn("featureGates:\n  requireAuthorization: true", config)
        self.assertIn("metaServer:\n      enable: true", config)


class BenchmarkLaunchPlaybookTests(unittest.TestCase):
    def _role_entry(self, relative_path):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / relative_path
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))
        roles = playbook[0]["roles"]
        self.assertEqual(len(roles), 1)
        return roles[0]

    def test_k8s_job_deploy_role_materializes_templates_and_kubectl_apply(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/application/k8s_job_deploy/tasks/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))

        self.assertIsInstance(tasks, list)
        copy_task = next(
            task
            for task in tasks
            if task.get("name") == "Create one-file-per-job Kubernetes files"
        )
        copy_args = copy_task["ansible.builtin.copy"]
        self.assertEqual(copy_args["src"], "{{ app_k8s_job_deploy_job_template_path }}")
        self.assertIs(copy_args["remote_src"], True)

        launch_task = next(task for task in tasks if task.get("name") == "Launch Kubernetes benchmark jobs")
        self.assertIn("ansible.builtin.command", launch_task)
        self.assertEqual(
            launch_task["ansible.builtin.command"]["cmd"],
            "kubectl apply -f {{ app_k8s_job_deploy_apply_path }}",
        )
        self.assertEqual(launch_task["register"], "app_k8s_job_deploy_launch")
        self.assertEqual(
            launch_task["environment"]["KUBECONFIG"],
            "{{ app_k8s_job_deploy_kubeconfig }}",
        )
        self.assertEqual(launch_task["when"], [
            "app_k8s_job_deploy_apply | bool", "app_k8s_job_deploy_labels | length == 0"
        ])

        owned_launch = next(task for task in tasks if task.get("name") ==
                            "Launch exactly the current owned Kubernetes benchmark files")
        self.assertEqual(owned_launch["ansible.builtin.command"]["argv"], [
            "kubectl", "--namespace=default", "apply", "-f",
            "{{ app_k8s_job_deploy_jobs_dir }}/job-{{ item }}.yaml",
        ])
        self.assertIn("app_k8s_job_deploy_labels | length > 0", owned_launch["when"])

    @unittest.skipUnless(shutil.which("ansible-playbook"), "ansible-playbook is required")
    def test_owned_job_role_applies_only_current_files_with_pod_labels(self):
        """Run the actual role against inert kubectl, leaving a stale file untouched."""
        with tempfile.TemporaryDirectory() as tempdir:
            root = Path(tempdir)
            jobs = root / "jobs"
            jobs.mkdir()
            stale = jobs / "job-99.yaml"
            stale.write_text("unrelated retained manifest", encoding="utf-8")
            binary = root / "kubectl"
            calls = root / "calls.jsonl"
            binary.write_text("#!%s\n" % sys.executable + '''import json
import os
import sys
with open(os.environ["TEST_CALLS"], "a", encoding="utf-8") as output:
    output.write(json.dumps(sys.argv[1:]) + "\\n")
print("job.batch/test created")
''', encoding="utf-8")
            binary.chmod(0o700)
            labels = {"continuum.io/benchmark-owner": "owner",
                      "continuum.io/benchmark-execution": "execution"}
            play = root / "play.yml"
            play.write_text(yaml.safe_dump([{
                "hosts": "localhost", "connection": "local", "gather_facts": False,
                "become": False,
                "vars": {"ansible_python_interpreter": sys.executable,
                         "app_name": "image-classification", "image": "worker:subscriber",
                         "replicas": 2, "app_k8s_job_deploy_layout": "one_file_per_job",
                         "app_k8s_job_deploy_apply": True,
                         "app_k8s_job_deploy_labels": labels,
                         "app_k8s_job_deploy_jobs_dir": str(jobs),
                         "app_k8s_job_deploy_job_template_path": str(root / "template.yaml")},
                "environment": {"PATH": str(root) + os.pathsep + os.environ["PATH"],
                                "TEST_CALLS": str(calls)},
                "roles": ["k8s_job_deploy"],
            }]), encoding="utf-8")
            config = root / "ansible.cfg"
            config.write_text("[defaults]\n", encoding="utf-8")
            env = dict(os.environ)
            env.pop("ANSIBLE_LOG_PATH", None)
            env.update({"ANSIBLE_CONFIG": str(config), "ANSIBLE_BECOME": "False",
                        "ANSIBLE_ROLES_PATH": str(Path(__file__).resolve().parents[3]
                                                  / "roles/application"),
                        "ANSIBLE_LOCAL_TEMP": str(root / "ansible-local"),
                        "ANSIBLE_REMOTE_TMP": str(root / "ansible-remote")})
            result = subprocess.run(
                [shutil.which("ansible-playbook"), "-i", "localhost,", str(play)], env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                timeout=60, check=False,
            )
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertEqual([json.loads(line) for line in calls.read_text().splitlines()], [
                ["--namespace=default", "apply", "-f", str(jobs / "job-1.yaml")],
                ["--namespace=default", "apply", "-f", str(jobs / "job-2.yaml")],
            ])
            for index in (1, 2):
                job = yaml.safe_load((jobs / ("job-%d.yaml" % index)).read_text())
                self.assertEqual(job["metadata"]["labels"], labels)
                self.assertEqual(job["spec"]["template"]["metadata"]["labels"], labels)
            self.assertEqual(stale.read_text(), "unrelated retained manifest")

    def test_image_classification_kubernetes_launch_uses_application_role(self):
        role = self._role_entry(
            "application/image_classification/launch_benchmark_kubernetes.yml"
        )
        self.assertEqual(role["role"], "k8s_job_deploy")
        vars_ = role["vars"]
        self.assertEqual(vars_["app_k8s_job_deploy_layout"], "one_file_per_job")
        self.assertIs(vars_["app_k8s_job_deploy_apply"], True)
        self.assertEqual(vars_["app_k8s_job_deploy_ports"], [1883])
        self.assertEqual(vars_["app_k8s_job_deploy_env"][0]["value_from_field_path"], "status.hostIP")

    def test_text_translation_kubernetes_launch_sets_ephemeral_storage(self):
        role = self._role_entry(
            "application/text_translation/launch_benchmark_kubernetes.yml"
        )
        self.assertEqual(role["role"], "k8s_job_deploy")
        vars_ = role["vars"]
        self.assertEqual(vars_["app_k8s_job_deploy_layout"], "one_file_per_job")
        self.assertIs(vars_["app_k8s_job_deploy_apply"], True)
        self.assertEqual(vars_["app_k8s_job_deploy_ephemeral_storage"], "12Gi")

    def test_kubeedge_launch_uses_k8s_job_role_instead_of_kubernetes_module(self):
        role = self._role_entry(
            "application/image_classification/launch_benchmark_kubeedge.yml"
        )
        self.assertEqual(role["role"], "k8s_job_deploy")
        self.assertIs(role["vars"]["app_k8s_job_deploy_apply"], True)
        self.assertEqual(role["vars"]["app_k8s_job_deploy_pull_policy"], "Always")

    def test_empty_file_mode_uses_render_only_one_file_role_variant(self):
        role = self._role_entry("application/empty/launch_benchmark_kubecontrol_file.yml")
        self.assertEqual(role["role"], "k8s_job_deploy")
        vars_ = role["vars"]
        self.assertEqual(vars_["app_k8s_job_deploy_layout"], "one_file_per_job")
        self.assertIs(vars_["app_k8s_job_deploy_index_template_metadata"], True)
        self.assertIs(vars_["app_k8s_job_deploy_index_container_name"], True)
        self.assertNotIn("app_k8s_job_deploy_apply", vars_)

    def test_openfaas_launch_playbooks_use_application_role(self):
        image_role = self._role_entry(
            "application/image_classification/launch_benchmark_openfaas.yml"
        )
        signal_role = self._role_entry("application/signal_classification/launch_benchmark_openfaas.yml")

        self.assertEqual(image_role["role"], "application/openfaas_deploy")
        self.assertEqual(image_role["vars"]["app_openfaas_deploy_scale_max"], 5)
        self.assertEqual(signal_role["role"], "application/openfaas_deploy")
        self.assertEqual(signal_role["vars"]["app_openfaas_deploy_scale_max"], 3)

    def test_openfaas_deploy_uses_versioned_stack_and_waits_for_function(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/application/openfaas_deploy/defaults/main.yml"
        tasks_path = repo_root / "roles/application/openfaas_deploy/tasks/main.yml"
        template_path = repo_root / "roles/application/openfaas_deploy/templates/function.yml.j2"

        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))
        template = template_path.read_text(encoding="utf-8")
        deploy_task = next(
            task for task in tasks if task.get("name") == "Launch OpenFaaS function"
        )
        wait_task = next(
            task for task in tasks if task.get("name") == "Wait for OpenFaaS function deployment"
        )

        self.assertEqual(defaults["app_openfaas_deploy_kubeconfig"], "/etc/kubernetes/admin.conf")
        self.assertIn("version: 1.0", template)
        self.assertIn("--gateway {{ app_openfaas_deploy_gateway }}", deploy_task["ansible.builtin.command"]["cmd"])
        self.assertIn(
            "deployment/{{ app_openfaas_deploy_app_name }}",
            wait_task["ansible.builtin.command"]["cmd"],
        )
        self.assertEqual(wait_task["environment"]["KUBECONFIG"], "{{ app_openfaas_deploy_kubeconfig }}")

    def test_openfaas_install_gateway_port_forward_is_endpoint_reachable(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/resource_manager/openfaas_install/defaults/main.yml"
        tasks_path = repo_root / "roles/resource_manager/openfaas_install/tasks/main.yml"

        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))
        install_task = next(
            task
            for task in tasks
            if task.get("name") == "Install OpenFaaS gateway port-forward service"
        )
        arkade_install_task = next(
            task for task in tasks if task.get("name") == "Install OpenFaaS CE with arkade"
        )
        content = install_task["ansible.builtin.copy"]["content"]

        self.assertEqual(defaults["rm_openfaas_install_gateway_address"], "0.0.0.0")
        self.assertEqual(defaults["rm_openfaas_install_retries"], 3)
        self.assertEqual(defaults["rm_openfaas_install_retry_delay"], 30)
        self.assertEqual(arkade_install_task["retries"], "{{ rm_openfaas_install_retries }}")
        self.assertEqual(arkade_install_task["delay"], "{{ rm_openfaas_install_retry_delay }}")
        self.assertEqual(arkade_install_task["until"], "openfaas_install_result.rc == 0")
        self.assertIn("--address {{ rm_openfaas_install_gateway_address }}", content)


class K8sMetricsServerRoleTests(unittest.TestCase):
    def test_metrics_role_stages_cluster_resource_collector_from_active_resource_manager(self):
        repo_root = Path(__file__).resolve().parents[3]
        defaults_path = repo_root / "roles/resource_manager/k8s_metrics_server/defaults/main.yml"
        tasks_path = repo_root / "roles/resource_manager/k8s_metrics_server/tasks/main.yml"
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))
        tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8"))

        self.assertEqual(
            defaults["rm_k8s_metrics_server_username"],
            "{{ username | default(continuum_username | default('ubuntu')) }}",
        )

        cluster_task = next(
            task
            for task in tasks
            if task.get("name") == "Stage Kubernetes cluster resource collector"
        )

        self.assertEqual(
            cluster_task["ansible.builtin.copy"]["src"],
            "{{ continuum_repo_root }}/resource_manager/{{ continuum_resource_manager_type }}/cloud/resource_usage.py",
        )
        self.assertEqual(
            cluster_task["ansible.builtin.copy"]["dest"],
            "/home/{{ rm_k8s_metrics_server_username }}/resource_usage.py",
        )
        self.assertEqual(cluster_task["ansible.builtin.copy"]["mode"], "0755")

    def test_metrics_playbook_stages_os_collector_on_all_cloud_nodes(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/k8s_metrics.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        os_play = next(
            play
            for play in playbook
            if play.get("name") == "Stage operating-system resource collector on cloud nodes"
        )
        os_task = os_play["tasks"][0]

        self.assertEqual(os_play["hosts"], "cloudcontroller:clouds")
        self.assertEqual(
            os_task["ansible.builtin.copy"]["src"],
            "{{ continuum_repo_root }}/resource_manager/{{ continuum_resource_manager_type }}/cloud/resource_usage_os.py",
        )
        self.assertEqual(
            os_task["ansible.builtin.copy"]["dest"],
            "/home/{{ username }}/resource_usage_os.py",
        )
        self.assertEqual(os_task["ansible.builtin.copy"]["mode"], "0755")
