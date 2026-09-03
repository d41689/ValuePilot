"""Descriptor-bound filesystem authority for isolated SEC acceptance artifacts."""

from __future__ import annotations

import ctypes
import errno
import json
import os
from pathlib import Path
import stat
import uuid
from typing import Any


_DIR_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC | os.O_NOFOLLOW
_FILE_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


def _identity(value: os.stat_result) -> tuple[int, ...]:
    return (
        value.st_dev,
        value.st_ino,
        value.st_mode,
        value.st_size,
        value.st_mtime_ns,
        value.st_ctime_ns,
    )


def _directory_identity(value: os.stat_result) -> tuple[int, ...]:
    return (value.st_dev, value.st_ino, value.st_mode)


def _parts(storage_root: Path, destination: Path) -> tuple[str, ...]:
    try:
        relative = destination.absolute().relative_to(storage_root.absolute())
    except ValueError as exc:
        raise ValueError("acceptance authority must remain inside isolated storage") from exc
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("acceptance authority has an invalid relative path")
    return parts


def _open_root(storage_root: Path) -> tuple[int, os.stat_result]:
    try:
        expected = os.stat(storage_root.absolute(), follow_symlinks=False)
        descriptor = os.open(storage_root.absolute(), _DIR_FLAGS)
    except OSError as exc:
        raise ValueError("acceptance storage root is not a stable directory") from exc
    actual = os.fstat(descriptor)
    if not stat.S_ISDIR(actual.st_mode) or _directory_identity(actual) != _directory_identity(expected):
        os.close(descriptor)
        raise ValueError("acceptance storage root identity changed")
    return descriptor, actual


def _open_parent(
    storage_root: Path, parts: tuple[str, ...], *, create: bool
) -> tuple[list[int], list[tuple[int, str, os.stat_result]], os.stat_result]:
    root_fd, root_identity = _open_root(storage_root)
    fds = [root_fd]
    chain: list[tuple[int, str, os.stat_result]] = []
    try:
        for component in parts[:-1]:
            parent_fd = fds[-1]
            try:
                child_fd = os.open(component, _DIR_FLAGS, dir_fd=parent_fd)
            except FileNotFoundError:
                if not create:
                    raise
                os.mkdir(component, 0o750, dir_fd=parent_fd)
                child_fd = os.open(component, _DIR_FLAGS, dir_fd=parent_fd)
            except OSError as exc:
                raise ValueError(
                    "acceptance storage component is unsafe"
                ) from exc
            child_identity = os.fstat(child_fd)
            if not stat.S_ISDIR(child_identity.st_mode):
                os.close(child_fd)
                raise ValueError("acceptance storage component is not a directory")
            chain.append((parent_fd, component, child_identity))
            fds.append(child_fd)
        return fds, chain, root_identity
    except Exception:
        for descriptor in reversed(fds):
            os.close(descriptor)
        raise


