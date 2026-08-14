# Text-translation release provenance

## Release identity

`en-nl-8aad73b-r1` is the maintained text-translation image release published on
2026-08-14. The publisher and subscriber are one matched release pair. Both are
CPU-only `linux/amd64` images. This release makes no GPU, ARM, or other platform
support claim.

The images were built from a clean worktree at source commit
`bfdd5f3e29e16c43254937199d9139ad27294c49` (`make translation publisher image
reproducible`). The N-02 implementation commits are:

| Boundary | Commit | Subject |
| --- | --- | --- |
| Commit 1: subscriber build and artifact contract | `ff6caa1733fecdb9db7b60b3e6c59c7d3e6f2c9e` | `make translation subscriber image reproducible` |
| Commit 2: publisher build contract | `bfdd5f3e29e16c43254937199d9139ad27294c49` | `make translation publisher image reproducible` |
| Commit 3: deployed image selection | `f8b84a22b8bb7e10c2e3ae552af931027fe708f4` | `pin translation deployment images` |

Commit 3 was made after publication, so it is not part of the image build
context. It is the runtime-selection authority for the published pair.

## Published images

The current canonical images are maintainer-published in the personal Docker
Hub namespace `redplanet00`. Continuum uses the OCI index digest, not the
human-readable tag. Each index contains one `linux/amd64` runtime manifest and
one registry attestation manifest.

| Role | Repository and release tag | OCI index digest used by Continuum | `linux/amd64` platform-manifest digest | Docker-reported local image size |
| --- | --- | --- | --- | ---: |
| Publisher | `redplanet00/continuum-text-translation-publisher:en-nl-8aad73b-r1` | `sha256:502142b93182c63f1225165f44d0308537aac95ee75a99b6f0ba19e668f6f6bf` | `sha256:131c660632302a286541d4d7c1e5e313751eae0d260a59d7929899af3c0a010f` | 48,114,208 bytes |
| Subscriber | `redplanet00/continuum-text-translation-subscriber:en-nl-8aad73b-r1` | `sha256:9aac61a0a1f0fe8938db7283b7f09ab9f9c5f84d95467fa267e9ca3220aabd26` | `sha256:183227758afcf34482871ef704ffc6c26d2a3f616bab2b9cd2b9f8618f41d821` | 620,130,250 bytes |

The size values were recorded from `docker image inspect .Size` measurements of
the local `linux/amd64` images before smoke testing. They are not compressed
registry-transfer sizes. The release process recorded the release date but not
a separate exact push-completion timestamp.

The active runtime constants are in
[`input/configuration/image_requirements.py`](../../input/configuration/image_requirements.py)
and [`text_translation.py`](text_translation.py). They define this flow:

1. Continuum pulls each immutable external OCI index reference.
2. The existing registry workflow retags the selected image into the run-local
   registry as `text_translation_publisher_en-nl-8aad73b-r1` or
   `text_translation_subscriber_en-nl-8aad73b-r1`.
3. Publisher and subscriber deployments use those run-local references.

The local names deliberately contain no Docker Hub owner. Moving the same
reviewed artifacts between external namespaces therefore does not change
experiment YAML or runtime role names. This document describes the runtime
constants; it is not a second runtime configuration authority.

## Model and tokenizer

The subscriber bundles the following maintained baseline:

- model repository: `Helsinki-NLP/opus-mt-en-nl`;
- immutable revision: `8aad73b34ff36c090e7fc8a2eb7e2e7cca235d31`;
- direction: English to Dutch;
- license: Apache-2.0;
- attribution: Helsinki-NLP OPUS-MT English-to-Dutch model.

The model and tokenizer files come from the same pinned upstream snapshot.
[`model.lock.json`](src/subscriber/model.lock.json) is the machine-readable
authority for the baseline classification, upstream model card, individual
artifact paths, sizes, SHA-256 hashes, license, and attribution. The artifacts
are fetched and hash-verified while building the subscriber image, then bundled
at `/opt/continuum/text-translation/artifacts/opus-mt-en-nl`. The runtime sets
Transformers and Hugging Face offline modes and loads only that local directory;
it does not download model or tokenizer files when a worker starts.

The subscriber image records these model-identity labels:

```text
io.continuum.benchmark.baseline=new-en-nl-opus-mt
io.continuum.model.license=Apache-2.0
io.continuum.model.repository=Helsinki-NLP/opus-mt-en-nl
io.continuum.model.revision=8aad73b34ff36c090e7fc8a2eb7e2e7cca235d31
```

The publisher contains no model or tokenizer and therefore has no model labels.
Neither image records the Continuum Git commit in an OCI source/revision label;
the exact source commit is recorded above and in the release-host BuildKit
metadata described under the evidence limitation below.

## Build provenance

Both images use Python 3.11.13 from the same resolved base image:

```text
docker.io/library/python:3.11.13-slim-bookworm@sha256:cec9aa7aa96eea4fa036e9b82be1e6b325f2e3707f462d885868df51ec0a4b47
```

The subscriber's direct constraints are `paho-mqtt==2.1.0`,
`sentencepiece==0.2.0`, `torch==2.5.1+cpu`, and `transformers==4.46.3`.
[`requirements.in`](src/subscriber/requirements.in) records those constraints,
while [`requirements.lock`](src/subscriber/requirements.lock) is the complete
hash-locked CPython 3.11 / `linux/amd64` dependency authority. The publisher
uses `paho-mqtt==1.5.1`; its corresponding authorities are
[`requirements.in`](src/publisher/requirements.in) and
[`requirements.lock`](src/publisher/requirements.lock).

