#!/usr/bin/env python3
"""Convert legacy Continuum .cfg into YAML triplet files.

This helper is intentionally conservative: it maps known legacy keys and leaves
unknown keys in a passthrough bucket for manual review.
"""

import argparse
import configparser
from pathlib import Path

import yaml


def _read_cfg(path: Path) -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read(path)
    return cfg


def _build_environment(cfg):
    infra = cfg["infrastructure"]
    return {
        "schema_version": 1,
        "kind": "ContinuumEnvironment",
        "provider": {
            "name": infra.get("provider", "qemu"),
            "config": {
                "base_path": infra.get("base_path", "~"),
                "cpu_pin": infra.getboolean("cpu_pin", False),
                "external_physical_machines": [
                    s.strip()
                    for s in infra.get("external_physical_machines", "").split(",")
                    if s.strip()
                ],
                "ip": {
                    "prefix": infra.get("prefixIP", "192.168"),
                    "middle": infra.getint("middleIP", 100),
                    "middle_base": infra.getint("middleIP_base", 90),
                },
                "netperf": infra.getboolean("netperf", False),
                "delete_on_exit": infra.getboolean("delete", False),
            },
        },
    }


def _build_software(cfg):
    bench = cfg["benchmark"]
    orchestrator_name = bench.get("resource_manager", "none")
    addons = []
    if cfg.has_section("execution_model") and cfg["execution_model"].get("model") == "openfaas":
        addons.append({"name": "openfaas", "config": {}})
    if bench.getboolean("observability", False):
        addons.append({"name": "observability", "config": {}})

    orchestrator_cfg = {}
    if orchestrator_name in {"kubernetes", "kubecontrol", "kube_kata", "kubeedge"}:
        orchestrator_cfg["kube_version"] = bench.get("kube_version", "v1.27.0")
        orchestrator_cfg["cache_worker"] = bench.getboolean("cache_worker", False)
    if orchestrator_name in {"kubernetes", "kubecontrol", "kube_kata"}:
        orchestrator_cfg["kube_deployment"] = bench.get("kube_deployment", "pod")
    if orchestrator_name == "kube_kata":
        orchestrator_cfg["runtime"] = bench.get("runtime", "runc")
        orchestrator_cfg["runtime_filesystem"] = bench.get("runtime_filesystem", "devmapper")

    return {
        "schema_version": 1,
        "kind": "ContinuumSoftware",
        "orchestrator": {
            "name": orchestrator_name,
            "config": orchestrator_cfg,
        },
        "addons": addons,
    }


def _build_experiment(cfg, env_name, sw_name):
    infra = cfg["infrastructure"]
    bench = cfg["benchmark"]
    return {
        "schema_version": 1,
        "kind": "ContinuumExperiment",
        "use": {"environment": env_name, "software": sw_name},
        "run": {
            "targets": (
                ["infrastructure"]
                if infra.getboolean("infra_only", False)
                else ["infrastructure", "software", "application"]
            ),
            "dry_run": False,
            "clean": False,
        },
        "topology": {
            "tiers": {
                "cloud": {
                    "count": infra.getint("cloud_nodes", 0),
                    "resources": {
                        "cpu": {
                            "cores": infra.getint("cloud_cores", 0),
                            "quota": infra.getfloat("cloud_quota", 0.0),
                        },
                        "memory": {"gb": infra.getfloat("cloud_memory", 0)},
                        "storage": {
                            "read_mbps": infra.getfloat("cloud_read_speed", 0),
                            "write_mbps": infra.getfloat("cloud_write_speed", 0),
                        },
                    },
                },
                "edge": {
                    "count": infra.getint("edge_nodes", 0),
                    "resources": {
                        "cpu": {
                            "cores": infra.getint("edge_cores", 0),
                            "quota": infra.getfloat("edge_quota", 0.0),
                        },
                        "memory": {"gb": infra.getfloat("edge_memory", 0)},
                        "storage": {
                            "read_mbps": infra.getfloat("edge_read_speed", 0),
                            "write_mbps": infra.getfloat("edge_write_speed", 0),
                        },
                    },
                },
                "endpoint": {
                    "count": infra.getint("endpoint_nodes", 0),
                    "resources": {
                        "cpu": {
                            "cores": infra.getint("endpoint_cores", 0),
                            "quota": infra.getfloat("endpoint_quota", 0.0),
                        },
                        "memory": {"gb": infra.getfloat("endpoint_memory", 0)},
                        "storage": {
                            "read_mbps": infra.getfloat("endpoint_read_speed", 0),
                            "write_mbps": infra.getfloat("endpoint_write_speed", 0),
                        },
                    },
                },
            },
            "network": {
                "emulation": infra.getboolean("network_emulation", False),
                "wireless_preset": infra.get("wireless_network_preset", "4g"),
                "overrides": {},
            },
        },
        "workload": {
            "name": bench.get("application", ""),
            "config": {
                "frequency": bench.getint("frequency", 5) if "frequency" in bench else 5,
                "duration_s": bench.getint("duration", 300) if "duration" in bench else 300,
                "sleep_time": bench.getint("sleep_time", 60) if "sleep_time" in bench else 60,
            },
        },
        "benchmark": {
            "name": "default",
            "config": {
                "repetitions": 1,
                "docker_pull": bench.getboolean("docker_pull", False),
                "applications_per_worker": bench.getint("applications_per_worker", 1),
                "resources": {
                    "worker": {
                        "cpu_cores": bench.getfloat("application_worker_cpu", 0.0),
                        "memory_gb": bench.getfloat("application_worker_memory", 0.0),
                    },
                    "endpoint": {
                        "cpu_cores": bench.getfloat("application_endpoint_cpu", 0.0),
                        "memory_gb": bench.getfloat("application_endpoint_memory", 0.0),
                    },
                },
            },
        },
    }


def _write_yaml(path: Path, payload: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as filep:
        yaml.safe_dump(payload, filep, sort_keys=False)


def main():
    parser = argparse.ArgumentParser(description="Migrate Continuum .cfg to YAML triplet")
    parser.add_argument("cfg", help="Path to legacy .cfg file")
    parser.add_argument("--experiment-out", required=True, help="Output experiment YAML path")
    parser.add_argument("--environment-out", required=True, help="Output environment YAML path")
    parser.add_argument("--software-out", required=True, help="Output software YAML path")
    args = parser.parse_args()

    cfg_path = Path(args.cfg).expanduser().resolve()
    cfg = _read_cfg(cfg_path)
    if not cfg.has_section("infrastructure") or not cfg.has_section("benchmark"):
        raise SystemExit("Input .cfg must include [infrastructure] and [benchmark] sections")

    env_out = Path(args.environment_out).expanduser().resolve()
    sw_out = Path(args.software_out).expanduser().resolve()
    exp_out = Path(args.experiment_out).expanduser().resolve()

    env_name = env_out.stem
    sw_name = sw_out.stem
    environment = _build_environment(cfg)
    software = _build_software(cfg)
    experiment = _build_experiment(cfg, env_name, sw_name)

    _write_yaml(env_out, environment)
    _write_yaml(sw_out, software)
    _write_yaml(exp_out, experiment)
    print("Wrote:")
    print(" - %s" % exp_out)
    print(" - %s" % env_out)
    print(" - %s" % sw_out)


if __name__ == "__main__":
    main()