def _verify_chain(
    storage_root: Path,
    fds: list[int],
    chain: list[tuple[int, str, os.stat_result]],
    root_identity: os.stat_result,
) -> None:
    for parent_fd, component, expected in reversed(chain):
        try:
            current = os.stat(component, dir_fd=parent_fd, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("acceptance storage identity race: component disappeared") from exc
        if _directory_identity(current) != _directory_identity(expected):
            raise ValueError("acceptance storage identity race: component changed")
    try:
        current_root = os.stat(storage_root.absolute(), follow_symlinks=False)
    except OSError as exc:
        raise ValueError("acceptance storage identity race: root disappeared") from exc
    if _directory_identity(current_root) != _directory_identity(root_identity) or _directory_identity(
        os.fstat(fds[0])
    ) != _directory_identity(root_identity):
        raise ValueError("acceptance storage identity race: root changed")


def secure_read_bytes(
    *, storage_root: Path, source: Path, missing_ok: bool = False
) -> bytes | None:
    """Read one regular authority file from one verified descriptor chain."""

    parts = _parts(storage_root, source)
    try:
        fds, chain, root_identity = _open_parent(
            storage_root, parts, create=False
        )
    except FileNotFoundError:
        if missing_ok:
            return None
        raise ValueError("acceptance authority file is missing") from None
    try:
        parent_fd = fds[-1]
        try:
            file_fd = os.open(parts[-1], _FILE_FLAGS, dir_fd=parent_fd)
        except FileNotFoundError:
            if missing_ok:
                _verify_chain(storage_root, fds, chain, root_identity)
                return None
            raise ValueError("acceptance authority file is missing") from None
        except OSError as exc:
            raise ValueError("acceptance authority file is unsafe") from exc
        try:
            before = os.fstat(file_fd)
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("acceptance authority must be a regular file")
            chunks: list[bytes] = []
            observed = 0
            while True:
                chunk = os.read(file_fd, 1024 * 1024)
                if not chunk:
                    break
                chunks.append(chunk)
                observed += len(chunk)
            after = os.fstat(file_fd)
            current = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            if (
                _identity(before) != _identity(after)
                or _identity(before) != _identity(current)
                or observed != before.st_size
            ):
                raise ValueError("acceptance storage identity race: file changed during read")
            _verify_chain(storage_root, fds, chain, root_identity)
            return b"".join(chunks)
        finally:
            os.close(file_fd)
    finally:
        for descriptor in reversed(fds):
            os.close(descriptor)


def secure_regular_file_exists(*, storage_root: Path, source: Path) -> bool:
    return secure_read_bytes(storage_root=storage_root, source=source, missing_ok=True) is not None


def secure_read_json(*, storage_root: Path, source: Path) -> dict[str, Any]:
    encoded = secure_read_bytes(storage_root=storage_root, source=source)
    assert encoded is not None
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"acceptance JSON is malformed: {source}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"acceptance JSON must be an object: {source}")
    return payload


_AT_FDCWD = -100
_AT_SYMLINK_FOLLOW = 0x400
_AT_EMPTY_PATH = 0x1000


def _linkat(
    old_directory_fd: int,
    old_path: bytes,
    new_directory_fd: int,
    new_path: str,
    flags: int,
) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    linkat = getattr(libc, "linkat", None)
    if linkat is None:
        raise OSError(errno.ENOSYS, "descriptor publication is unavailable")
    linkat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
    linkat.restype = ctypes.c_int
    if linkat(
        old_directory_fd,
        old_path,
        new_directory_fd,
        new_path.encode(),
        flags,
    ) != 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error), new_path)


def _publish_held_descriptor(
    *, descriptor: int, parent_fd: int, destination: str, anonymous: bool
) -> None:
    if anonymous:
        _linkat(descriptor, b"", parent_fd, destination, _AT_EMPTY_PATH)
    else:
        _linkat(
            _AT_FDCWD,
            f"/proc/self/fd/{descriptor}".encode(),
            parent_fd,
            destination,
            _AT_SYMLINK_FOLLOW,
        )


