"""Bounded API reconciliation must improve membership without inventing Job state."""

from datetime import datetime
from types import SimpleNamespace
import unittest

from test_opendt_observer import (
    FakeCoreApi,
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

        def list_jobs(**_kwargs):
            calls.append(None)
            return SimpleNamespace(items=lists[min(len(calls) - 1, len(lists) - 1)])

        sampler = ResourceSampler(
            batch_api=SimpleNamespace(list_namespaced_job=list_jobs),
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


if __name__ == "__main__":
    unittest.main()
