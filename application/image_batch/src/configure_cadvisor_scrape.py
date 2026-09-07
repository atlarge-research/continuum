"""Set the FNS demo's cAdvisor scrape cadence without changing other monitors."""

from __future__ import annotations

import json
import subprocess
from typing import Any


NAMESPACE = "monitoring"
NAME = "kubelet"
CADVISOR_PATH = "/metrics/cadvisor"


def cadvisor_endpoint(monitor: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    matches = [
        (index, endpoint)
        for index, endpoint in enumerate(monitor.get("spec", {}).get("endpoints", []))
        if endpoint.get("path") == CADVISOR_PATH
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"expected one {CADVISOR_PATH} endpoint in {NAMESPACE}/{NAME}, "
            f"found {len(matches)}"
        )
    return matches[0]


def patch_operations(monitor: dict[str, Any]) -> list[dict[str, str]]:
    index, endpoint = cadvisor_endpoint(monitor)
    operations = []
    for field, value in (("interval", "5s"), ("scrapeTimeout", "1s")):
        if endpoint.get(field) == value:
            continue
        operation = "replace" if field in endpoint else "add"
        operations.append(
            {
                "op": operation,
                "path": f"/spec/endpoints/{index}/{field}",
                "value": value,
            }
        )
    return operations


def kubectl(*args: str) -> str:
    completed = subprocess.run(
        ["kubectl", *args],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return completed.stdout


def read_monitor() -> dict[str, Any]:
    return json.loads(
        kubectl("get", "servicemonitor", NAME, "-n", NAMESPACE, "-o", "json")
    )


def main() -> None:
    operations = patch_operations(read_monitor())
    if operations:
        kubectl(
            "patch",
            "servicemonitor",
            NAME,
            "-n",
            NAMESPACE,
            "--type=json",
            "-p",
            json.dumps(operations, separators=(",", ":")),
        )
    _, endpoint = cadvisor_endpoint(read_monitor())
    if endpoint.get("interval") != "5s" or endpoint.get("scrapeTimeout") != "1s":
        raise RuntimeError("cAdvisor scrape configuration did not take effect")
    print("monitoring/kubelet cAdvisor scrape configured at 5s (1s timeout)")


if __name__ == "__main__":
    main()