def secure_atomic_write_bytes(
    *, storage_root: Path, destination: Path, content: bytes
) -> None:
    """Create an immutable authority artifact using descriptor-relative I/O."""

    parts = _parts(storage_root, destination)
    existing = secure_read_bytes(
        storage_root=storage_root, source=destination, missing_ok=True
    )
    if existing is not None:
        if existing == content:
            return
        raise ValueError("refusing to overwrite existing acceptance authority")
    fds, chain, root_identity = _open_parent(storage_root, parts, create=True)
    parent_fd = fds[-1]
    temporary: str | None = None
    descriptor: int | None = None
    published = False

    def remove_owned_publication() -> None:
        if not published or descriptor is None:
            return
        try:
            current = os.stat(parts[-1], dir_fd=parent_fd, follow_symlinks=False)
            held = os.fstat(descriptor)
            if (current.st_dev, current.st_ino) == (held.st_dev, held.st_ino):
                os.unlink(parts[-1], dir_fd=parent_fd)
                os.fsync(parent_fd)
        except OSError:
            pass

    def cleanup_temporary_entries() -> None:
        if descriptor is None or temporary is None:
            return
        held = os.fstat(descriptor)
        if not stat.S_ISREG(held.st_mode):
            raise ValueError("acceptance authority temporary object is invalid")
        try:
            item = os.stat(temporary, dir_fd=parent_fd, follow_symlinks=False)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValueError("acceptance authority temporary cleanup failed") from exc
        if not stat.S_ISREG(item.st_mode) or _identity(item) != _identity(held):
            return
        try:
            os.unlink(temporary, dir_fd=parent_fd)
        except FileNotFoundError:
            return
        except OSError as exc:
            raise ValueError("acceptance authority temporary cleanup failed") from exc

    try:
        anonymous = False
        temporary_flag = getattr(os, "O_TMPFILE", 0)
        if temporary_flag:
            try:
                descriptor = os.open(
                    ".",
                    os.O_RDWR | os.O_CLOEXEC | temporary_flag,
                    0o640,
                    dir_fd=parent_fd,
                )
                anonymous = True
            except OSError as exc:
                if exc.errno not in {
                    errno.EINVAL,
                    errno.EISDIR,
                    errno.ENOSYS,
                    errno.EOPNOTSUPP,
                    errno.EPERM,
                }:
                    raise
        if descriptor is None:
            temporary = f".{parts[-1]}.{uuid.uuid4().hex}.tmp"
            descriptor = os.open(
                temporary,
                os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW,
                0o640,
                dir_fd=parent_fd,
            )
        held_before = os.fstat(descriptor)
        if not stat.S_ISREG(held_before.st_mode) or held_before.st_size != 0:
            raise ValueError("acceptance authority temporary object is invalid")
        view = memoryview(content)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise ValueError("acceptance authority descriptor write failed")
            view = view[written:]
        os.fsync(descriptor)
        held_after_write = os.fstat(descriptor)
        if held_after_write.st_size != len(content):
            raise ValueError("acceptance authority descriptor size mismatch")
        _verify_chain(storage_root, fds, chain, root_identity)
        try:
            _publish_held_descriptor(
                descriptor=descriptor,
                parent_fd=parent_fd,
                destination=parts[-1],
                anonymous=anonymous,
            )
        except OSError as exc:
            if anonymous and exc.errno in {
                errno.EINVAL,
                errno.ENOENT,
                errno.ENOSYS,
                errno.EOPNOTSUPP,
                errno.EPERM,
            }:
                os.close(descriptor)
                descriptor = None
                temporary = f".{parts[-1]}.{uuid.uuid4().hex}.tmp"
                descriptor = os.open(
                    temporary,
                    os.O_RDWR
                    | os.O_CREAT
                    | os.O_EXCL
                    | os.O_CLOEXEC
                    | os.O_NOFOLLOW,
                    0o640,
                    dir_fd=parent_fd,
                )
                view = memoryview(content)
                while view:
                    written = os.write(descriptor, view)
                    if written <= 0:
                        raise ValueError("acceptance authority descriptor write failed")
                    view = view[written:]
                os.fsync(descriptor)
                _publish_held_descriptor(
                    descriptor=descriptor,
                    parent_fd=parent_fd,
                    destination=parts[-1],
                    anonymous=False,
                )
            else:
                raise
        published = True
        cleanup_temporary_entries()
        published_identity = os.stat(
            parts[-1], dir_fd=parent_fd, follow_symlinks=False
        )
        held_identity = os.fstat(descriptor)
        if (
            not stat.S_ISREG(published_identity.st_mode)
            or _identity(published_identity) != _identity(held_identity)
            or held_identity.st_nlink != 1
        ):
            raise ValueError("acceptance authority published object identity mismatch")
        os.fsync(parent_fd)
        _verify_chain(storage_root, fds, chain, root_identity)
        written = secure_read_bytes(storage_root=storage_root, source=destination)
        if written != content:
            raise ValueError("acceptance authority write verification failed")
    except OSError as exc:
        remove_owned_publication()
        if exc.errno == errno.EEXIST:
            raise ValueError("refusing to replace existing acceptance authority") from exc
        raise ValueError("descriptor-based acceptance authority publication failed") from exc
    except Exception:
        remove_owned_publication()
        raise
    finally:
        try:
            cleanup_temporary_entries()
        except (OSError, ValueError):
            pass
        if descriptor is not None:
            os.close(descriptor)
        for descriptor in reversed(fds):
            os.close(descriptor)
