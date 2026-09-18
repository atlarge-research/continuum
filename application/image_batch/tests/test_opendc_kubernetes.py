"""Artifact collection must distinguish an interrupted container from success."""
import io
import copy
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from opendc_inputs import CONTRACT, file_hashes, prepare, write_json
from opendc_kubernetes import classify_execution, collect, extract_artifacts, job_manifest


def finished_pod(code, reason="Completed"):
    """Return minimal OpenDC container termination evidence for the requested exit/reason.

    Args:
        code (int): Container termination exit code.
        reason (str): Kubernetes termination reason.

    Returns:
        dict: Minimal Pod status containing one terminated OpenDC container.
    """
    return {
        "status": {
            "containerStatuses": [
                {
                    "name": "opendc",
                    "imageID": "sha256:test",
                    "state": {"terminated": {"exitCode": code, "reason": reason}},
                }
            ]
        }
    }


class KubernetesTests(unittest.TestCase):
    """Check Job constraints, termination classification and safe archive extraction."""

    def test_success_requires_complete_execution_evidence(self):
        """Require contract, process, validation and container exit evidence to agree."""
        valid = {
            "contract": CONTRACT,
            "status": "succeeded",
            "runner_exit_code": 0,
            "process": {
                "exit_code": 0,
                "timed_out": False,
                "received_signal": None,
                "launch_error": None,
            },
            "validation": {"status": "passed"},
        }
        self.assertEqual(classify_execution(finished_pod(0), valid)["status"], "succeeded")
        for field, value in (
            ("contract", "other"),
            ("validation", {"status": "not_run"}),
            ("process", {"exit_code": 1}),
            ("runner_exit_code", 1),
        ):
            with self.subTest(field=field):
                manifest = copy.deepcopy(valid)
                manifest[field] = value
                self.assertEqual(
                    classify_execution(finished_pod(0), manifest)["status"], "inconsistent"
                )

    def test_oom_without_final_manifest_is_interrupted(self):
        """Preserve the Kubernetes OOM reason when the runner could not finalize its record."""
        result = classify_execution(finished_pod(137, "OOMKilled"), {"status": "started"})
        self.assertEqual(result["status"], "interrupted")
        self.assertEqual(result["container_exit_code"], 137)
        self.assertEqual(result["termination_reason"], "OOMKilled")

    def test_container_failure_overrides_success_manifest(self):
        """Mark conflicting container and runner exits as inconsistent."""
        result = classify_execution(
            finished_pod(1, "Error"), {"status": "succeeded", "runner_exit_code": 0}
        )
        self.assertEqual(result["status"], "inconsistent")

    def test_manifest_timeout_is_preserved(self):
        """Keep timed_out when the manifest and Kubernetes both report exit 124."""
        result = classify_execution(
            finished_pod(124, "Error"), {"status": "timed_out", "runner_exit_code": 124}
        )
        self.assertEqual(result["status"], "timed_out")

    def test_job_is_bounded_and_pins_node_without_bypassing_scheduler(self):
        """Check resource bounds and node selection while retaining scheduler admission."""
        job = job_manifest(
            "test-run",
            "test-job",
            "continuum/opendc:test",
            "cloud0matthijs",
            "/var/tmp/fns-opendc-test",
        )
        pod = job["spec"]["template"]["spec"]
        self.assertNotIn("nodeName", pod)
        self.assertEqual(pod["nodeSelector"]["kubernetes.io/hostname"], "cloud0matthijs")
        self.assertEqual(
            pod["containers"][0]["resources"],
            {"requests": {"cpu": "1", "memory": "2Gi"}, "limits": {"cpu": "1", "memory": "2Gi"}},
        )
        self.assertEqual(job["spec"]["backoffLimit"], 0)
        self.assertEqual(job["spec"]["activeDeadlineSeconds"], 180)
        self.assertFalse(pod["automountServiceAccountToken"])
        self.assertTrue(pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"])

    def test_archive_cannot_escape_or_introduce_symlinks(self):
        """Reject parent traversal and symlink entries before extracting an archive."""
        for name, kind in (("../escape", tarfile.REGTYPE), ("link", tarfile.SYMTYPE)):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as root:
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as archive:
                    member = tarfile.TarInfo(name)
                    member.type = kind
                    member.linkname = "/tmp"
                    archive.addfile(member)
                stream.seek(0)
                with self.assertRaises(ValueError):
                    extract_artifacts(stream, Path(root))


class CollectionTests(unittest.TestCase):
    """Exercise real artifact files and archive verification with mocked SSH transport."""

    def setUp(self):
        """Create finalized output and matching Job/Pod ownership for each collection test."""
        # unittest owns cleanup across setUp and the test, including failed setup.
        self.temporary = tempfile.TemporaryDirectory()  # pylint: disable=consider-using-with
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.remote = self.root / "remote"
        self.run = self.remote / "results/run"
        self.run.mkdir(parents=True)
        prepare("memory", self.run / "inputs")
        (self.run / "output.parquet").write_bytes(b"recorded simulator output")
        self.manifest = {
            "contract": CONTRACT,
            "status": "succeeded",
            "runner_exit_code": 0,
            "process": {
                "exit_code": 0,
                "timed_out": False,
                "received_signal": None,
                "launch_error": None,
            },
            "validation": {"status": "passed"},
            "sha256": file_hashes(self.run),
        }
        write_json(self.run / "execution.json", self.manifest)
        self.remote_dir = "/var/tmp/fns-opendc-test"
        self.hostname = "cloud0matthijs"
        self.job = job_manifest("test", "run", "image:test", self.hostname, self.remote_dir)
        self.job["metadata"]["uid"] = "job-uid"
        self.job["status"] = {"conditions": [{"type": "Complete", "status": "True"}]}
        self.pod = finished_pod(0)
        self.pod["metadata"] = {
            "name": "run-pod",
            "ownerReferences": [{"kind": "Job", "uid": "job-uid", "controller": True}],
        }
        self.pod["spec"] = copy.deepcopy(self.job["spec"]["template"]["spec"])
        self.pod["spec"]["nodeName"] = self.hostname

    def collect(self):
        """Collect the fixture with only SSH transport substituted.

        Archive extraction and hashes use real files, including a prepared
        input manifest, so transport mocks cannot bypass integrity checks.

        Returns:
            dict: Collection record produced using the fixture SSH transport.
        """

        def remote_command(host, key, command, timeout=45):
            """Serve fixture Kubernetes records and local artifacts as SSH response bytes.

            Args:
                host (str): Requested SSH destination; unused by the transport stub.
                key (Path): Requested SSH key; unused by the transport stub.
                command (list[str]): Remote operation whose response the fixture supplies.
                timeout (float): Requested SSH timeout; unused by the transport stub.

            Returns:
                bytes: Encoded Kubernetes records or artifact data for the requested operation.
            """
            if command == ["hostname"]:
                return (self.hostname + "\n").encode()
            if command[0] == "python3":
                return json.dumps(file_hashes(self.remote)).encode()
            if command[0] == "tar":
                stream = io.BytesIO()
                with tarfile.open(fileobj=stream, mode="w") as archive:
                    archive.add(self.remote, arcname=".")
                return stream.getvalue()
            if "job" in command:
                return json.dumps(self.job).encode()
            if "pods" in command:
                return json.dumps({"items": [self.pod]}).encode()
            if "events" in command or "node" in command:
                return b"{}"
            if "logs" in command:
                return b"container evidence\n"
            raise AssertionError(command)

        with patch("opendc_kubernetes.ssh", side_effect=remote_command):
            return collect(
                "controller",
                "worker",
                Path("/key"),
                "test",
                "run",
                self.remote_dir,
                self.root / "collected",
            )

    def test_successful_collection_preserves_verified_evidence(self):
        """Require a verified local copy and a consistent successful execution record."""
        record = self.collect()
        self.assertEqual(record["status"], "collected")
        self.assertEqual(record["execution"]["status"], "succeeded")
        self.assertTrue(record["artifacts_verified"])
        self.assertTrue((self.root / "collected/artifacts/results/run/output.parquet").is_file())

    def test_corrupted_final_output_is_retained_but_never_verified(self):
        """Retain diagnostic archives when finalized simulator output has changed."""
        (self.run / "output.parquet").write_bytes(b"corrupted after execution")
        record = self.collect()
        self.assertEqual(record["status"], "incomplete")
        self.assertFalse(record.get("artifacts_verified", False))
        self.assertIn("execution artifact hash", " ".join(record["errors"]))
        self.assertTrue((self.root / "collected/artifacts.tar").is_file())
        self.assertEqual((self.run / "output.parquet").read_bytes(), b"corrupted after execution")

    def test_deleted_final_output_is_not_verified(self):
        """Reject a copy that no longer contains every finalized artifact."""
        (self.run / "output.parquet").unlink()
        record = self.collect()
        self.assertEqual(record["status"], "incomplete")
        self.assertFalse(record.get("artifacts_verified", False))

    def test_success_rechecks_the_copied_input_manifest(self):
        """Detect changed inputs even if the outer execution inventory was recomputed."""
        (self.run / "inputs/trace/tasks.parquet").write_bytes(b"changed input")
        self.manifest["sha256"] = file_hashes(self.run, exclude=("execution.json",))
        write_json(self.run / "execution.json", self.manifest)
        self.assertEqual(self.collect()["status"], "incomplete")

    def test_started_execution_can_be_collected_as_interrupted(self):
        """Collect partial files after an OOM without inventing a finalized simulator result."""
        write_json(self.run / "execution.json", {"contract": CONTRACT, "status": "started"})
        self.pod["status"] = finished_pod(137, "OOMKilled")["status"]
        self.job["status"] = {"conditions": [{"type": "Failed", "status": "True"}]}
        record = self.collect()
        self.assertEqual(record["status"], "collected")
        self.assertEqual(record["execution"]["status"], "interrupted")
        self.assertTrue(record["artifacts_verified"])

    def test_missing_execution_can_be_collected_as_interrupted(self):
        """Use Kubernetes termination evidence when no execution manifest survived."""
        (self.run / "execution.json").unlink()
        self.pod["status"] = finished_pod(137, "OOMKilled")["status"]
        self.job["status"] = {"conditions": [{"type": "Failed", "status": "True"}]}
        record = self.collect()
        self.assertEqual(record["status"], "collected")
        self.assertEqual(record["execution"]["status"], "interrupted")
        self.assertTrue(record["artifacts_verified"])

    def test_unscheduled_failed_pod_preserves_preparation_evidence(self):
        """Retrieve staged inputs after a deadline even if the Pod never reached a node."""
        (self.run / "execution.json").unlink()
        self.pod["spec"].pop("nodeName")
        self.pod["status"] = {"phase": "Failed"}
        self.job["status"] = {"conditions": [{"type": "Failed", "status": "True"}]}
        record = self.collect()
        self.assertEqual(record["status"], "collected")
        self.assertEqual(record["execution"]["status"], "interrupted")

    def test_malformed_manifest_preserves_collection_failure_evidence(self):
        """Keep the received archive when the execution manifest is not an object."""
        write_json(self.run / "execution.json", ["not an execution record"])
        record = self.collect()
        self.assertEqual(record["status"], "incomplete")
        self.assertTrue((self.root / "collected/artifacts.tar").is_file())

    def test_malformed_process_preserves_collection_failure_evidence(self):
        """Reject a success manifest whose process evidence has the wrong structure."""
        self.manifest["process"] = ["not a process record"]
        write_json(self.run / "execution.json", self.manifest)
        self.assertEqual(self.collect()["status"], "incomplete")

    def test_job_storage_path_must_match_requested_directory(self):
        """Reject artifacts from a staging path not referenced by the retrieved Job."""
        self.job["spec"]["template"]["spec"]["volumes"][1]["hostPath"][
            "path"
        ] = "/var/tmp/fns-opendc-other/results"
        self.assertEqual(self.collect()["status"], "incomplete")

    def test_pod_storage_path_must_match_requested_directory(self):
        """Check the actual Pod mounts as well as the Job template before collection."""
        self.pod["spec"]["volumes"][0]["hostPath"]["path"] = "/var/tmp/fns-opendc-other/inputs"
        self.assertEqual(self.collect()["status"], "incomplete")

    def test_pod_selector_must_match_job_selector(self):
        """Reject a Pod selector that points to a different artifact worker."""
        self.pod["spec"]["nodeSelector"]["kubernetes.io/hostname"] = "another-worker"
        self.assertEqual(self.collect()["status"], "incomplete")

    def test_scheduled_node_must_match_selector(self):
        """Reject execution on a node different from the selected artifact worker."""
        self.pod["spec"]["nodeName"] = "another-worker"
        self.assertEqual(self.collect()["status"], "incomplete")

    def test_ssh_worker_hostname_must_match_scheduled_node(self):
        """Reject SSH retrieval from a host other than the selected execution node."""
        self.hostname = "another-worker"
        self.assertEqual(self.collect()["status"], "incomplete")

    def test_pod_must_belong_to_retrieved_job(self):
        """Reject stale Pod evidence from a previous Job with the same name."""
        self.pod["metadata"]["ownerReferences"][0]["uid"] = "previous-job-uid"
        self.assertEqual(self.collect()["status"], "incomplete")
