"""Static tests for the reproducible text-translation publisher image contract."""

import hashlib
from pathlib import Path
import re
import unittest


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
PUBLISHER_ROOT = REPOSITORY_ROOT / "application/text_translation/src/publisher"
PUBLISHER_SOURCE_SHA256 = "d0df9a06314c4494084d069d0517561a22478137057fd89ba380263839ff5857"
PUBLISHER_CORPUS_SHA256 = "33db49d914c3a468e207e7428264217d99684ee872367393bdc63546615c1db4"


class TextTranslationPublisherDependencyLockTests(unittest.TestCase):
    """Validate the complete publisher dependency identity."""

    def test_direct_requirement_preserves_the_existing_mqtt_client(self):
        """The matched image rebuild must not silently change the Paho API."""
        direct_requirements = (PUBLISHER_ROOT / "requirements.in").read_text().splitlines()
        self.assertEqual(direct_requirements, ["paho-mqtt==1.5.1"])

    def test_complete_dependency_set_is_exactly_versioned_and_hashed(self):
        """Paho 1.5.1 has no runtime dependencies and its sdist is hash-locked."""
        dependency_pattern = re.compile(
            r"^(?P<name>[a-z0-9-]+)==(?P<version>\S+) "
            r"--hash=sha256:(?P<hash>[0-9a-f]{64})$"
        )
        dependencies = []
        for raw_line in (PUBLISHER_ROOT / "requirements.lock").read_text().splitlines():
            line = raw_line.strip()
            if not line or line.startswith(("#", "--")):
                continue
            match = dependency_pattern.fullmatch(line)
            self.assertIsNotNone(match, line)
            dependencies.append(match.groupdict())

        self.assertEqual(
            dependencies,
            [
                {
                    "name": "paho-mqtt",
                    "version": "1.5.1",
                    "hash": "9feb068e822be7b3a116324e01fb6028eb1d66412bf98595ae72698965cb1cae",
                }
            ],
        )


class TextTranslationPublisherDockerContractTests(unittest.TestCase):
    """Guard publisher build and runtime behavior without invoking Docker."""

    @classmethod
    def setUpClass(cls):
        cls.dockerfile = (PUBLISHER_ROOT / "Dockerfile").read_text()
        cls.build_script = (PUBLISHER_ROOT / "docker.sh").read_text()

    def test_build_uses_the_matched_reviewed_amd64_base_and_hash_lock(self):
        """The publisher shares Commit 1's immutable Python base and install policy."""
        self.assertIn(
            "python:3.11.13-slim-bookworm@sha256:"
            "cec9aa7aa96eea4fa036e9b82be1e6b325f2e3707f462d885868df51ec0a4b47",
            self.dockerfile,
        )
        self.assertIn("--require-hashes", self.dockerfile)
        self.assertIn("--requirement /tmp/requirements.lock", self.dockerfile)

    def test_dockerfile_copies_and_launches_only_checked_in_publisher_inputs(self):
        """The runtime contains publisher source and corpus without subscriber artifacts."""
        self.assertIn("COPY src/publisher.py src/crime_and_punishment.txt", self.dockerfile)
        self.assertIn(
            'CMD ["python3", "-u", '
            '"/opt/continuum/text-translation/publisher/publisher.py"]',
            self.dockerfile,
        )
        self.assertIn("WORKDIR /opt/continuum/text-translation/publisher", self.dockerfile)
        for forbidden in (
            "model.lock",
            "fetch_model",
            "tokenizer",
            "transformers",
            "huggingface",
            "curl",
            "wget",
        ):
            self.assertNotIn(forbidden, self.dockerfile.lower())

    def test_runtime_is_unprivileged_and_has_no_download_command(self):
        """Only the dependency stage accesses package indexes."""
        self.assertIn("USER 65532:65532", self.dockerfile)
        runtime_section = self.dockerfile.split("FROM ${PYTHON_IMAGE} AS runtime", 1)[1]
        self.assertNotIn("pip install", runtime_section)
        self.assertNotIn("https://", runtime_section)

    def test_local_build_script_is_amd64_only_and_cannot_publish(self):
        """Commit 2's convenience command only loads a local amd64 image."""
        self.assertIn(
            'image_tag="${1:-continuum-text-translation-publisher:local}"',
            self.build_script,
        )
        self.assertIn("--platform linux/amd64", self.build_script)
        self.assertIn("--load", self.build_script)
        for forbidden in ("--push", "docker login", "fzovpec2", "redplanet00"):
            self.assertNotIn(forbidden, self.build_script)


class TextTranslationPublisherBehaviorTests(unittest.TestCase):
    """Prove that Commit 2 leaves publisher protocol inputs byte-for-byte unchanged."""

    def test_publisher_source_is_unchanged(self):
        """MQTT payload, timing, termination, and CLI behavior remain unchanged."""
        source = (PUBLISHER_ROOT / "src/publisher.py").read_bytes()
        self.assertEqual(hashlib.sha256(source).hexdigest(), PUBLISHER_SOURCE_SHA256)

    def test_publisher_corpus_is_unchanged(self):
        """The checked-in text payload source remains unchanged."""
        corpus = (PUBLISHER_ROOT / "src/crime_and_punishment.txt").read_bytes()
        self.assertEqual(hashlib.sha256(corpus).hexdigest(), PUBLISHER_CORPUS_SHA256)


if __name__ == "__main__":
    unittest.main()
