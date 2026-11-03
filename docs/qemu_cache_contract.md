# QEMU base-image cache contract

QEMU keeps one cache slot per existing base-image name. The owning physical host checks, invalidates, cleans and atomically publishes its own schema-v1 ready marker. A marker is published only after all rebuilt base guests are confirmed stopped. Valid peers retain their files and metadata; no permission repair or cache generations are introduced.

## Baked inputs

The marker compares the RM execution playbooks and sorted content hashes for:

- Those playbooks and the separately executed common base-install playbook.
- Active direct roles and their literal include_role/import_role dependencies. The current included dependencies are KubeEdge's Docker/containerd roles.
- Common netperf sources/defaults and, only when enabled, Mahimahi role files and its available cached source payload, excluding .git as the role does.
- The resolved containerd config.toml copied by the selected role, including KubeEdge's explicit Kubernetes source rather than a guessed stack-local path.
- The actual local instrumented Kubernetes tarball for applicable kubecontrol and kube_kata base hostnames, including its version-derived source selection.

A small base_recipe_inputs mapping additionally records the resolved controller timezone, Mahimahi enablement/source availability, the registry endpoint where Docker/containerd bakes it, KubeEdge's consumed repository version, and immutable manifest/config identities of images actually preloaded into this base. Preload selection is shared with the pull operation: Kubernetes-family cloud/edge bases skip preload, endpoint bases use their tier requirements, and generic names do not match tier-targeted requirements. Mutable-tag identity changes invalidate the slot; known pinned sources must also match their trusted config digest.

Every selected base recipe is preflighted before any owner-cache check or marker invalidation, even if the image is missing. Missing/malformed mandatory playbooks or role task entrypoints/static YAML, missing/unreadable required copied inputs, unavailable image identities and unreadable/non-symlink controller /etc/localtime fail clearly. The timezone is resolved once and reused for guest setup and publication. Mahimahi's absent source is the explicit first-fetch case: preflight records pending-fetch; successful publication after installation binds the then-available payload. Validation itself does not fetch Git or pull images. Old markers lacking the expanded fields are rebuilt through the normal owner-scoped flow, not hand-edited.

## Limits

This is a bounded recipe check, not a general Ansible interpreter or a bit-reproducibility guarantee. Literal included roles are followed conservatively; dynamic role names are unsupported. The existing Mahimahi and instrumented-binary conditions are handled explicitly. Unrelated benchmark frequency/duration, topology and Git revision are not baked inputs. Regular Kubernetes currently fixes its apt repository in role defaults; configured kube_version is not an exact installed patch pin and does not by itself change that role's recipe.

The existing Ubuntu image/download provenance and mutable upstream apt/source contents remain limitations. VM disks/ISOs are not hashed. Concurrent external changes to recipe sources or registry tags during a build are not synchronized; do not mutate these inputs concurrently. Cache tests do not renew runtime or reproduction certification. See docs/configuration_inventory.md and docs/release_certification_matrix.md for remaining acceptance gates.
