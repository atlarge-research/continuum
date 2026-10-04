"""Verify host/guest time alignment before generating a timed physical workload."""

import math
import time

from opendc_kubernetes import ssh


def clock_alignment(settings, *, maximum_skew_seconds=1.0):
    """Check every explicit guest clock using measured SSH transport bounds.

    A wide transport bracket spanning zero gets one fresh read. Neither attempt
    is accepted until its entire offset bracket fits the configured bound.

    Args:
        settings (dict): Resolved deployment with inventory_hosts and ssh_key.
        maximum_skew_seconds (float): Maximum absolute offset, including transport uncertainty.

    Returns:
        dict: Per-guest epoch clocks, host transport brackets and conservative offset bounds.

    Raises:
        ValueError: The bound or a guest timestamp is invalid, or alignment cannot be established.
        RuntimeError: A bounded guest clock read fails.
    """
    if (
        isinstance(maximum_skew_seconds, bool)
        or not math.isfinite(maximum_skew_seconds)
        or maximum_skew_seconds <= 0
    ):
        raise ValueError("clock skew bound must be finite and positive")
    result = {"maximum_skew_seconds": maximum_skew_seconds, "guests": []}
    for host in settings["inventory_hosts"]:
        target = f'{host["ansible_user"]}@{host["ansible_host"]}'
        attempts = []
        for attempt in range(2):
            before = time.time()
            guest = float(ssh(target, settings["ssh_key"], ["date", "+%s.%N"], timeout=20).decode())
            after = time.time()
            bounds = [guest - after, guest - before]
            attempts.append(
                dict(
                    guest_seconds=guest,
                    host_before_seconds=before,
                    host_after_seconds=after,
                    offset_seconds_bounds=bounds,
                )
            )
            if math.isfinite(guest) and max(abs(value) for value in bounds) <= maximum_skew_seconds:
                result["guests"].append(dict(host=target, **attempts[-1], attempts=attempts))
                break
            if not math.isfinite(guest) or not bounds[0] <= 0 <= bounds[1] or attempt == 1:
                raise ValueError(
                    f"guest clock alignment failed for {target}: offset bounds {bounds}"
                )
    return result
