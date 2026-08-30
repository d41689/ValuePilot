"""Persistent identity for one installed Rate Guard instance."""
from __future__ import annotations

import os
from pathlib import Path
import uuid


_IDENTITY_FILENAME = "instance_id"


def _validated_identity(raw: str) -> str:
    value = raw.strip()
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError) as exc:
        raise RuntimeError("invalid Rate Guard instance identity") from exc
    canonical = str(parsed)
    if value != canonical:
        raise RuntimeError("invalid Rate Guard instance identity")
    return canonical


def load_or_create_instance_id(cache_root: str | Path) -> str:
    """Return the installation UUID, creating it atomically on first boot.

    The identity lives beside the response cache on its persistent volume. A
    malformed existing file is a configuration/integrity failure: regenerating
    it silently would make every correctly pinned client reject this instance.
    """
    root = Path(cache_root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / _IDENTITY_FILENAME
    try:
        return _validated_identity(path.read_text(encoding="ascii"))
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise RuntimeError("cannot read Rate Guard instance identity") from exc

    created = str(uuid.uuid4())
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        try:
            return _validated_identity(path.read_text(encoding="ascii"))
        except OSError as exc:
            raise RuntimeError("cannot read Rate Guard instance identity") from exc
    except OSError as exc:
        raise RuntimeError("cannot create Rate Guard instance identity") from exc

    try:
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(created + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise
    return created
