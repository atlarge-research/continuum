"""Regression tests for Ansible role task contracts."""

from pathlib import Path
import unittest

import yaml


class DockerSetupRoleTests(unittest.TestCase):
    def test_docker_setup_selects_engine_family_from_package_state(self):
        repo_root = Path(__file__).resolve().parents[2]
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
        repo_root = Path(__file__).resolve().parents[2]
        defaults_path = repo_root / "roles/resource_manager/docker_setup/defaults/main.yml"
        defaults = yaml.safe_load(defaults_path.read_text(encoding="utf-8"))

        self.assertEqual(defaults["rm_docker_setup_ubuntu_engine_packages"], ["docker.io"])
        self.assertEqual(
            defaults["rm_docker_setup_upstream_engine_packages"],
            ["docker-ce", "docker-ce-cli"],
        )


class EndpointInstallPlaybookTests(unittest.TestCase):
    def test_endpoint_install_includes_mosquitto_before_endpoint_runtime(self):
        repo_root = Path(__file__).resolve().parents[2]
        playbook_path = repo_root / "playbooks/resource_manager/endpoint_install.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        self.assertIsInstance(playbook, list)
        self.assertEqual(len(playbook), 1)

        roles = [entry["role"] if isinstance(entry, dict) else entry for entry in playbook[0]["roles"]]
        self.assertIn("mosquitto", roles)
        self.assertLess(roles.index("mosquitto"), roles.index("endpoint_runtime"))


class KubernetesPrereqsRoleTests(unittest.TestCase):
    def test_k8s_prereqs_installs_python_client_for_ansible_modules(self):
        repo_root = Path(__file__).resolve().parents[2]
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
        repo_root = Path(__file__).resolve().parents[2]
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


class BenchmarkLaunchPlaybookTests(unittest.TestCase):
    def test_image_classification_kubernetes_launch_uses_kubectl_apply(self):
        repo_root = Path(__file__).resolve().parents[2]
        playbook_path = (
            repo_root / "application/image_classification/launch_benchmark_kubernetes.yml"
        )
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        tasks = playbook[0]["tasks"]
        launch_task = next(task for task in tasks if task.get("name") == "Launch jobs")
        self.assertIn("ansible.builtin.command", launch_task)
        self.assertEqual(
            launch_task["ansible.builtin.command"]["cmd"],
            "kubectl apply -f /home/{{ username }}/jobs",
        )
        self.assertEqual(launch_task["register"], "launch_jobs_result")
        self.assertIn("launch_jobs_result.stdout", launch_task["changed_when"])
        self.assertEqual(
            launch_task["environment"]["KUBECONFIG"],
            "/etc/kubernetes/admin.conf",
        )

    def test_text_translation_kubernetes_launch_uses_kubectl_apply(self):
        repo_root = Path(__file__).resolve().parents[2]
        playbook_path = (
            repo_root / "application/text_translation/launch_benchmark_kubernetes.yml"
        )
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        tasks = playbook[0]["tasks"]
        launch_task = next(task for task in tasks if task.get("name") == "Launch jobs")
        self.assertIn("ansible.builtin.command", launch_task)
        self.assertEqual(
            launch_task["ansible.builtin.command"]["cmd"],
            "kubectl apply -f /home/{{ username }}/jobs",
        )
        self.assertEqual(launch_task["register"], "launch_jobs_result")
        self.assertIn("launch_jobs_result.stdout", launch_task["changed_when"])
        self.assertEqual(
            launch_task["environment"]["KUBECONFIG"],
            "/etc/kubernetes/admin.conf",
        )
