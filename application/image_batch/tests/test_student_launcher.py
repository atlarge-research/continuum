"""Exercise the student Bash entry point without installing dependencies or provisioning."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


LAUNCHER = Path(__file__).resolve().parents[1] / "scripts" / "student_demo.sh"
RUNTIME_STUB = """import json
import os
from pathlib import Path
import sys

if sys.argv[1:3] == ["-m", "pip"]:
    Path(__file__).parents[2].joinpath("pip.json").write_text(json.dumps(sys.argv[1:]))
else:
    print(json.dumps({"args": sys.argv[1:], "cwd": os.getcwd(), "env": {
        key: os.environ.get(key) for key in (
            "PYTHONPATH", "OPENDC_RUNTIME", "OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"
        )
    }}))
"""


class StudentLauncherTests(unittest.TestCase):
    """Check path resolution, runtime setup and child process boundaries."""

    def setUp(self):
        """Place the actual launcher in an isolated repository tree."""
        self.assertTrue(LAUNCHER.is_file(), "student demo launcher is missing")
        self.directory = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.directory)
        self.repository = self.directory / "repository"
        self.launcher = self.repository / "application/image_batch/scripts/student_demo.sh"
        self.launcher.parent.mkdir(parents=True)
        shutil.copyfile(LAUNCHER, self.launcher)
        self.caller = self.directory / "caller"
        self.caller.mkdir()
        self.environment = os.environ.copy()
        for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS"):
            self.environment.pop(name, None)

    def runtime(self, demo_root):
        """Create an interpreter substitute that records the launch boundary.

        Args:
            demo_root (Path): Directory containing the demo configuration and runtime.

        Returns:
            Path: Executable substitute for the virtual environment's Python.
        """
        interpreter = demo_root / "runtime/bin/python"
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text("#!" + sys.executable + "\n" + RUNTIME_STUB, encoding="utf-8")
        interpreter.chmod(0o755)
        return interpreter

    def invoke(self, *arguments):
        """Run the launcher from outside its repository.

        Args:
            *arguments (str): Arguments forwarded to the Bash entry point.

        Returns:
            subprocess.CompletedProcess: Launcher output and exit status.
        """
        return subprocess.run(
            ["/bin/bash", str(self.launcher), *arguments],
            cwd=self.caller,
            env=self.environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def test_help_does_not_create_runtime(self):
        """Help must remain available before Python or demo files exist."""
        result = self.invoke("--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("prepare", result.stdout)
        self.assertIn("--config", result.stdout)
        self.assertFalse((self.repository / "logs").exists())

    def test_missing_runtime_explains_prepare_without_creating_files(self):
        """An ordinary command must not install dependencies implicitly."""
        result = self.invoke("check")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("prepare", result.stderr)
        self.assertFalse((self.repository / "logs").exists())

    def test_default_config_and_sources_resolve_against_repository(self):
        """Changing caller directory must not change demo state or source imports."""
        demo_root = self.repository / "logs/student-demo"
        self.runtime(demo_root)
        self.environment["PYTHONPATH"] = "/unrelated/source"
        self.environment["OPENDC_RUNTIME"] = "unrelated"
        result = self.invoke("check")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(record["cwd"], str(self.repository))
        self.assertEqual(
            record["args"],
            ["-m", "student_demo", "--config", str(demo_root / "cluster.cfg"), "check"],
        )
        self.assertEqual(
            record["env"],
            {
                "PYTHONPATH": str(self.repository / "application/image_batch/src")
                + ":"
                + str(self.repository),
                "OPENDC_RUNTIME": "fns-demo",
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
            },
        )
        self.assertFalse((demo_root / "pip.json").exists())

    def test_relative_config_preserves_spaces_and_forwarded_arguments(self):
        """An explicit config belongs to the caller and arguments retain word boundaries."""
        demo_root = self.caller / "my demo"
        self.runtime(demo_root)
        result = self.invoke("--config", "my demo/cluster file.cfg", "python", "-c", "print('x y')")
        self.assertEqual(result.returncode, 0, result.stderr)
        record = json.loads(result.stdout)
        self.assertEqual(
            record["args"],
            [
                "-m",
                "student_demo",
                "--config",
                str(demo_root / "cluster file.cfg"),
                "python",
                "-c",
                "print('x y')",
            ],
        )

    def test_thread_overrides_are_preserved(self):
        """Existing thread limits must reach the demo process unchanged."""
        self.runtime(self.repository / "logs/student-demo")
        self.environment.update(OPENBLAS_NUM_THREADS="3", OMP_NUM_THREADS="2")
        result = self.invoke("url")
        self.assertEqual(result.returncode, 0, result.stderr)
        environment = json.loads(result.stdout)["env"]
        self.assertEqual(environment["OPENBLAS_NUM_THREADS"], "3")
        self.assertEqual(environment["OMP_NUM_THREADS"], "2")

    def test_invalid_arguments_do_not_create_runtime(self):
        """Invalid invocations must fail before any setup side effects."""
        for arguments in ((), ("--config",), ("unknown",)):
            with self.subTest(arguments=arguments):
                result = self.invoke(*arguments)
                self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.repository / "logs").exists())

    def test_prepare_creates_python310_runtime_and_installs_requirements(self):
        """Prepare must install the reporting and YAML dependencies before execution."""
        demo_root = self.caller / "new demo"
        demo_root.mkdir()
        config = demo_root / "cluster.cfg"
        config.write_text("[infrastructure]\n", encoding="utf-8")
        template = self.runtime(self.directory / "stub")
        binaries = self.directory / "bin"
        binaries.mkdir()
        bootstrap = binaries / "python3.10"
        bootstrap.write_text(
            "#!" + sys.executable + "\n"
            "import json\nimport os\nfrom pathlib import Path\nimport shutil\nimport sys\n"
            "runtime = Path(sys.argv[3])\n"
            "runtime.joinpath('bin').mkdir(parents=True)\n"
            "shutil.copyfile(os.environ['LAUNCHER_RUNTIME_STUB'], runtime / 'bin/python')\n"
            "runtime.joinpath('bin/python').chmod(0o755)\n"
            "runtime.parent.joinpath('venv.json').write_text(json.dumps(sys.argv[1:]))\n",
            encoding="utf-8",
        )
        bootstrap.chmod(0o755)
        self.environment["PATH"] = str(binaries) + os.pathsep + self.environment["PATH"]
        self.environment["LAUNCHER_RUNTIME_STUB"] = str(template)
        result = self.invoke("--config", str(config), "prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads((demo_root / "venv.json").read_text(encoding="utf-8")),
            ["-m", "venv", str(demo_root / "runtime")],
        )
        self.assertEqual(
            json.loads((demo_root / "pip.json").read_text(encoding="utf-8")),
            [
                "-m",
                "pip",
                "install",
                "-r",
                str(self.repository / "application/image_batch/requirements-analysis.txt"),
                "PyYAML==6.0.3",
            ],
        )
        self.assertEqual(json.loads(result.stdout)["args"][-1], "prepare")

    def test_prepare_repairs_dependencies_in_existing_runtime(self):
        """Rerunning preparation must also recover a partially completed installation."""
        demo_root = self.caller / "existing demo"
        self.runtime(demo_root)
        config = demo_root / "cluster.cfg"
        config.touch()
        result = self.invoke("--config", str(config), "prepare")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((demo_root / "pip.json").is_file())
        self.assertEqual(json.loads(result.stdout)["args"][-1], "prepare")

    def test_prepare_rejects_missing_config_before_installing(self):
        """A mistyped configuration path must not leave an unnecessary runtime tree."""
        result = self.invoke("--config", "missing/cluster.cfg", "prepare")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("config", result.stderr.lower())
        self.assertFalse((self.caller / "missing").exists())


if __name__ == "__main__":
    unittest.main()
