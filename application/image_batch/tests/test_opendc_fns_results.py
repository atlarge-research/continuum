"""Independent lifecycle and energy oracles for complete native cordon results."""
from pathlib import Path
import sys
import tempfile
import unittest

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# pylint: disable=wrong-import-position
from opendc_results import validate_provisional_results
from opendc_evaluate import analyze_case
from opendc_energy import datacenter_series

# pylint: enable=wrong-import-position


def cordon_output(directory):
    """Write a literal two-worker drain oracle with a missing final host sample.

    Args:
        directory (Path): New simulator output root.

    Returns:
        tuple: Case, raw table directory and completed task rows.
    """
    raw = directory / "controlled/raw-output/0/seed=0"
    raw.mkdir(parents=True)
    rows = []
    records = []
    for task_id, (host, arrival, start, finish, assigned) in enumerate(
        [
            ("a", 0, 0, 10000, "a"),
            ("b", 0, 0, 6000, "b"),
            ("b", 0, 6000, 9000, None),
            ("b", 1000, 9000, 12000, None),
        ]
    ):
        rows.append(
            {
                "task_id": task_id,
                "task_state": "COMPLETED",
                "timestamp": finish,
                "submission_time": arrival,
                "schedule_time": start,
                "finish_time": finish,
                "host_name": host,
                "cpu_count": 1,
                "mem_capacity": 256,
            }
        )
        records.append(
            {
                "task": {
                    "id": task_id,
                    "submission_time": arrival,
                    "duration": finish - start,
                    "cpu_count": 1,
                    "mem_capacity": 256,
                },
                "metadata": {
                    "cohort": "future" if arrival else "backlog",
                    "phase": "running" if assigned else ("future" if arrival else "queued"),
                    "preserved_assignment": assigned,
                    "original_creation_ms": 100000 + arrival,
                },
            }
        )
    pq.write_table(pa.Table.from_pylist(rows), raw / "task.parquet")
    hosts = [
        {
            "host_name": name,
            "timestamp": timestamp,
            "energy_usage": energy,
            "core_count": 1,
            "mem_capacity": 512,
        }
        for name, timestamp, energy in [
            ("a", 0, 0),
            ("a", 9000, 1800),
            ("b", 0, 0),
            ("b", 12000, 2400),
        ]
    ]
    pq.write_table(pa.Table.from_pylist(hosts), raw / "host.parquet")
    service = [
        {
            "timestamp": 12000,
            "tasks_total": 4,
            "tasks_completed": 4,
            "tasks_pending": 0,
            "tasks_active": 0,
            "tasks_terminated": 0,
            "hosts_up": 1,
        }
    ]
    pq.write_table(pa.Table.from_pylist(service), raw / "service.parquet")
    energy = [
        {
            "timestamp": timestamp,
            "data_center_name": "provisional",
            "energy_usage": joules,
            "power_draw": watts,
        }
        for timestamp, joules, watts in [
            (0, 0, 400),
            (9000, 3600, 400),
            (10000, 4000, 200),
            (12000, 4400, 100),
        ]
    ]
    pq.write_table(pa.Table.from_pylist(energy), raw / "dataCenter.parquet")
    pq.write_table(pa.Table.from_pylist(energy), raw / "powerSource.parquet")
    case = {
        "initialization_mode": "pinned-trace",
        "candidate": "scale-down",
        "selected_worker": "a",
        "scope": "complete",
        "tasks": records,
        "omitted_tasks": [],
        "model_exhausted_jobs": [],
        "cutoff_ms": 100000,
        "horizon_ms": 10000,
        "workers": [
            {
                "node_name": name,
                "configured_cores": 2,
                "modeled_cores": 1,
                "memory_mib": 512,
                "idle_power_w": 100,
                "max_power_w": 200,
            }
            for name in ("a", "b")
        ],
    }
    return case, raw, rows