The release host used Docker Engine client/server 28.1.1, Docker Buildx 0.21.1
(`7c2359c`), and BuildKit 0.25.1 with the `docker-container` driver. The SBOM
scanner material resolved to
`docker/buildkit-syft-scanner@sha256:79e7b013cbec16bbb436f312819a49a4a57752b2270c1a9332ae1a10fcc82a68`.

The executed publication builds were:

```sh
docker buildx build \
    --platform linux/amd64 \
    --push \
    --provenance=mode=max \
    --sbom=true \
    --progress=plain \
    --metadata-file /tmp/n02-release.HZC8zN/subscriber-publication-metadata.json \
    --tag redplanet00/continuum-text-translation-subscriber:en-nl-8aad73b-r1 \
    application/text_translation/src/subscriber

docker buildx build \
    --platform linux/amd64 \
    --push \
    --provenance=mode=max \
    --sbom=true \
    --progress=plain \
    --metadata-file /tmp/n02-release.HZC8zN/publisher-publication-metadata.json \
    --tag redplanet00/continuum-text-translation-publisher:en-nl-8aad73b-r1 \
    application/text_translation/src/publisher
```

BuildKit generated an SBOM and maximal provenance attestation for each image.
They are registry attachments associated with the platform manifests:

| Role | Attestation-manifest digest |
| --- | --- |
| Publisher | `sha256:c9c822cb780bbd18f606ac382836235cba50075ee1bef66ab42b6cda23c31f95` |
| Subscriber | `sha256:3cbe001d8f85b7eecbea7123518ac885fe909cbc128e06d56581619063083121` |

The release-host metadata, build logs, and smoke stdout logs remain only under
`/tmp/n02-release.HZC8zN`. They are ephemeral, are not committed or published as
release artifacts, and may disappear with host cleanup. In particular, the
directory does not contain a smoke command transcript, container/image IDs,
captured exit statuses, or logs for the network-disabled checks.

The durable evidence is the checked-in Dockerfiles, dependency and model locks,
artifact-fetch contract, this provenance record, and the immutable registry
manifests and attestations. The registry attestations cover image construction;
they do not attest the smoke runs. In this record, *reproducible* means that a
maintainer can rebuild from pinned, immutable base, dependency, source, and
model inputs whose integrity is checked. Byte-identical OCI output was not
demonstrated or guaranteed. Consistently, both published maximal provenance
attestations report `reproducible: false`.

## Operational validation observed

The following results were observed during the operational release, but the
ephemeral-evidence limitation above means they are not durably linked to the
published platform-manifest digests:

- The locally built candidates were inspected as `linux/amd64` and were observed
  running as the unprivileged runtime user (UID/GID 65532).
- With container networking disabled, the publisher was observed loading its
  checked-in source and corpus and locked `paho-mqtt==1.5.1` installation.
- With container networking disabled, the subscriber was observed loading the
  bundled model and tokenizer, remaining in evaluation mode on CPU, and
  translating `This is a test.` to `Dit is een test.`.
- An MQTT matched-pair smoke run was observed sending one checked-in English
  corpus line to the subscriber. Its stdout reported `Op een uitzonderlijk
  warme avond begin juli kwam er een jongeman uit het garret waarin hij in S
  verbleef.`; both processes were reported as exiting successfully after one
  message. Only their stdout logs remain in the ephemeral release directory.
- Registry inspection confirmed the OCI index and `linux/amd64` manifest
  identities above. In the Docker 28.1.1 release environment, `docker image
  inspect --format '{{.Id}}'` returned those same digest strings for the local
  candidates; BuildKit recorded separate configuration digests. This states the
  exact observed field comparison, not a general equivalence between Docker
  image IDs and OCI platform-manifest digests. No durable record proves that
  those candidates were used for the observed smoke and network-disabled
  checks.
- Deterministic tests verify that Continuum pulls the immutable OCI references,
  retags them under the distinct run-local names, and passes those local names
  to deployment code. This registry/deployment wiring check was static; it was
  not a live Continuum workload execution.

These are operator-observed container results and static integration checks,
not retained validation evidence. They are not VM, cloud-provider, Kubernetes
benchmark, retained-run, or release-matrix certification.

## Historical relationship

The historical image pair used by Continuum came from the supervised BSc-thesis
implementation. Repository content, Git history, and the metadata-only audit of
the old images did not establish the exact original model or tokenizer identity.
No historical image layers were downloaded as part of N-02.

This pinned English-to-Dutch pair is a maintained replacement with reproducibly
specified inputs in the narrow sense defined above and a **new benchmark
baseline**. It must not be described as reproducing the thesis baseline unless
later evidence proves that relationship. The old mutable
`fzovpec2/text_translation:text_translation_publisher` and
`fzovpec2/text_translation:text_translation_subscriber` tags are historical
references, not current build, release, or runtime authorities.

## Licensing and remaining provenance limits

The model and tokenizer attribution and Apache-2.0 license are recorded in the
machine-readable model lock. Continuum source code is distributed under the
repository's [`LICENSE`](../../LICENSE). The checked-in publisher corpus excerpt
predates N-02, and the repository does not retain its exact import provenance or
an application-local corpus license record; this document does not invent one.

## Certification boundary

N-02 closes the checked-in image-build defect, model/tokenizer artifact defect,
publication-provenance defect, and deployed image-selection defect. Live
Continuum workload certification remains a separate activity and is not granted
by N-02.

The application remains uncertified unless and until a nominated scope and the
required retained evidence are recorded under
[`docs/release_certification_matrix.md`](../../docs/release_certification_matrix.md),
which remains the sole certification-status authority. No certification row or
status is changed by this provenance record.
