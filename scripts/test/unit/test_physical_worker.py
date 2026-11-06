"""Regressions for physical-worker identity and transport."""

from argparse import Namespace
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import continuum
from infrastructure import infrastructure, machine as machine_module
from infrastructure.machine import Machine, make_machine_objects
from infrastructure.qemu import qemu


class PhysicalWorkerTests(unittest.TestCase):
    def test_remote_only_placement_creates_controller_key_before_exact_worker_transfer(self):
        owner = Machine("operator@worker.local", False)
        key = "/run/.continuum/ssh/id_rsa_continuum"
        config = {"ssh_key": key}
        with (
            mock.patch.object(infrastructure.os.path, "isfile", return_value=False),
            mock.patch.object(owner, "process", return_value=[[[], []]]) as controller,
            mock.patch.object(
                owner, "process_on_owner",
                side_effect=[[[["/run/.continuum/ssh/.upload.abc"], []]], [[[], []]]],
            ) as prepare,
            mock.patch.object(owner, "copy_to_worker", return_value=[[], []]) as transfer,
        ):
            calls = mock.Mock()
            calls.attach_mock(controller, "controller")
            calls.attach_mock(prepare, "prepare")
            calls.attach_mock(transfer, "transfer")
            infrastructure.create_keypair(config, [owner])
        self.assertEqual(
            [call[0] for call in calls.mock_calls],
            ["controller", "controller", "controller", "prepare", "transfer", "prepare"],
        )
        self.assertEqual(controller.call_args_list[0].args[1][0][0], "mkdir")
        self.assertEqual(controller.call_args_list[1].args[1][0][0], "ssh-keygen")
        self.assertEqual(controller.call_args_list[2].args[1],
                         [["chmod", "600", key], ["chmod", "600", key + ".pub"]])
        transfer.assert_called_once_with(
            config, [key, key + ".pub"], "/run/.continuum/ssh/.upload.abc/",
        )

    def test_failed_worker_transfer_never_replaces_the_existing_keypair(self):
        owner = Machine("operator@worker.local", False)
        key = "/run/.continuum/ssh/id_rsa_continuum"
        with (
            mock.patch.object(infrastructure.os.path, "isfile", return_value=True),
            mock.patch.object(owner, "process", return_value=[[[], []]]),
            mock.patch.object(
                owner, "process_on_owner",
                return_value=[[["/run/.continuum/ssh/.upload.abc"], []]],
            ) as worker,
            mock.patch.object(owner, "copy_to_worker", return_value=[[], ["connection closed"]])
            as transfer,
            self.assertRaises(SystemExit),
        ):
            infrastructure.create_keypair({"ssh_key": key}, [owner])
        worker.assert_called_once()
        self.assertNotIn("rm -f", worker.call_args.args[1][2])
        transfer.assert_called_once()

    def test_resume_checks_physical_worker_before_guest_and_image_operations(self):
        owner = Machine("operator@worker.local", False)
        config = {
            "infrastructure": {"provider": "qemu", "delete": True},
            "domains": {"run": {"targets": ["software"]}},
        }
        with (
            mock.patch.object(continuum.yaml_parser, "write_experiment_lock", return_value=None),
            mock.patch.object(continuum.infra_state, "load_resume_state", return_value=({}, [owner])),
            mock.patch.object(
                machine_module, "_run_bounded_command",
                return_value=[[[], ["Host key verification failed."]]],
            ) as run,
            mock.patch.object(machine_module, "validate_resume_ssh_reachability") as guest_check,
            mock.patch.object(continuum.image_registry, "prepare_runtime_images") as images,
            self.assertRaises(SystemExit),
        ):
            continuum.main(Namespace(config=config))
        self.assertIn("ControlPath=none", run.call_args.args[0])
        guest_check.assert_not_called()
        images.assert_not_called()

    @unittest.skipUnless(shutil.which("sftp") and Path("/usr/lib/openssh/sftp-server").is_file(),
                         "OpenSSH local SFTP harness unavailable")
    def test_sftp_paths_transfer_exact_literal_file(self):
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / 'literal[1]*" name'
            source.write_text("exact", encoding="utf-8")
            source.chmod(0o600)
            (Path(root) / 'literal1other" name').write_text("wrong", encoding="utf-8")
            destination = Path(root) / 'remote \\ "dir"'
            destination.mkdir()
            owner = Machine("operator@worker.local", False)

            def local_sftp(argv, *_args):
                result = subprocess.run(
                    ["sftp", "-D", "/usr/lib/openssh/sftp-server",
                     "-b", argv[argv.index("-b") + 1], "localhost"],
                    capture_output=True, text=True, check=False,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                return [[result.stdout.splitlines(), result.stderr.splitlines()]]

            with mock.patch.object(machine_module, "_run_bounded_command", side_effect=local_sftp):
                self.assertEqual(
                    owner.copy_to_worker({}, [str(source)], str(destination) + "/"), [[], []]
                )
            self.assertEqual((destination / source.name).read_bytes(), b"exact")
            self.assertEqual((destination / source.name).stat().st_mode & 0o777, 0o600)
            self.assertEqual(len(list(destination.iterdir())), 1)

    def test_remote_launch_does_not_replay_a_disconnected_mutation(self):
        owner = Machine("operator@worker.local", False)
        owner.cloud_names = ["cloud0_operator"]
        config = {"infrastructure": {"base_path": "/run path"}}
        with (
            mock.patch.object(qemu.time, "sleep"),
            mock.patch.object(machine_module.subprocess, "Popen", side_effect=AssertionError),
            mock.patch.object(
                machine_module, "_run_bounded_command",
                return_value=[[[], ["Connection to worker closed."]]],
            ) as run,
            self.assertRaisesRegex(RuntimeError, "worker.local.*Connection"),
        ):
            qemu.launch_vms(config, [owner])
        run.assert_called_once()
        argv = run.call_args.args[0]
        self.assertIn("ControlPath=none", argv)
        self.assertEqual(argv[-4:], ["--connect", "qemu:///system", "create",
                                     "'/run path/.continuum/domain_cloud0_operator.xml'"])

    def test_workspace_rejects_unverified_worker_using_fresh_ssh(self):
        owner = Machine("operator@worker.local", False)
        config = {"infrastructure": {"base_path": "/run path"}}
        for action in (infrastructure.delete_old_content, infrastructure.create_continuum_dir):
            with (
                self.subTest(action=action),
                mock.patch.object(
                    machine_module, "_run_bounded_command",
                    return_value=[[[], ["Host key verification failed."]]],
                ) as run,
                mock.patch.object(machine_module.subprocess, "Popen", side_effect=AssertionError),
                self.assertRaises(SystemExit),
            ):
                action(config, [owner])
            argv = run.call_args.args[0]
            self.assertIn("StrictHostKeyChecking=yes", argv)
            self.assertIn("ControlPath=none", argv)
            self.assertIn(owner.name, argv)

    def test_worker_copy_keeps_strict_trust_and_rejects_batch_line_injection(self):
        owner = Machine("operator@worker.local", False)

        def run_transfer(argv, *_args):
            self.assertEqual(argv[0], "sftp")
            self.assertEqual(argv[-2:], ["--", owner.name])
            self.assertIn("StrictHostKeyChecking=yes", argv)
            self.assertIn("ControlPath=none", argv)
            batch = Path(argv[argv.index("-b") + 1]).read_text(encoding="utf-8")
            self.assertEqual(batch, '@put -p "/controller path/key" "/worker path/"\n')
            return [[[], ["REMOTE HOST IDENTIFICATION HAS CHANGED"]]]

        with mock.patch.object(machine_module, "_run_bounded_command", side_effect=run_transfer) as run:
            result = owner.copy_to_worker({}, ["/controller path/key"], "/worker path/")
            self.assertIn("REMOTE HOST IDENTIFICATION HAS CHANGED", result[1])
            with self.assertRaises(ValueError):
                owner.copy_to_worker({}, ["/controller/key\n!command"], "/worker/")
            run.assert_called_once()

    def test_local_is_a_controller_role_not_a_worker_name_substring(self):
        workers = ["operator@worker.local", "localuser@worker", "operator@worker"]
        config = {"infrastructure": {"external_physical_machines": workers}}
        machines = make_machine_objects(config)

        self.assertEqual([machine.name for machine in machines], ["local", *workers])
        self.assertEqual([machine.is_local for machine in machines], [True, False, False, False])

    def test_owner_command_keeps_strict_trust_and_quotes_remote_arguments(self):
        owner = Machine("operator@worker.local", False)
        with mock.patch.object(
            machine_module, "_run_bounded_command", return_value=[[[], []]]
        ) as run:
            owner.process_on_owner({}, ["mkdir", "-p", "/run path/$name"], timeout_seconds=30)
        argv, shell, _, _, timeout = run.call_args.args
        self.assertEqual(argv[0], "ssh")
        target = argv.index(owner.name)
        for option in ("BatchMode=yes", "StrictHostKeyChecking=yes", "ControlPath=none"):
            self.assertLess(argv.index(option), target)
        self.assertEqual(argv[target - 1:], ["--", owner.name, "mkdir", "-p", "'/run path/$name'"])
        self.assertFalse(shell)
        self.assertEqual(timeout, 30)
