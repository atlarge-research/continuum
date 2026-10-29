"""Regression tests for benchmark publisher source contracts."""

import ast
from pathlib import Path
import unittest
from unittest import mock

from application.image_classification import image_classification


class PublisherCompletionLoopTests(unittest.TestCase):
    def assert_waits_until_at_least_target(self, source_path, received_name, target_name):
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
        comparisons = [
            node.test
            for node in ast.walk(tree)
            if isinstance(node, ast.While) and isinstance(node.test, ast.Compare)
        ]

        matching_less_than = [
            comparison
            for comparison in comparisons
            if (
                isinstance(comparison.left, ast.Name)
                and comparison.left.id == received_name
                and len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.Lt)
                and len(comparison.comparators) == 1
                and isinstance(comparison.comparators[0], ast.Name)
                and comparison.comparators[0].id == target_name
            )
        ]
        exact_waits = [
            comparison
            for comparison in comparisons
            if (
                isinstance(comparison.left, ast.Name)
                and comparison.left.id == received_name
                and len(comparison.ops) == 1
                and isinstance(comparison.ops[0], ast.NotEq)
                and len(comparison.comparators) == 1
                and isinstance(comparison.comparators[0], ast.Name)
                and comparison.comparators[0].id == target_name
            )
        ]

        self.assertEqual(len(matching_less_than), 1)
        self.assertEqual(exact_waits, [])

    def test_image_classification_publisher_accepts_extra_responses(self):
        repo_root = Path(__file__).resolve().parents[3]
        source_path = (
            repo_root
            / "application/image_classification/src/publisher/src/publisher.py"
        )

        self.assert_waits_until_at_least_target(source_path, "RECEIVED", "MAX_IMGS")

    def test_text_translation_publisher_accepts_extra_responses(self):
        repo_root = Path(__file__).resolve().parents[3]
        source_path = repo_root / "application/text_translation/src/publisher/src/publisher.py"

        self.assert_waits_until_at_least_target(source_path, "RECEIVED", "MAX_TXTS")


class ImageClassificationMetricTableTests(unittest.TestCase):
    def test_cloud_mode_without_worker_metrics_writes_only_endpoint_table(self):
        config = {
            "mode": "cloud",
            "infrastructure": {"endpoint_nodes": 1},
        }
        endpoint_metrics = [
            {
                "worker_id": 0,
                "total_time": 1.0,
                "proc_avg": 2.0,
                "data_avg": 3.0,
                "latency_avg": 4.0,
                "latency_stdev": 0.5,
            }
        ]

        with mock.patch(
            "application.image_classification.image_classification."
            "runtime_helpers.write_benchmark_metric_artifacts"
        ) as write_artifacts:
            image_classification.format_output(config, [], endpoint_metrics)

        tables = write_artifacts.call_args.args[1]
        self.assertEqual([table["label"] for table in tables], ["ENDPOINT OUTPUT"])


