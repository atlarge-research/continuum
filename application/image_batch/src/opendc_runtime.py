"""Explicit compatibility identities for the preserved and FNS-demo OpenDC engines."""
import copy
import os


RUNTIMES = {
    "legacy": {
        "opendc_version": "master-7db7e1a2331fd",
        "opendc_commit": "7db7e1a2331fd239bf29c4a69eb6fccd6fddbdad",
        "opendc_source_archive_sha256": (
            "df798dae10c0ee3b1911fb01b0dbd25f06f5adb6e8495826dc8ad8b108f4f52d"
        ),
    },
    "fns-demo": {
        "opendc_version": "fns-demo-cf10c06eb73c",
        "opendc_commit": "cf10c06eb73c7e60e1076e376922b1201caf12d1",
        "opendc_source_archive_sha256": (
            "b60208e517037eaeae10f5ef32f36716bda5500de9c9a89f4e8cfc240f5ccb25"
        ),
        "example_repository": "https://github.com/atlarge-research/FNS-demo",
        "example_commit": "41aaa9e20a4e299329924454316e6c91eb39f42f",
        "developer_binary_equivalence_verified": False,
    },
}


def runtime_identity():
    """Return the engine selected by OPENDC_RUNTIME, defaulting to the preserved engine.

    Container builds also declare OPENDC_BUILD_COMMIT so an incompatible runtime
    selection fails before producing inputs or invoking Java. Selection never
    infers the engine from an input file, which could hide a wrong-image execution.

    Returns:
        dict: Engine/source identity and, for FNS, separate example provenance.

    Raises:
        ValueError: The runtime is unknown or disagrees with the container build.
    """
    name = os.environ.get("OPENDC_RUNTIME", "legacy")
    if name not in RUNTIMES:
        raise ValueError(f"unknown OpenDC runtime: {name}")
    identity = dict(RUNTIMES[name])
    compiled = os.environ.get("OPENDC_BUILD_COMMIT")
    if compiled is not None and compiled != identity["opendc_commit"]:
        raise ValueError("selected runtime differs from the container build revision")
    return identity


def fns_runtime():
    """Return whether the explicitly selected engine uses FNS host/datacenter semantics.

    Returns:
        bool: True for the FNS-demo source build, after identity validation.
    """
    return "example_commit" in runtime_identity()


def verify_runtime(manifest):
    """Reject prepared provenance that differs from the explicitly selected engine.

    Args:
        manifest (dict): Prepared input identity and source hashes.

    Raises:
        ValueError: A required engine or example provenance field differs.
    """
    if any(manifest.get(key) != value for key, value in runtime_identity().items()):
        raise ValueError("input version differs from the pinned runner runtime")


def adapt_topology(topology):
    """Copy the single-cluster topology into the selected SDK's topology schema.

    The newer SDK moves the power source from the cluster into its datacenter.
    Host capacities and names remain unchanged; no core deduction occurs here.

    Args:
        topology (dict): Legacy-form single-cluster topology with a power source.

    Returns:
        dict: Independent topology in the selected engine's schema.

    Raises:
        ValueError: FNS conversion receives other than one cluster.
    """
    result = copy.deepcopy(topology)
    if not fns_runtime():
        return result
    clusters = result["clusters"]
    if len(clusters) != 1:
        raise ValueError("FNS adapter expects one cluster per worker pool")
    cluster = clusters[0]
    return {
        "datacenters": [
            {
                "name": cluster.get("name", "application"),
                "clusters": clusters,
                "powerSource": cluster.pop("powerSource"),
            }
        ]
    }


def topology_hosts(topology):
    """Read the single worker pool from a topology in the selected SDK schema.

    Args:
        topology (dict): Prepared topology matching the selected engine.

    Returns:
        list[dict]: Modeled worker host records.
    """
    if fns_runtime():
        return topology["datacenters"][0]["clusters"][0]["hosts"]
    return topology["clusters"][0]["hosts"]
