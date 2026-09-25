"""Bounded API reconciliation must improve membership without inventing Job state."""

from datetime import datetime
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

from kubernetes import client

from test_opendt_observer import (
    FakeCoreApi,
    FakeBatchApi,
    FakePrometheus,
    RecordingWriter,
    ResourceSampler,
    demo_job,
    demo_pod,
)


class ReconciliationTests(unittest.TestCase):
    """Exercise a Job becoming visible between independent API list operations."""

    def sampler(self, lists):
        """Prepare changing API responses with a Pod referring to the missing Job.

        Args:
            lists (list[list]): Consecutive Job list responses.

        Returns:
            tuple: Sampler, saved states, diagnostics and mutable call count.
        """
        calls = []
        states, diagnostics = RecordingWriter(), []

        batch = FakeBatchApi([])
        read = batch.list_namespaced_job

        def list_jobs(**kwargs):
            """Advance one explicitly supplied API inventory.

            Args:
                kwargs (dict): Raw-list options from the sampler.

            Returns:
                SimpleNamespace: The next raw fixture response.
            """
            calls.append(None)
            batch.jobs = lists[min(len(calls) - 1, len(lists) - 1)]
            return read(**kwargs)

        batch.list_namespaced_job = list_jobs
        sampler = ResourceSampler(
            batch_api=batch,
            core_api=FakeCoreApi(pods=[demo_pod()]),
            prometheus=FakePrometheus(),
            namespace="fns-demo",
            label_selector="continuum.atlarge.nl/workload=image-batch",
            run_id="run-test",
            state_interval_seconds=1,
            resource_interval_seconds=5,
            snapshot_writer=RecordingWriter(),
            state_writer=states,
            emit_diagnostic=lambda event, details: diagnostics.append((event, details)),
        )
        return sampler, states, diagnostics, calls

    def test_second_read_recovers_job_referenced_by_newer_pod_list(self):
        """The collected snapshot includes the real Job discovered by a bounded reread."""
        sampler, states, _, calls = self.sampler([[], [demo_job(state="Running")]])
        sampler.collect_once(collect_resources=False)
        self.assertEqual(states.records[0]["counts"]["active_jobs"], 1)
        self.assertEqual(len(calls), 2)
        collection = states.records[0]["collection"]
        self.assertEqual(collection["passes"], 2)
        self.assertEqual(collection["missing_job_uids"], [])
        self.assertLessEqual(
            datetime.fromisoformat(collection["started_at"]),
            datetime.fromisoformat(states.records[0]["timestamp"]),
        )

    def test_unresolved_owner_stays_explicit_after_only_one_retry(self):
        """Persistent missing membership cannot trigger unbounded reads or invented Jobs."""
        sampler, states, _, calls = self.sampler([[], []])
        sampler.collect_once(collect_resources=False)
        self.assertEqual(len(calls), 2)
        self.assertEqual(states.records[0]["counts"]["active_jobs"], 0)
        self.assertEqual(states.records[0]["counts"]["queued_jobs"], 0)
        self.assertEqual(states.records[0]["collection"]["missing_job_uids"], ["job-uid"])

    def test_no_retry_when_job_and_pod_membership_already_agree(self):
        """Ordinary snapshots use one list pass, avoiding unnecessary API overhead."""
        sampler, states, _, calls = self.sampler([[demo_job(state="Running")]])
        sampler.collect_once(collect_resources=False)
        self.assertEqual(states.records[0].get("collection", {}).get("passes"), 1)
        self.assertEqual(len(calls), 1)

    def test_persisted_completion_retires_only_that_uid_from_recurring_inventory(self):
        """Completed evidence stays causal while each future API decode avoids archived Jobs."""
        sampler, states, _, _ = self.sampler([[demo_job(state="Complete")]])
        sampler.collect_once(collect_resources=False)
        self.assertEqual(states.records[-1]["counts"]["finished_jobs"], 1)
        sampler.take_snapshots("job-uid")
        sampler.collect_once(collect_resources=False)
        self.assertEqual(states.records[-1]["counts"]["finished_jobs"], 1)
        sampler.retire_job("job-uid")
        sampler.collect_once(collect_resources=False)
        self.assertEqual(states.records[-1]["jobs"]["finished"], [])
        self.assertEqual(states.records[-1]["collection"]["missing_job_uids"], [])
        self.assertEqual(states.records[-1]["collection"]["retired_completed_jobs"], 1)

    def test_raw_inventory_uses_real_sdk_after_filtering_only_persisted_uid(self):
        """The public client deserializer preserves list version and unretired identities."""
        sampler, _, _, _ = self.sampler([[]])
        raw = dict(
            metadata=dict(resourceVersion="21"),
            items=[
                dict(metadata=dict(uid="done", name="old")),
                dict(metadata=dict(uid="live", name="current")),
            ],
        )
        response = SimpleNamespace(data=json.dumps(raw).encode(), release_conn=Mock())
        sampler.batch_api = SimpleNamespace(
            list_namespaced_job=Mock(return_value=response), api_client=client.ApiClient()
        )
        sampler.take_snapshots("done")
        sampler.retire_job("done")
        result = sampler._list_inventory("jobs")  # pylint: disable=protected-access
        self.assertEqual([item.metadata.uid for item in result.items], ["live"])
        self.assertEqual(result.metadata.resource_version, "21")
        response.release_conn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