class ImageClassificationEndpointMetricTests(unittest.TestCase):
    """Endpoint fields retain their own numeric values in concurrent output."""

    @staticmethod
    def _output(records):
        return (
            ["2026-10-28T23:14:00.000000000Z Start connecting"]
            + [record for record in records for _ in range(20)]
            + ["2026-10-28T23:19:00.000000000Z All images have been received back"]
        )

    def _gather(self, records):
        return image_classification.gather_endpoint_metrics(
            {"mode": "edge"}, [self._output(records)], ["edge0_endpoint0"]
        )[0]

    def test_concatenated_latency_and_sending_keep_both_numeric_fields(self):
        """Both captured merges preserve latency in ms and payload size in KB."""
        samples = [
            (
                "2026-10-28T23:16:46.626442750Z Latency (ns): "
                "3644463497Sending data (bytes): 104664",
                "Latency (ns): 3644463497", "Sending data (bytes): 104664",
                3644.46, 104.66,
            ),
            (
                "2026-10-28T23:18:46.678285264Z Latency (ns): "
                "5456768713Sending data (bytes): 103280",
                "Latency (ns): 5456768713", "Sending data (bytes): 103280",
                5456.77, 103.28,
            ),
        ]
        for raw, latency, sending, expected_latency, expected_data in samples:
            with self.subTest(raw=raw), mock.patch.object(
                image_classification.logging, "warning"
            ) as warning:
                actual = self._gather(["Preparation and preprocessing (ns): 1000000", raw])
                separate = self._gather(
                    ["Preparation and preprocessing (ns): 1000000", latency, sending]
                )
                self.assertEqual(actual, separate)
                self.assertEqual(actual["latency_avg"], expected_latency)
                self.assertEqual(actual["data_avg"], expected_data)
                warning.assert_not_called()

    def test_received_publish_suffix_keeps_preparation_value(self):
        """MQTT debug output cannot discard the three captured prep values."""
        samples = [
            ("2026-10-28T23:14:34.742819417Z", "2845412", 2.85),
            ("2026-10-28T23:16:55.671788959Z", "2004164", 2.0),
            ("2026-10-28T23:18:56.165486841Z", "2599848", 2.6),
        ]
        for timestamp, number, expected in samples:
            record = "%s Preparation and preprocessing (ns): %s" % (timestamp, number)
            merged = record + (
                "[ 16 ] Received PUBLISH (d0, q0, r0, m0), "
                "'image-classification-pub', ...  (20 bytes)"
            )
            with self.subTest(number=number), mock.patch.object(
                image_classification.logging, "warning"
            ) as warning:
                actual = self._gather(
                    [merged, "Latency (ns): 2000000", "Sending data (bytes): 1000"]
                )
                self.assertEqual(actual, self._gather(
                    [record, "Latency (ns): 2000000", "Sending data (bytes): 1000"]
                ))
                self.assertEqual(actual["proc_avg"], expected)
                warning.assert_not_called()

    def test_published_data_suffix_keeps_latency_value(self):
        """A publish callback suffix leaves its preceding latency intact."""
        records = [
            "Preparation and preprocessing (ns): 1000000",
            "Sending data (bytes): 1000",
        ]
        raw = "2026-10-28T23:18:59.604235269Z Latency (ns): 204351027Published data"
        with mock.patch.object(image_classification.logging, "warning") as warning:
            actual = self._gather(records + [raw])
            self.assertEqual(actual, self._gather(records + ["Latency (ns): 204351027"]))
            warning.assert_not_called()
        self.assertEqual(actual["latency_avg"], 204.35)

    def test_ordinary_and_combined_metrics_keep_trimming_mapping_and_schema(self):
        """Normal metrics retain conversions, trimming and all three mode mappings."""
        for preparation in (
            "Preparation and preprocessing", "Preparation, preprocessing and processing"
        ):
            records = ["Sending data (bytes): 1000"]
            for value in range(20, 0, -1):
                records.extend([
                    "%s (ns): %i" % (preparation, value * 1000000),
                    "Latency (ns): %i" % (value * 1000000),
                ])
            # Exactly twenty distinct values: trim to 2..18, mean 10, stdev 4.90.
            output = ["2026-10-28T23:14:00.000000000Z Start"] + records + [
                "2026-10-28T23:19:00.000000000Z Finished"
            ]
            for mode, names in (
                ("edge", ["edge1_endpoint1", "edge0_endpoint0"]),
                ("cloud", ["cloud1_endpoint1", "cloud0_endpoint0"]),
                ("endpoint", ["endpoint1", "endpoint0"]),
            ):
                with self.subTest(preparation=preparation, mode=mode):
                    actual = image_classification.gather_endpoint_metrics(
                        {"mode": mode}, [output, output], names
                    )
                    self.assertEqual(actual, [
                        {"worker_id": worker_id, "total_time": 300.0, "proc_avg": 10.0,
                         "data_avg": 1.0, "latency_avg": 10.0, "latency_stdev": 4.9}
                        for worker_id in (0, 1)
                    ])

    def test_malformed_latency_does_not_borrow_later_sending_integer(self):
        """A malformed field warns while a subsequent valid metric is independent."""
        baseline = ["Preparation and preprocessing (ns): 1000000",
                    "Latency (ns): 2000000", "Sending data (bytes): 1000"]
        for bad_number in ("", "bad", "1.5", "123junk", "12 34"):
            with self.subTest(number=bad_number), self.assertLogs(level="WARNING") as logs:
                actual = self._gather(baseline + [
                    "Latency (ns): %sSending data (bytes): 7000" % bad_number
                ])
                self.assertEqual(actual["latency_avg"], 2.0)
                self.assertEqual(actual["data_avg"], 4.0)
                self.assertTrue(any("parsing line" in entry for entry in logs.output))

    def test_negative_unknown_unit_and_malformed_values_keep_diagnostics(self):
        """Invalid standalone fields still warn and leave valid observations intact."""
        baseline = ["Preparation and preprocessing (ns): 1000000",
                    "Latency (ns): 2000000", "Sending data (bytes): 1000"]
        expected = self._gather(baseline)
        for record, warning in (
            ("Latency (ns): -1", "Time/Size < 0"),
            ("Sending data (bytes): -1", "Time/Size < 0"),
            ("Latency (seconds): 1000000", "Unit should be one of"),
            ("Latency (ns): bad", "parsing line"),
            ("Latency (ns): 1.5", "parsing line"),
            ("Latency (ns): 123junk", "parsing line"),
        ):
            with self.subTest(record=record), self.assertLogs(level="WARNING") as logs:
                self.assertEqual(self._gather(baseline + [record]), expected)
                self.assertTrue(any(warning in entry for entry in logs.output))

    def test_malformed_sending_received_publish_keeps_warning_suppression(self):
        """The existing malformed sending/MQTT exception remains quiet and excluded."""
        baseline = ["Preparation and preprocessing (ns): 1000000",
                    "Latency (ns): 2000000", "Sending data (bytes): 1000"]
        with mock.patch.object(image_classification.logging, "warning") as warning:
            self.assertEqual(self._gather(baseline + [
                "Sending data (bytes): bad[ 16 ] Received PUBLISH (20 bytes)"
            ]), self._gather(baseline))
            warning.assert_not_called()