class CordonResultTests(unittest.TestCase):
    """Require complete work and energy rather than accepting native exit zero."""

    def test_datacenter_covers_drain_interval_missing_from_host_telemetry(self):
        """Keep all four completions and expose why summed host totals are incomplete."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, _, _ = cordon_output(directory)
            result = validate_provisional_results(directory, case)
            self.assertEqual(result["task_count"], 4)
            self.assertEqual(result["initialization_mode"], "pinned-trace")
            self.assertEqual(result["cordon"]["drain_finish_ms"], 10000)
            self.assertEqual(result["cordon"]["last_host_sample_ms"], 9000)
            self.assertEqual(result["energy"]["final_datacenter_joules"], 4400)

    def test_delayed_pinned_start_is_rejected(self):
        """Initial placement includes immediate occupation, not merely eventual host choice."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, raw, rows = cordon_output(directory)
            rows[0].update(schedule_time=1000, finish_time=11000, timestamp=11000)
            pq.write_table(pa.Table.from_pylist(rows), raw / "task.parquet")
            with self.assertRaisesRegex(ValueError, "pinned"):
                validate_provisional_results(directory, case)

    def test_draining_host_cannot_admit_later_work(self):
        """Even an otherwise fitting task must not be admitted after the cordon."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, raw, rows = cordon_output(directory)
            rows[2].update(host_name="a", schedule_time=10000, finish_time=13000, timestamp=13000)
            pq.write_table(pa.Table.from_pylist(rows), raw / "task.parquet")
            with self.assertRaisesRegex(ValueError, "cordon"):
                validate_provisional_results(directory, case)

    def test_missing_datacenter_tail_is_not_complete_energy(self):
        """A drain does not excuse an unobserved aggregate energy endpoint."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, raw, _ = cordon_output(directory)
            table = pq.read_table(raw / "dataCenter.parquet").slice(0, 2)
            pq.write_table(table, raw / "dataCenter.parquet")
            with self.assertRaisesRegex(ValueError, "datacenter.*coverage"):
                validate_provisional_results(directory, case)

    def test_cordon_evaluation_uses_complete_energy_and_only_remaining_worker_idle(self):
        """At 12 s use 4400 J, then add 100 W for the one remaining powered worker."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, raw, rows = cordon_output(directory)
            result = analyze_case(
                case,
                rows,
                pq.read_table(raw / "host.parquet").to_pylist(),
                evaluation_seconds=15,
                datacenter_rows=pq.read_table(raw / "dataCenter.parquet").to_pylist(),
            )
            self.assertEqual(result["windows"]["fixed_window"]["energy_joules"], 4700)
            self.assertEqual(result["windows"]["cohort_through_completion"]["energy_joules"], 4400)
            self.assertEqual(result["included_idle_power_w"], 100)

    def test_completed_tasks_do_not_prove_the_cordoned_host_closed(self):
        """Require native service evidence of closure as well as completed assigned work."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, raw, _ = cordon_output(directory)
            service = pq.read_table(raw / "service.parquet").to_pylist()
            service[0]["hosts_up"] = 2
            pq.write_table(pa.Table.from_pylist(service), raw / "service.parquet")
            with self.assertRaisesRegex(ValueError, "cordon.*close"):
                validate_provisional_results(directory, case)

    def test_aggregate_cannot_discard_recorded_drained_host_energy(self):
        """A plausible remaining-host total is not complete worker-pool energy."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, raw, _ = cordon_output(directory)
            rows = pq.read_table(raw / "dataCenter.parquet").to_pylist()
            for row, energy in zip(rows, (0, 1800, 2000, 2400)):
                row["energy_usage"] = energy
            pq.write_table(pa.Table.from_pylist(rows), raw / "dataCenter.parquet")
            with self.assertRaisesRegex(ValueError, "recorded host energy"):
                validate_provisional_results(directory, case)

    def test_float32_energy_rounding_does_not_fail_idle_power_bound(self):
        """Accept native quantization, while rejecting a real missing energy interval."""
        case = {
            "scope": "complete",
            "candidate": "unchanged",
            "workers": [{"node_name": "a", "idle_power_w": 300, "max_power_w": 600}],
        }
        rows = [
            {"data_center_name": "provisional", "timestamp": at, "energy_usage": energy}
            for at, energy in [(0, 0), (3000, 1007.3446655273438), (4000, 1307.3446044921875)]
        ]
        self.assertTrue(datacenter_series(case, rows))
        rows[-1]["energy_usage"] -= 1
        with self.assertRaisesRegex(ValueError, "power bounds"):
            datacenter_series(case, rows)

    def test_pinned_task_cannot_visit_another_host_before_its_final_record(self):
        """Check running placement rather than only the host named on completion."""
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            case, raw, rows = cordon_output(directory)
            rows.append({**rows[0], "task_state": "RUNNING", "timestamp": 5000, "host_name": "b"})
            pq.write_table(pa.Table.from_pylist(rows), raw / "task.parquet")
            with self.assertRaisesRegex(ValueError, "pinned"):
                validate_provisional_results(directory, case)


if __name__ == "__main__":
    unittest.main()
