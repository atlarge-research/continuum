"""Static and dependency-free tests for the text-translation subscriber image contract."""

from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import stat
import tempfile
import unittest
from unittest import mock


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SUBSCRIBER_ROOT = (
    REPOSITORY_ROOT / "application" / "text_translation" / "src" / "subscriber"
)


def load_module(name, path):
    """Load one source file without requiring it to be an installed package."""
    specification = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


class FakeTranslationModel:
    """Record the arguments and state applied by the offline loader."""

    calls = []

    def __init__(self):
        self.evaluated = False
        self.device = None

    @classmethod
    def from_pretrained(cls, path, **kwargs):
        """Return a model double while retaining loader arguments."""
        cls.calls.append((path, kwargs))
        return cls()

    def eval(self):
        """Record evaluation-mode selection."""
        self.evaluated = True

    def to(self, device):
        """Record device selection."""
        self.device = device


# pylint: disable-next=too-few-public-methods
class FakeTranslationTokenizer:
    """Record the arguments applied by the offline tokenizer loader."""

    calls = []

    @classmethod
    def from_pretrained(cls, path, **kwargs):
        """Return a tokenizer double while retaining loader arguments."""
        cls.calls.append((path, kwargs))
        return cls()


class TextTranslationModelLockTests(unittest.TestCase):
    """Validate the immutable upstream model and tokenizer identity."""

    @classmethod
    def setUpClass(cls):
        with (SUBSCRIBER_ROOT / "model.lock.json").open(encoding="utf-8") as lock_file:
            cls.model_lock = json.load(lock_file)

    def test_lock_labels_the_approved_new_english_to_dutch_baseline(self):
        """The fallback must never be presented as a thesis reproduction."""
        self.assertEqual(
            self.model_lock["model"]["repository"], "Helsinki-NLP/opus-mt-en-nl"
        )
        self.assertEqual(
            self.model_lock["model"]["revision"],
            "8aad73b34ff36c090e7fc8a2eb7e2e7cca235d31",
        )
        self.assertEqual(
            self.model_lock["model"]["model_card"],
            "https://huggingface.co/Helsinki-NLP/opus-mt-en-nl/blob/"
            "8aad73b34ff36c090e7fc8a2eb7e2e7cca235d31/README.md",
        )
        self.assertEqual(self.model_lock["model"]["license"], "Apache-2.0")
        self.assertEqual(
            self.model_lock["baseline"],
            {
                "classification": "new-benchmark-baseline",
                "historical_equivalence": False,
                "source_language": "en",
                "target_language": "nl",
            },
        )

    def test_lock_contains_the_complete_reviewed_artifact_set(self):
        """Model and tokenizer remain distinct roles in one immutable snapshot."""
        artifacts = {artifact["filename"]: artifact for artifact in self.model_lock["artifacts"]}
        self.assertEqual(
            set(artifacts),
            {
                "README.md",
                "config.json",
                "generation_config.json",
                "pytorch_model.bin",
                "source.spm",
                "target.spm",
                "tokenizer_config.json",
                "vocab.json",
            },
        )
        self.assertEqual(artifacts["pytorch_model.bin"]["size"], 316246425)
        self.assertEqual(artifacts["pytorch_model.bin"]["roles"], ["model"])
        self.assertEqual(artifacts["source.spm"]["roles"], ["tokenizer"])
        self.assertEqual(
            artifacts["README.md"]["roles"],
            ["license", "provenance", "attribution"],
        )
        for artifact in artifacts.values():
            self.assertRegex(artifact["sha256"], r"^[0-9a-f]{64}$")
            self.assertGreater(artifact["size"], 0)


class TextTranslationFetchTests(unittest.TestCase):
    """Exercise artifact verification with in-memory data and no network."""

    @classmethod
    def setUpClass(cls):
        cls.fetch_model = load_module(
            "text_translation_fetch_model", SUBSCRIBER_ROOT / "scripts" / "fetch_model.py"
        )

    @staticmethod
    def manifest(content, sha256=None):
        """Create a minimal valid lock for one in-memory test artifact."""
        return {
            "schema_version": 1,
            "model": {
                "repository": "example/model",
                "revision": "a" * 40,
            },
            "artifacts": [
                {
                    "filename": "artifact.bin",
                    "size": len(content),
                    "sha256": sha256 or hashlib.sha256(content).hexdigest(),
                }
            ],
        }

    def test_verified_artifact_is_written(self):
        """Only bytes matching both the locked size and digest are retained."""
        content = b"reviewed model bytes"
        requested_urls = []

        @contextmanager
        def open_url(url):
            requested_urls.append(url)
            yield io.BytesIO(content)

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            self.fetch_model.fetch_artifacts(
                self.manifest(content), destination, open_url=open_url
            )
            installed_artifact = destination / "artifact.bin"
            self.assertEqual(installed_artifact.read_bytes(), content)
            self.assertEqual(stat.S_IMODE(installed_artifact.stat().st_mode), 0o444)

        self.assertEqual(
            requested_urls,
            ["https://huggingface.co/example/model/resolve/%s/artifact.bin" % ("a" * 40)],
        )

    def test_hash_mismatch_fails_without_installing_artifact(self):
        """A changed upstream object makes the image build fail clearly."""
        content = b"changed bytes"

        @contextmanager
        def open_url(_url):
            yield io.BytesIO(content)

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
                self.fetch_model.fetch_artifacts(
                    self.manifest(content, sha256="0" * 64),
                    destination,
                    open_url=open_url,
                )
            self.assertFalse((destination / "artifact.bin").exists())

    def test_oversized_response_aborts_before_end_of_stream(self):
        """An endpoint cannot exhaust build-host disk before the size check."""
        locked_content = b"small"
        response = io.BytesIO(locked_content + b"unexpected bytes")

        @contextmanager
        def open_url(_url):
            yield response

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory)
            with self.assertRaisesRegex(ValueError, "exceeds locked size"):
                self.fetch_model.fetch_artifacts(
                    self.manifest(locked_content),
                    destination,
                    open_url=open_url,
                )
            self.assertFalse((destination / "artifact.bin").exists())


