"""Repeated decisions preserve draining placement and explicit capacity bounds."""

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from opendc_inputs import verify_inputs
from opendc_native_batch import plan_suite
from opendc_scenarios import prepare_suite
from test_opendc_scenarios import configuration, make_forecast, observer_rows, worker


class PersistentDrainTests(unittest.TestCase):
    """A previous cordon remains executable context at the next decision."""

    def prepare(self, root, *, names=("worker-a", "worker-b", "worker-c"), draining=True):
        """Create causal observations with an assigned, optionally cordoned worker.

        Args:
            root (Path): Empty temporary directory.
            names (tuple[str]): Configured and observed workers.
            draining (bool): Whether worker-a was cordoned by a prior action.

        Returns:
            tuple: Forecast directory, observer directory and explicit worker configuration.
        """
        rows = observer_rows([worker(name, 8, 16384) for name in names])
        for state in rows["cluster-state.jsonl"]:
            state["jobs"]["active"] = [
                job for job in state["jobs"]["active"] if job["kubernetes_job_uid"] != "exhausted"
            ]
            for node in state["workers"]:
                node["schedulable"] = node["node_name"] != "worker-a" or not draining
        with patch("test_opendc_scenarios.observer_rows", return_value=rows):
            forecast, observer = make_forecast(root)
        config = configuration(names=names, cores=(8,) * len(names))
        config.update(
            active_workers=[name for name in names if name != "worker-a"]
            if draining
            else list(names),
            draining_workers=["worker-a"] if draining else [],
            minimum_workers=1,
            maximum_workers=len(names),
        )
        return forecast, observer, config

    @patch.dict(os.environ, {"OPENDC_RUNTIME": "fns-demo"})
    def test_hold_preserves_busy_cordon_and_blocks_second_down(self):
        """Assigned work drains on its original node and receives no new admission."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer, config = self.prepare(root)
            manifest = prepare_suite(forecast, observer, config, root / "suite", "pinned-trace")
            self.assertEqual({row["candidate"] for row in manifest["experiments"]}, {"unchanged"})
            self.assertIn(
                {"candidate": "scale-down", "reason": "worker_already_draining"},
                manifest["unavailable_candidates"],
            )
            first = root / "suite" / manifest["experiments"][0]["input_dir"]
            verify_inputs(first)
            case = json.loads((first / "case.json").read_text())
            self.assertEqual(case["initial_cordoned_worker"], "worker-a")
            self.assertEqual(
                json.loads((first / "experiment.json").read_text())["cordonHosts"], [["worker-a"]]
            )
            self.assertTrue(
                any(
                    row["metadata"].get("preserved_assignment") == "worker-a"
                    for row in case["tasks"]
                )
            )
            self.assertEqual(
                plan_suite(root / "suite")["experiment"]["cordonHosts"], [["worker-a"]]
            )

    @patch.dict(os.environ, {"OPENDC_RUNTIME": "fns-demo"})
    def test_explicit_bounds_allow_five_workers_without_double_reserving_cpu(self):
        """Configured eight-core workers contribute seven application cores each."""
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            forecast, observer, config = self.prepare(
                root, names=tuple(f"worker-{name}" for name in "abcde"), draining=False
            )
            config["minimum_workers"] = 2
            manifest = prepare_suite(forecast, observer, config, root / "suite", "pinned-trace")
            self.assertEqual(len(manifest["active_workers"]), 5)
            case = json.loads(
                (root / "suite" / manifest["experiments"][0]["input_dir"] / "case.json").read_text()
            )
            self.assertEqual(sum(node["modeled_cores"] for node in case["workers"]), 35)
            for entry in manifest["experiments"]:
                verify_inputs(root / "suite" / entry["input_dir"])
            plan_suite(root / "suite")


if __name__ == "__main__":
    unittest.main()
