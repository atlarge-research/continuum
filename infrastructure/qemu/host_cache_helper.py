"""Standalone host-side operations for QEMU base-image cache integrity."""

import base64
import json
import os
import sys
import tempfile


PROTOCOL = "continuum-qemu-cache-v1"


def _response(payload):
    """Return one protocol response mapping."""
    response = dict(payload)
    response["protocol"] = PROTOCOL
    return response


def _emit(payload):
    """Emit one canonical protocol response."""
    print(json.dumps(_response(payload), sort_keys=True, separators=(",", ":")))


def _fsync_parent(path):
    """Durably persist a directory-entry change for one path."""
    directory = os.path.dirname(path) or "."
    descriptor = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_unlink(path):
    """Remove one path and fsync its parent, returning False when already absent."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    _fsync_parent(path)
    return True


def readable(path):
    """Return a deterministic readability failure reason, if any."""
    try:
        with open(path, "rb") as filep:
            filep.read(1)
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "unreadable"
    return None


def check(image_path, metadata_path):
    """Return cache-read results without interpreting metadata bytes."""
    reason = readable(image_path)
    if reason:
        return {"status": "invalid", "reason": "image " + reason}
    try:
        with open(metadata_path, "rb") as filep:
            metadata = filep.read()
    except FileNotFoundError:
        return {"status": "invalid", "reason": "metadata missing"}
    except OSError:
        return {"status": "invalid", "reason": "metadata unreadable"}
    return {
        "status": "ok",
        "metadata_b64": base64.b64encode(metadata).decode("ascii"),
    }


def remove_paths(paths):
    """Durably remove exact paths in caller-provided order."""
    for path in paths:
        _durable_unlink(path)


def publish(metadata_path, encoded_payload):
    """Atomically and durably publish one ready-metadata payload."""
    payload = base64.b64decode(encoded_payload.encode("ascii"), validate=True)
    directory = os.path.dirname(metadata_path) or "."
    temporary_path = None
    replaced = False
    try:
        descriptor, temporary_path = tempfile.mkstemp(
            prefix=os.path.basename(metadata_path) + ".",
            suffix=".tmp",
            dir=directory,
        )
        with os.fdopen(descriptor, "wb") as filep:
            if filep.write(payload) != len(payload):
                raise OSError("short metadata write")
            filep.flush()
            os.fsync(filep.fileno())
        os.replace(temporary_path, metadata_path)
        temporary_path = None
        replaced = True
        _fsync_parent(metadata_path)
    except BaseException:
        if temporary_path is not None:
            _durable_unlink(temporary_path)
        if replaced:
            _durable_unlink(metadata_path)
        raise


def main(argv):
    """Dispatch one argv-delimited cache protocol operation."""
    operation = argv[1] if len(argv) > 1 else ""
    if operation == "check" and len(argv) == 4:
        _emit(check(argv[2], argv[3]))
    elif operation == "cleanup" and len(argv) == 6:
        remove_paths(argv[2:])
        _emit({"status": "ok"})
    elif operation == "invalidate" and len(argv) == 3:
        remove_paths(argv[2:])
        _emit({"status": "ok"})
    elif operation == "publish" and len(argv) == 4:
        publish(argv[2], argv[3])
        _emit({"status": "ok"})
    else:
        raise ValueError("invalid cache-helper operation")


if __name__ == "__main__":
    main(sys.argv)