class TextTranslationDependencyLockTests(unittest.TestCase):
    """Validate that dependency resolution is closed and hash-pinned."""

    def test_every_dependency_has_one_exact_version_and_hash(self):
        """The image cannot accept a newly published wheel under an old name."""
        requirement_pattern = re.compile(
            r"^(?P<name>[a-z0-9-]+)==(?P<version>\S+) "
            r"--hash=sha256:(?P<hash>[0-9a-f]{64})$"
        )
        dependencies = {}
        for raw_line in (SUBSCRIBER_ROOT / "requirements.lock").read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", "--")):
                continue
            match = requirement_pattern.fullmatch(line)
            self.assertIsNotNone(match, line)
            dependencies[match.group("name")] = match.group("version")

        self.assertEqual(len(dependencies), 27)
        self.assertEqual(dependencies["torch"], "2.5.1+cpu")
        self.assertEqual(dependencies["transformers"], "4.46.3")
        self.assertEqual(dependencies["sentencepiece"], "0.2.0")
        self.assertEqual(dependencies["paho-mqtt"], "2.1.0")


class TextTranslationDockerContractTests(unittest.TestCase):
    """Guard build and runtime behavior without invoking Docker."""

    @classmethod
    def setUpClass(cls):
        cls.dockerfile = (SUBSCRIBER_ROOT / "Dockerfile").read_text()
        cls.build_script = (SUBSCRIBER_ROOT / "docker.sh").read_text()

    def test_build_uses_the_reviewed_amd64_base_and_hash_locks(self):
        """Base, Python packages, and model inputs all have immutable identities."""
        self.assertIn(
            "python:3.11.13-slim-bookworm@sha256:"
            "cec9aa7aa96eea4fa036e9b82be1e6b325f2e3707f462d885868df51ec0a4b47",
            self.dockerfile,
        )
        for required in ("--only-binary=:all:", "--require-hashes", "fetch_model.py"):
            self.assertIn(required, self.dockerfile)

    def test_runtime_is_offline_and_uses_explicit_artifact_paths(self):
        """A started worker cannot silently fetch or depend on its working directory."""
        for required in (
            'HF_HUB_OFFLINE="1"',
            'TRANSFORMERS_OFFLINE="1"',
            "/opt/continuum/text-translation/artifacts/opus-mt-en-nl",
            'CMD ["python3", "-u", "/opt/continuum/text-translation/subscriber/subscriber.py"]',
            "USER 65532:65532",
        ):
            self.assertIn(required, self.dockerfile)

    def test_local_build_script_cannot_publish_and_targets_amd64(self):
        """Commit 1 cannot accidentally mutate the external release repository."""
        self.assertIn("--platform linux/amd64", self.build_script)
        self.assertIn("--load", self.build_script)
        self.assertNotIn("--push", self.build_script)
        self.assertNotIn("redplanet00", self.build_script)
        self.assertTrue(os.access(SUBSCRIBER_ROOT / "docker.sh", os.X_OK))


class TextTranslationRuntimeTests(unittest.TestCase):
    """Validate local-only loading without importing Transformers or Torch."""

    @classmethod
    def setUpClass(cls):
        cls.runtime = load_module(
            "text_translation_runtime", SUBSCRIBER_ROOT / "src" / "translation_runtime.py"
        )

    def test_loader_uses_local_only_paths_and_cpu(self):
        """Both logical artifacts load from reviewed absolute paths on the CPU."""
        FakeTranslationModel.calls = []
        FakeTranslationTokenizer.calls = []

        with tempfile.TemporaryDirectory() as temporary_directory:
            artifact_path = Path(temporary_directory).resolve()
            for filename in set(self.runtime.MODEL_FILES + self.runtime.TOKENIZER_FILES):
                (artifact_path / filename).touch()

            with mock.patch.object(self.runtime, "ARTIFACT_DIR", artifact_path):
                model, _tokenizer = self.runtime.load_translation_components(
                    FakeTranslationModel, FakeTranslationTokenizer
                )

        self.assertEqual(
            FakeTranslationModel.calls,
            [(str(artifact_path), {"local_files_only": True})],
        )
        self.assertEqual(
            FakeTranslationTokenizer.calls,
            [(str(artifact_path), {"local_files_only": True})],
        )
        self.assertTrue(model.evaluated)
        self.assertEqual(model.device, "cpu")

    def test_runtime_artifact_path_is_fixed_and_absolute(self):
        """Environment or working-directory changes cannot select other weights."""
        expected = Path("/opt/continuum/text-translation/artifacts/opus-mt-en-nl")
        self.assertEqual(self.runtime.ARTIFACT_DIR, expected)
        self.assertTrue(self.runtime.ARTIFACT_DIR.is_absolute())


if __name__ == "__main__":
    unittest.main()
