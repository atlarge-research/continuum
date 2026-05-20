"""State persistence helpers for phase-based execution."""

import json
import logging
import os
import tempfile
from datetime import datetime, timezone

from infrastructure import machine as machine_utils
from infrastructure.machine import Machine
from input.configuration import config_access, resume_contract

_MACHINE_FIELDS = [
    "name",
    "is_local",
    "cores",
    "cloud_controller",
    "clouds",
    "edges",
    "endpoints",
    "cloud_controller_ips",
    "cloud_ips",
    "edge_ips",
    "endpoint_ips",
    "base_ips",
    "cloud_controller_ips_internal",
    "cloud_ips_internal",
    "edge_ips_internal",
    "endpoint_ips_internal",
    "cloud_controller_names",
    "cloud_names",
    "edge_names",
    "endpoint_names",
    "base_names",
]

_MACHINE_DERIVED_FIELDS = {"name_sanitized", "user", "ip"}
_MACHINE_SCHEMA_VALIDATED = False
_STATE_SCHEMA_VERSION = 2
_STATE_KIND = "ContinuumState"
_PHASE_ORDER = {
    "infrastructure": 1,
    "software": 2,
    "application": 3,
}


def state_file_path(config):
    """Return the state file location under .continuum.

    Args:
        config (dict): Parsed Continuum configuration.

    Returns:
        str: Path to the state file.
    """
    return os.path.join(config["infrastructure"]["base_path"], ".continuum", "state.json")


def phase_rank(phase):
    """Return numeric rank of phase for ordering checks."""
    return _PHASE_ORDER.get(str(phase), -1)


def _validate_phase(phase):
    """Return a valid phase string or raise ValueError."""
    if phase not in _PHASE_ORDER:
        raise ValueError(
            "Invalid state phase_completed %r (allowed: %s)"
            % (phase, ", ".join(sorted(_PHASE_ORDER.keys())))
        )
    return phase


def _validate_machine_schema():
    """Fail fast when Machine schema drifts from state schema assumptions."""
    global _MACHINE_SCHEMA_VALIDATED
    if _MACHINE_SCHEMA_VALIDATED:
        return

    probe = Machine("state_schema_probe", True)
    machine_attrs = set(probe.__dict__.keys())
    schema_attrs = set(_MACHINE_FIELDS)

    missing_fields = sorted(field for field in _MACHINE_FIELDS if field not in machine_attrs)
    if missing_fields:
        raise ValueError(
            "State schema out of date: fields missing on Machine: %s" % (", ".join(missing_fields))
        )

    unexpected_fields = sorted(
        field
        for field in machine_attrs
        if field not in schema_attrs and field not in _MACHINE_DERIVED_FIELDS
    )
    if unexpected_fields:
        raise ValueError(
            "State schema review required: new Machine fields not covered by schema/exclude list: %s"
            % (", ".join(unexpected_fields))
        )

    required_identity_fields = {"name", "is_local"}
    if not required_identity_fields.issubset(schema_attrs):
        missing_identity = sorted(required_identity_fields - schema_attrs)
        raise ValueError(
            "State schema invalid: missing required identity field(s): %s"
            % (", ".join(missing_identity))
        )

    _MACHINE_SCHEMA_VALIDATED = True


def _serialize_machine(machine):
    """Serialize one Machine object using the explicit state schema.

    Args:
        machine (Machine): Machine object to serialize.

    Returns:
        dict: Serialized machine payload.
    """
    _validate_machine_schema()
    return {field: getattr(machine, field) for field in _MACHINE_FIELDS}


def _serialize_machines(machines):
    """Serialize a list of Machine objects.

    Args:
        machines (list[Machine]): Machine objects to serialize.

    Returns:
        list[dict]: Serialized machine payloads.
    """
    return [_serialize_machine(machine) for machine in machines]


