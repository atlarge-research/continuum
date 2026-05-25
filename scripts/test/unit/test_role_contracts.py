"""Regression tests for Ansible role task contracts."""

from pathlib import Path
import unittest

import yaml


class DockerSetupRoleTests(unittest.TestCase):
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

    def test_kubeedge_cluster_playbook_verifies_edge_readiness(self):
        repo_root = Path(__file__).resolve().parents[3]
        playbook_path = repo_root / "playbooks/resource_manager/kubeedge_cluster.yml"
        playbook = yaml.safe_load(playbook_path.read_text(encoding="utf-8"))

        self.assertEqual(playbook[-1]["name"], "Verify KubeEdge edge readiness")
        readiness_task = playbook[-1]["tasks"][0]
        self.assertIn("kubectl get nodes", readiness_task["ansible.builtin.shell"])
        self.assertIn("expected_edges", readiness_task["ansible.builtin.shell"])
        self.assertEqual(readiness_task["environment"]["KUBECONFIG"], "/etc/kubernetes/admin.conf")


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
        self.assertEqual(launch_task["when"], "app_k8s_job_deploy_apply | bool")

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

        self.assertEqual(image_role["role"], "openfaas_deploy")
        self.assertEqual(image_role["vars"]["app_openfaas_deploy_scale_max"], 5)
        self.assertEqual(signal_role["role"], "openfaas_deploy")
        self.assertEqual(signal_role["vars"]["app_openfaas_deploy_scale_max"], 3)
