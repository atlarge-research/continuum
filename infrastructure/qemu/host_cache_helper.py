"""Standalone host-side operations for QEMU base-image cache integrity."""

import base64
import json
import os
import stat
import subprocess
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


def _report_failure(operation, path, error):
    """Best-effort read-only context; never replace the original filesystem error."""
    try:
        details = ["QEMU cache %s failed for %r: %s: %s" %
                   (operation, path, type(error).__name__, error)]
        for target in (path, os.path.dirname(path) or "."):
            try:
                metadata = os.lstat(target)
                details.append("%r uid=%s gid=%s mode=%s sticky=%s" % (
                    target, metadata.st_uid, metadata.st_gid,
                    oct(stat.S_IMODE(metadata.st_mode)), bool(metadata.st_mode & stat.S_ISVTX)))
            except OSError as diagnostic_error:
                details.append("%r stat unavailable: %s" % (target, diagnostic_error))
            try:
                acl = subprocess.run(
                    ["getfacl", "-n", "-p", "--", target], check=False,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=3,
                )
                details.append("ACL %r (rc=%s): %s" % (
                    target, acl.returncode, acl.stdout[:8192].decode("utf-8", "replace")))
            except (OSError, subprocess.SubprocessError) as diagnostic_error:
                details.append("ACL %r unavailable: %s" % (target, diagnostic_error))
        details.append("An operator must inspect this exact cache slot and parent ownership, "
                       "permissions, sticky bit and ACLs; no automatic privilege or repair is used.")
        print("\n".join(details), file=sys.stderr)
    except Exception:  # Diagnostics must not hide the original operation failure.
        pass


def _durable_unlink(path):
    """Remove one path and fsync its parent, returning False when already absent."""
    try:
        os.unlink(path)
    except FileNotFoundError:
        return False
    except OSError as error:
        _report_failure("unlink", path, error)
        raise
    try:
        _fsync_parent(path)
    except OSError as error:
        _report_failure("fsync parent after unlink", path, error)
        raise
    return True


def readable(path):
    """Return a deterministic readability failure reason, if any."""
    try:
        with open(path, "rb") as filep:
            filep.read(1)
    except FileNotFoundError:
        return "missing"
    except OSError as error:
        _report_failure("read image", path, error)
        raise
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
    except OSError as error:
        _report_failure("read metadata", metadata_path, error)
        raise
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
    except BaseException as error:
        if isinstance(error, OSError):
            _report_failure("publish", metadata_path, error)
        for cleanup_path in (temporary_path, metadata_path if replaced else None):
            if cleanup_path is not None:
                try:
                    _durable_unlink(cleanup_path)
                except OSError:
                    pass  # Already diagnosed; retain the original publication failure.
        raise


def main(argv):
    """Dispatch one argv-delimited cache protocol operation."""
    operation = argv[1] if len(argv) > 1 else ""
    if operation == "check" and len(argv) == 4:
        _emit(check(argv[2], argv[3]))
    elif operation == "cleanup" and len(argv) == 5:
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