def _reconstruct_machine(machine_data):
    """Reconstruct one Machine object from serialized state.

    Args:
        machine_data (dict): Serialized machine payload.

    Returns:
        Machine: Reconstructed machine object.
    """
    _validate_machine_schema()
    if not isinstance(machine_data, dict):
        raise ValueError("Invalid state machine_data entry: expected mapping")

    missing_fields = [field for field in _MACHINE_FIELDS if field not in machine_data]
    if missing_fields:
        raise ValueError(
            "Invalid state machine_data entry: missing required field %s"
            % (missing_fields[0],)
        )
    extra_fields = sorted(
        field
        for field in machine_data.keys()
        if field not in set(_MACHINE_FIELDS) and field not in _MACHINE_DERIVED_FIELDS
    )
    if extra_fields:
        raise ValueError(
            "Invalid state machine_data entry: unexpected field %s" % (extra_fields[0],)
        )
    if not isinstance(machine_data["name"], str) or not machine_data["name"].strip():
        raise ValueError("Invalid state machine_data entry: name must be a non-empty string")
    if not isinstance(machine_data["is_local"], bool):
        raise ValueError("Invalid state machine_data entry: is_local must be boolean")

    machine = Machine(machine_data["name"], machine_data["is_local"])
    for field in _MACHINE_FIELDS:
        if field in ("name", "is_local"):
            continue
        if field in machine_data:
            setattr(machine, field, machine_data[field])
    return machine


def _reconstruct_machines(machine_data):
    """Reconstruct a list of Machine objects from serialized payloads.

    Args:
        machine_data (list[dict]): Serialized machine payloads.

    Returns:
        list[Machine]: Reconstructed machine objects.
    """
    if not isinstance(machine_data, list) or not machine_data:
        raise ValueError("Invalid state machine_data: expected non-empty list")
    return [_reconstruct_machine(data) for data in machine_data]


def _validate_state_schema(state):
    """Validate the persisted state envelope and return it."""
    if not isinstance(state, dict):
        raise ValueError("Invalid state file: expected top-level mapping")
    if state.get("schema_version") != _STATE_SCHEMA_VERSION:
        raise ValueError(
            "State schema mismatch: expected schema_version %s but found %r"
            % (_STATE_SCHEMA_VERSION, state.get("schema_version"))
        )
    if state.get("kind") != _STATE_KIND:
        raise ValueError(
            "State schema mismatch: expected kind %r but found %r"
            % (_STATE_KIND, state.get("kind"))
        )
    created_at = state.get("created_at")
    if not isinstance(created_at, str) or not created_at.strip():
        raise ValueError("Invalid state file: created_at must be a non-empty string")
    _validate_phase(state.get("phase_completed"))
    resume_contract.validate_persisted_resume_contract(
        state.get("resume_contract"),
        "state.resume_contract",
    )
    _reconstruct_machines(state.get("machine_data"))
    return state


