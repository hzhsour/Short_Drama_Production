"""Replaceable artifact storage; the default implementation never replaces media."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Protocol


class StorageError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class ArtifactStorage(Protocol):
    def put(self, source: Path, key: str) -> dict[str, Any]: ...

    def verify(self, artifact: dict[str, Any]) -> bool: ...


class LocalStorage:
    """Store immutable objects under a configured local/mounted persistent path.

    S3/other storage backends can implement the same protocol. This backend does
    not upload anything, and does not assert that an ephemeral cloud disk persists.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        relative = Path(key)
        if not key or relative.is_absolute() or ".." in relative.parts or "\\" in key:
            raise StorageError("artifact key must be a relative path without traversal")
        destination = (self.root / relative).resolve()
        if not destination.is_relative_to(self.root) or destination == self.root:
            raise StorageError("artifact key escapes storage root")
        return destination

    def put(self, source: Path, key: str) -> dict[str, Any]:
        source = Path(source)
        if not source.is_file() or source.stat().st_size == 0:
            raise StorageError("artifact source is missing or empty")
        checksum = sha256_file(source)
        destination = self.path_for(key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            if not destination.is_file() or sha256_file(destination) != checksum:
                raise StorageError("immutable artifact collision; existing media was preserved")
        else:
            descriptor, temporary_name = tempfile.mkstemp(prefix=".artifact-", dir=destination.parent)
            temporary = Path(temporary_name)
            try:
                with os.fdopen(descriptor, "wb") as output, source.open("rb") as input_stream:
                    shutil.copyfileobj(input_stream, output)
                    output.flush()
                    os.fsync(output.fileno())
                if sha256_file(temporary) != checksum:
                    raise StorageError("artifact changed during copy")
                try:
                    # Atomic exclusive creation: never replace an existing original.
                    os.link(temporary, destination)
                except FileExistsError:
                    if sha256_file(destination) != checksum:
                        raise StorageError("concurrent artifact collision") from None
            finally:
                temporary.unlink(missing_ok=True)
        return {
            "storage": "local", "key": key, "path": str(destination),
            "sha256": checksum, "size_bytes": destination.stat().st_size,
        }

    def verify(self, artifact: dict[str, Any]) -> bool:
        try:
            path = self.path_for(artifact["key"])
            return (
                artifact.get("storage") == "local"
                and Path(artifact["path"]).resolve() == path
                and path.is_file()
                and path.stat().st_size == artifact["size_bytes"]
                and sha256_file(path) == artifact["sha256"]
            )
        except (KeyError, OSError, StorageError, TypeError, ValueError):
            return False

    def rebind(self, artifact: dict[str, Any]) -> dict[str, Any]:
        """Locate a restored backup by immutable key under this storage root.

        No copy, network request or regeneration occurs. Call this explicitly
        after restoring the ledger and media onto a new cloud machine/mount.
        """
        restored = {**artifact, "path": str(self.path_for(artifact["key"]))}
        if not self.verify(restored):
            raise StorageError("restored artifact is missing or checksum differs; rebinding refused")
        return restored
