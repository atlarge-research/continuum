"""Focused unit tests for text-translation application contracts."""

import unittest
import warnings

from application.text_translation import text_translation


class TextTranslationOptionTests(unittest.TestCase):
    """Validate text-translation application option descriptors."""

    def test_frequency_descriptor_requires_a_positive_number(self):
        """Frequency remains a mandatory positive floating-point option."""
        frequency_setting = next(
            setting for setting in text_translation.add_options({}) if setting[0] == "frequency"
        )
        _name, value_type, condition, mandatory, default = frequency_setting

        self.assertIs(value_type, float)
        self.assertTrue(mandatory)
        self.assertIsNone(default)
        for value in (1, 0.5):
            with self.subTest(valid=value):
                self.assertTrue(condition(value))
        for value in (0, -1, True, False, "1"):
            with self.subTest(invalid=value):
                self.assertFalse(condition(value))


class TextTranslationWorkerMetricTests(unittest.TestCase):
    """Validate the worker timing-marker result contract."""

    def _gather(self, lines, worker_identity="translation-worker-0"):
        return text_translation.gather_worker_metrics(
            None,
            None,
            [[worker_identity, lines]],
            None,
        )

    def assert_parse_error(self, lines, *expected_parts):
        """Assert worker output fails with contextual marker details."""
        with self.assertRaises(ValueError) as exc:
            self._gather(lines)

        message = str(exc.exception)
        self.assertTrue(message.startswith("text_translation result parsing failed"))
        self.assertIn("translation-worker-0", message)
        for part in expected_parts:
            self.assertIn(part, message)

    def test_one_message_uses_normal_latency_start_and_post_finish_end(self):
        """One normal message excludes the pre-work wait and retains the final wait."""
        # The subscriber prints Received time without a newline, so its Latency print
        # completes the same timestamped container-log record.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)
            metrics = self._gather(
                [
                    "2026-08-07T12:00:00.000000000Z Start connecting to the local MQTT broker",
                    "2026-08-07T12:00:00.100000000Z Broker ip: 10.0.0.2",
                    "2026-08-07T12:00:00.200000000Z Topic: text-translation-sub",
                    "2026-08-07T12:00:00.300000000Z [ForkPoolWorker-1] Preparations finished",
                    "2026-08-07T12:00:00.500000000Z [ForkPoolWorker-1] Get item",
                    "2026-08-07T12:00:01.000000000Z [ForkPoolWorker-1] Received time is "
                    "1786104000000000000[ForkPoolWorker-1] Latency (ns): 1000000",
                    "2026-08-07T12:00:01.200000000Z [ForkPoolWorker-1] Translated text: "
                    "Das ist ein Test",
                    "2026-08-07T12:00:01.300000000Z [ForkPoolWorker-1] Processing "
                    "(ns): 3000000",
                    "2026-08-07T12:00:01.400000000Z [ForkPoolWorker-1] Send result to "
                    "source: 10.0.0.3",
                    "2026-08-07T12:00:01.500000000Z [ForkPoolWorker-1] Connect to remote "
                    "broker on endpoint 10.0.0.3",
                    "2026-08-07T12:00:01.600000000Z [ForkPoolWorker-1] Connected with the "
                    "remote broker",
                    "2026-08-07T12:00:02.000000000Z [ForkPoolWorker-1] Get item",
                    "2026-08-07T12:00:02.200000000Z [ForkPoolWorker-1] A client "
                    "disconnected, 0 clients left",
                    "2026-08-07T12:00:02.500000000Z [ForkPoolWorker-1] Get item",
                ]
            )

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["total_time"], 1.5)

    def test_multiple_messages_use_first_latency_and_final_post_start_end(self):
        """Multiple messages retain the first metric and select the final later wait."""
        metrics = self._gather(
            [
                "2026-08-07T12:00:00.500000000Z [ForkPoolWorker-1] Get item",
                "not-a-timestamp [ 16 ] Sending CONNECT",
                "2026-08-07T12:00:01.000000000Z [ForkPoolWorker-1] Received time is "
                "1786104000000000000[ForkPoolWorker-1] Latency (ns): 1000000",
                "2026-08-07T12:00:01.100000000Z [ForkPoolWorker-1] Translated text: Eins",
                "2026-08-07T12:00:01.200000000Z [ForkPoolWorker-1] Processing (ns): 3000000",
                "2026-08-07T12:00:02.000000000Z [ForkPoolWorker-1] Get item",
                "2026-08-07T12:00:03.000000000Z [ForkPoolWorker-1] Received time is "
                "1786104002000000000[ForkPoolWorker-1] Latency (ns): 2000000",
                "2026-08-07T12:00:03.100000000Z [ForkPoolWorker-1] Translated text: Zwei",
                "2026-08-07T12:00:03.200000000Z [ForkPoolWorker-1] Processing (ns): 4000000",
                "2026-08-07T12:00:04.000000000Z [ForkPoolWorker-1] Get item",
                "2026-08-07T12:00:04.200000000Z Published data",
                "2026-08-07T12:00:04.500000000Z [ForkPoolWorker-1] Get item",
            ]
        )

        self.assertEqual(len(metrics), 1)
        self.assertEqual(metrics[0]["total_time"], 3.5)
        self.assertEqual(metrics[0]["comm_delay_avg"], 1.0)
        self.assertEqual(metrics[0]["comm_delay_stdev"], 0.0)
        self.assertEqual(metrics[0]["proc_avg"], 3.0)

    def test_empty_overall_worker_output_remains_empty(self):
        """An empty worker collection preserves the existing empty result."""
        self.assertEqual(text_translation.gather_worker_metrics(None, None, [], None), [])

    def test_missing_normal_start_rejects_exception_and_historical_markers(self):
        """Neither read marker can replace normal-path latency evidence."""
        for marker in ("Read text and apply ML", "Read image and apply ML"):
            with self.subTest(marker=marker):
                self.assert_parse_error(
                    [
                        "2026-08-07T12:00:00.500000000Z [ForkPoolWorker-1] Get item",
                        "2026-08-07T12:00:01.000000000Z [ForkPoolWorker-1] %s" % marker,
                        "2026-08-07T12:00:02.000000000Z [ForkPoolWorker-1] Get item",
                    ],
                    "missing normal-path start marker",
                    "Latency (ns):",
                )

    def test_missing_post_start_end_fails(self):
        """A worker start without a later Get item fails clearly."""
        self.assert_parse_error(
            [
                "2026-08-07T12:00:00.500000000Z [ForkPoolWorker-1] Get item",
                "2026-08-07T12:00:01.000000000Z [ForkPoolWorker-1] Received time is "
                "1786104000000000000[ForkPoolWorker-1] Latency (ns): 1000000",
                "2026-08-07T12:00:01.200000000Z [ForkPoolWorker-1] Processing (ns): 3000000",
            ],
            "missing post-start end marker",
            "Get item",
        )

    def test_malformed_first_start_fails_without_selecting_later_start(self):
        """A malformed first selected start is not skipped."""
        self.assert_parse_error(
            [
                "2026-08-07T12:00:00.500000000Z [ForkPoolWorker-1] Get item",
                "not-a-timestamp [ForkPoolWorker-1] Received time is "
                "1786104000000000000[ForkPoolWorker-1] Latency (ns): 1000000",
                "2026-08-07T12:00:02.000000000Z [ForkPoolWorker-1] Received time is "
                "1786104001000000000[ForkPoolWorker-1] Latency (ns): 2000000",
                "2026-08-07T12:00:03.000000000Z [ForkPoolWorker-1] Get item",
            ],
            "malformed timestamp for normal-path start marker",
            "Latency (ns):",
            "not-a-timestamp",
        )

    def test_malformed_post_start_end_fails_without_selecting_later_end(self):
        """A malformed required end is not skipped."""
        self.assert_parse_error(
            [
                "2026-08-07T12:00:01.000000000Z [ForkPoolWorker-1] Received time is "
                "1786104000000000000[ForkPoolWorker-1] Latency (ns): 1000000",
                "not-a-timestamp [ForkPoolWorker-1] Get item",
                "2026-08-07T12:00:03.000000000Z [ForkPoolWorker-1] Get item",
            ],
            "malformed timestamp for required end marker",
            "Get item",
            "not-a-timestamp",
        )

    def test_end_preceding_start_fails(self):
        """An end timestamp earlier than the start fails clearly."""
        self.assert_parse_error(
            [
                "2026-08-07T12:00:02.000000000Z [ForkPoolWorker-1] Received time is "
                "1786104000000000000[ForkPoolWorker-1] Latency (ns): 1000000",
                "2026-08-07T12:00:01.000000000Z [ForkPoolWorker-1] Get item",
            ],
            "end marker 'Get item' precedes start marker 'Latency (ns):'",
        )


if __name__ == "__main__":
    unittest.main()
