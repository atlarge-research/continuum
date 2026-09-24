"""Complete worker-pool energy from the FNS engine's datacenter accumulator."""
import math


def energy_tolerance(*values):
    """Bound float32 cumulative-energy rounding at compared sample endpoints.

    Args:
        values (tuple[float]): Native energy values used in a sum or difference.

    Returns:
        float: Joule tolerance using one float32 relative epsilon per value.
    """
    return sum(abs(value) for value in values) * 2**-23 + 1e-6


def datacenter_series(case, rows, native_time_origin_ms=0):
    """Validate cumulative datacenter joules and add explicit pre-arrival idle energy.

    Cordoned hosts disappear from native host telemetry before their final
    interval is exported. The datacenter accumulator retains their contribution.
    Its scope must be the one modeled worker pool. After native completion only
    the workers remaining powered on contribute analytical idle energy.

    Args:
        case (dict): Complete pinned case with workers and optional selected cordon host.
        rows (list[dict]): Native dataCenter rows, retaining original timestamps.
        native_time_origin_ms (float): Earliest arrival offset from the cutoff.

    Returns:
        dict: One aggregate series in the existing energy interpolation format.

    Raises:
        ValueError: Scope, identity, timestamps, coverage or cumulative energy is invalid.
    """
    if case.get("scope") != "complete" or not rows:
        raise ValueError("complete datacenter energy requires a complete case and native rows")
    names = {row.get("data_center_name") for row in rows}
    if names != {"provisional"}:
        raise ValueError("datacenter energy must describe the single provisional worker pool")
    origin = float(native_time_origin_ms)
    if not math.isfinite(origin) or origin < 0:
        raise ValueError("invalid datacenter native time origin")
    removed = case.get("selected_worker") if case["candidate"] == "scale-down" else None
    idle = sum(w["idle_power_w"] for w in case["workers"] if w["node_name"] != removed)
    maximum = sum(w["max_power_w"] for w in case["workers"])
    samples = {0.0: 0.0, origin: idle * origin / 1000}
    last = origin
    for row in rows:
        timestamp, energy = float(row["timestamp"]), float(row["energy_usage"])
        if not math.isfinite(timestamp) or not math.isfinite(energy) or min(timestamp, energy) < 0:
            raise ValueError("invalid datacenter time or cumulative energy")
        if "timestamp_absolute" in row and row["timestamp_absolute"] - timestamp != origin:
            raise ValueError("datacenter native origin differs from task timing")
        at = timestamp + origin
        energy += idle * origin / 1000
        if at in samples and not math.isclose(samples[at], energy, abs_tol=1e-6):
            raise ValueError("conflicting datacenter cumulative samples")
        samples[at] = energy
        last = max(last, at)
    ordered = sorted(samples.items())
    for (before, initial), (after, final) in zip(ordered, ordered[1:]):
        elapsed = (after - before) / 1000
        tolerance = energy_tolerance(initial, final)
        if not idle * elapsed - tolerance <= final - initial <= maximum * elapsed + tolerance:
            raise ValueError("datacenter cumulative energy violates configured worker power bounds")
    return {
        "modeled-worker-pool": {
            "samples": ordered,
            "idle_power_w": idle,
            "native_last_timestamp_ms": last,
        }
    }