def save_state(config, phase_completed, machines):
    """Persist run state for later resume support.

    Args:
        config (dict): Parsed Continuum configuration.
        phase_completed (str): Last completed phase identifier.
        machines (list[Machine]): Machine objects to persist.

    Returns:
        str: Path to the written state file.
    """
    _validate_phase(phase_completed)
    contract = resume_contract.build_persisted_resume_contract(config)
    payload = {
        "schema_version": _STATE_SCHEMA_VERSION,
        "kind": _STATE_KIND,
        "created_at": datetime.now(tz=timezone.utc).isoformat(),
        "phase_completed": phase_completed,
        "resume_contract": contract,
        "provider": config["infrastructure"]["provider"],
        "cloud_nodes": config["infrastructure"]["cloud_nodes"],
        "edge_nodes": config["infrastructure"]["edge_nodes"],
        "endpoint_nodes": config["infrastructure"]["endpoint_nodes"],
        "resource_manager": config_access.orchestrator_name(config),
        "ssh_key": config.get("ssh_key"),
        "cloud_ssh": config.get("cloud_ssh", []),
        "edge_ssh": config.get("edge_ssh", []),
        "endpoint_ssh": config.get("endpoint_ssh", []),
        "machine_data": _serialize_machines(machines),
    }

    path = state_file_path(config)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=os.path.dirname(path),
            prefix=".state.",
            suffix=".tmp",
            delete=False,
        ) as filep:
            temp_path = filep.name
            json.dump(payload, filep, indent=2, sort_keys=True)
            filep.write("\n")
            filep.flush()
            os.fsync(filep.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path and os.path.exists(temp_path):
            os.unlink(temp_path)

    return path


def load_state(config):
    """Load raw state JSON from disk.

    Args:
        config (dict): Parsed Continuum configuration.

    Returns:
        dict: Raw state payload.
    """
    path = state_file_path(config)
    with open(path, "r", encoding="utf-8") as filep:
        return json.load(filep)


def validate_state_compatibility(config, state):
    """Return compatibility issues when comparing runtime config with saved state.

    Args:
        config (dict): Parsed Continuum configuration.
        state (dict): Loaded state payload.

    Returns:
        list[str]: Validation errors, empty when compatible.
    """
    errors = []
    try:
        _validate_state_schema(state)
    except ValueError as exc:
        return [str(exc)]

    expected = {
        "provider": config["infrastructure"]["provider"],
        "cloud_nodes": config["infrastructure"]["cloud_nodes"],
        "edge_nodes": config["infrastructure"]["edge_nodes"],
        "endpoint_nodes": config["infrastructure"]["endpoint_nodes"],
        "resource_manager": config_access.orchestrator_name(config),
    }

    for key, value in expected.items():
        if state.get(key) != value:
            errors.append(
                "State mismatch for %s: expected %r but found %r" % (key, value, state.get(key))
            )

    try:
        resume_contract.validate_current_resume_contract(
            config,
            state.get("resume_contract"),
            "state.resume_contract",
        )
    except ValueError as exc:
        errors.append("Resume contract mismatch: %s" % (exc,))

    return errors


def load_and_reconstruct(config):
    """Load state payload and reconstruct persisted machine objects.

    Args:
        config (dict): Parsed Continuum configuration.

    Returns:
        tuple[dict, list[Machine]]: Raw state payload and reconstructed machines.
    """
    state = _validate_state_schema(load_state(config))
    machines = _reconstruct_machines(state.get("machine_data", []))
    return state, machines


def load_resume_state(config, required_phase):
    """Load state for phase-resume and rehydrate derived runtime fields.

    Args:
        config (dict): Parsed Continuum configuration.
        required_phase (str | None): Minimum phase that must be completed in state.

    Returns:
        tuple[dict, list[Machine]]: Loaded state payload and reconstructed machines.

    Raises:
        FileNotFoundError: When no state file exists.
        OSError: On state read I/O failures.
        json.JSONDecodeError: When state file is malformed JSON.
        ValueError: On compatibility/phase validation failures.
    """
    path = state_file_path(config)
    state_payload, machines = load_and_reconstruct(config)

    errors = validate_state_compatibility(config, state_payload)
    if errors:
        raise ValueError(
            "State file is not compatible with current configuration %s: %s"
            % (path, "; ".join(errors))
        )

    completed_phase = _validate_phase(state_payload.get("phase_completed"))
    if required_phase and phase_rank(completed_phase) < phase_rank(required_phase):
        raise ValueError(
            "State file phase is too early for requested targets (%s): need '%s', found '%s'"
            % (path, required_phase, completed_phase)
        )

    # Rebuild derived config lists used across modules.
    machine_utils.gather_ssh(config, machines)
    machine_utils.gather_ips(config, machines)

    if state_payload.get("ssh_key"):
        config["ssh_key"] = state_payload["ssh_key"]

    logging.info(
        "Loaded state from %s (phase_completed=%s)",
        path,
        completed_phase,
    )
    return state_payload, machines
