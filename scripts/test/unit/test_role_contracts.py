from pathlib import Path
import re
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

    def test_k8s_control_plane_waits_for_cri_before_kubeadm_init(self):
        repo_root = Path(__file__).resolve().parents[3]
        task_path = repo_root / "roles/resource_manager/k8s_control_plane/tasks/main.yml"
        tasks = yaml.safe_load(task_path.read_text(encoding="utf-8"))
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
