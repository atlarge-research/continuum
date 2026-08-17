"""Unit tests for benchmark stage contract validation helpers."""

from pathlib import Path
import unittest

from input.configuration import benchmark_stage_contract


class BenchmarkStageContractTests(unittest.TestCase):
    def setUp(self):
        self.path = Path("/tmp/benchmark-contract.yaml")
        self.prefix = "benchmark.pipeline[0]"

    def _image_classification_config(self):
        return {
            "frequency": 2,
            "duration": 120,
            "applications_per_worker": 1,
            "application_worker_cpu": 0.5,
            "application_worker_memory": 1.0,
            "application_endpoint_cpu": 0.5,
            "application_endpoint_memory": 1.0,
        }

    def _text_translation_config(self, frequency):
        return {
            "frequency": frequency,
            "duration": 120,
            "applications_per_worker": 1,
            "application_worker_cpu": 0.5,
            "application_worker_memory": 1.0,
            "application_endpoint_cpu": 0.5,
            "application_endpoint_memory": 1.0,
        }

    def test_known_stage_contract_accepts_valid_config(self):
        benchmark_stage_contract.validate_stage_config_contract(
            "image_classification",
            self._image_classification_config(),
            self.path,
            self.prefix,
        )

    def test_unknown_stage_type_is_contract_noop(self):
        benchmark_stage_contract.validate_stage_config_contract(
            "custom_stage",
            {"arbitrary": "value"},
            self.path,
            self.prefix,
        )

    def test_unknown_config_key_fails(self):
        config = self._image_classification_config()
        config["unknown"] = 1
        with self.assertRaises(ValueError) as exc:
            benchmark_stage_contract.validate_stage_config_contract(
                "image_classification", config, self.path, self.prefix
            )
        self.assertIn("benchmark.pipeline[0].config.unknown", str(exc.exception))
        self.assertIn("unexpected key for benchmark stage type 'image_classification'", str(exc.exception))

    def test_missing_required_key_fails(self):
        config = self._image_classification_config()
        del config["duration"]
        with self.assertRaises(ValueError) as exc:
            benchmark_stage_contract.validate_stage_config_contract(
                "image_classification", config, self.path, self.prefix
            )
        self.assertIn("benchmark.pipeline[0].config.duration", str(exc.exception))
        self.assertIn("is required for benchmark stage type 'image_classification'", str(exc.exception))

    def test_invalid_value_type_fails(self):
        config = self._image_classification_config()
        config["duration"] = True
        with self.assertRaises(ValueError) as exc:
            benchmark_stage_contract.validate_stage_config_contract(
                "image_classification", config, self.path, self.prefix
            )
        self.assertIn("benchmark.pipeline[0].config.duration", str(exc.exception))
        self.assertIn(
            "must be integer >= 1 for benchmark stage type 'image_classification'",
            str(exc.exception),
        )

    def test_text_translation_frequency_accepts_positive_integer_and_float(self):
        for frequency in (1, 0.5):
            with self.subTest(frequency=frequency):
                benchmark_stage_contract.validate_stage_config_contract(
                    "text_translation",
                    self._text_translation_config(frequency),
                    self.path,
                    self.prefix,
                )

    def test_text_translation_frequency_rejects_non_positive_and_non_numeric_values(self):
        for frequency in (
            0,
            -1,
            True,
            False,
            "1",
            float("inf"),
            float("-inf"),
            float("nan"),
        ):
            with self.subTest(frequency=frequency):
                with self.assertRaises(ValueError) as exc:
                    benchmark_stage_contract.validate_stage_config_contract(
                        "text_translation",
                        self._text_translation_config(frequency),
                        self.path,
                        self.prefix,
                    )
                self.assertIn("benchmark.pipeline[0].config.frequency", str(exc.exception))
                self.assertIn(
                    "must be finite number > 0 for benchmark stage type 'text_translation'",
                    str(exc.exception),
                )

    def test_float_capable_resource_fields_reject_non_finite_values(self):
        for key in (
            "application_worker_cpu",
            "application_worker_memory",
            "application_endpoint_cpu",
            "application_endpoint_memory",
        ):
            for value in (float("inf"), float("-inf"), float("nan")):
                with self.subTest(key=key, value=value):
                    config = self._image_classification_config()
                    config[key] = value
                    with self.assertRaises(ValueError) as exc:
                        benchmark_stage_contract.validate_stage_config_contract(
                            "image_classification",
                            config,
                            self.path,
                            self.prefix,
                        )
                    self.assertIn(
                        "benchmark.pipeline[0].config.%s" % (key,),
                        str(exc.exception),
                    )
                    self.assertIn("must be finite number >= 0.001", str(exc.exception))


if __name__ == "__main__":
    unittest.main()
