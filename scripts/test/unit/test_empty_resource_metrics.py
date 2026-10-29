"""Resource labels and CSV preservation for the empty application formatters."""

import csv
import os
import tempfile
import unittest

from application import runtime_helpers
from application.empty import empty as empty_app
from application.empty_kata import empty_kata as empty_kata_app


class EmptyResourceMetricsTests(unittest.TestCase):
    """Keep node/component labels distinct without changing sampled resource data."""

    def _check_resource_labels(self, username):
        columns = [
            "timestamp",
            "cloud0%s_cpu" % username,
            "cloud0%s_memory" % username,
            "cloudcontroller%s_cpu" % username,
            "cloudcontroller%s_memory" % username,
            "etcd_cpu",
            "etcd_memory",
            "apiserver_cpu",
            "apiserver_memory",
            "controller-manager_cpu",
            "controller-manager_memory",
            "scheduler_cpu",
            "scheduler_memory",
        ]
        expected_columns = [
            "Time (s)",
            "cloud0_cpu",
            "cloud0_memory",
            "controller_cpu",
            "controller_memory",
            "etcd_cpu",
            "etcd_memory",
            "apiserver_cpu",
            "apiserver_memory",
            "controller-manager_cpu",
            "controller-manager_memory",
            "scheduler_cpu",
            "scheduler_memory",
        ]
        rows = [
            [0.25, 11, 12, 21, 22, 31, 32, 41, 42, 51, 52, 61, 62],
            [1.75, 111, 112, 121, 122, 131, 132, 141, 142, 151, 152, 161, 162],
        ]
        for app in (empty_app, empty_kata_app):
            with self.subTest(app=app.__name__):
                with tempfile.TemporaryDirectory() as tempdir:
                    log_dir = os.path.join(tempdir, ".continuum", "logs")
                    os.makedirs(log_dir)
                    config = {
                        "username": username,
                        "timestamp": "resources-labels",
                        "infrastructure": {"base_path": tempdir},
                    }
                    kube_df = runtime_helpers.pd.DataFrame(rows, columns=columns, index=[7, 9])
                    os_df = runtime_helpers.pd.DataFrame(
                        {
                            "Time (s)": [0.25, 1.75],
                            "cpu-used cloud0 (%)": [1.5, 2.5],
                            "memory-used cloud0 (%)": [10.5, 20.5],
                        },
                        index=[4, 8],
                    )
                    expected_kube = kube_df.copy(deep=True)
                    expected_kube.columns = expected_columns
                    expected_os = os_df.copy(deep=True)
                    frames = [kube_df, os_df]

                    result = app.print_resources(config, frames)

                    self.assertIs(result, frames)
                    self.assertIs(result[0], kube_df)
                    self.assertIs(result[1], os_df)
                    for suffix, expected in (
                        ("resources", expected_kube),
                        ("resources_os", expected_os),
                    ):
                        path = os.path.join(log_dir, "resources-labels_dataframe_%s.csv" % suffix)
                        with open(path, encoding="utf-8", newline="") as handle:
                            header = next(csv.reader(handle))
                        self.assertEqual(header, list(expected.columns))
                        self.assertEqual(len(header), len(set(header)))
                        runtime_helpers.pd.testing.assert_frame_equal(
                            runtime_helpers.pd.read_csv(path), expected.reset_index(drop=True)
                        )
                    runtime_helpers.pd.testing.assert_frame_equal(kube_df, expected_kube)
                    runtime_helpers.pd.testing.assert_frame_equal(os_df, expected_os)

    def test_print_resources_preserves_node_and_component_labels(self):
        """Controller-manager metrics must remain separate from the controller VM."""
        self._check_resource_labels("matthijs")

    def test_print_resources_does_not_treat_controller_username_as_vm_role(self):
        """A username containing controller must not turn a worker into the controller."""
        self._check_resource_labels("analystcontroller")


if __name__ == "__main__":
    unittest.main()
