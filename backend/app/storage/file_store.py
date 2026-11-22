"""Write-once, content-addressed storage for original uploads.

CONTRACT (implemented by the ingestion work package):

* Uploads are first *spooled* to ``<root>/tmp`` while their SHA-256 and size are computed. The
  size limit is enforced while streaming (never trust Content-Length); exceeding it raises
  :class:`app.core.errors.FileTooLargeError` and leaves no file behind.
* Only after the file passed format/security validation is it *committed*: moved to
  ``<root>/originals/<sha[:2]>/<sha>``, made read-only, and never modified again. Committing the
  same bytes twice is idempotent (deduplicated by hash).
* Storage keys are the 64-char lowercase hex SHA-256. ``path_for`` validates the key format
  strictly so no caller-supplied string can traverse the filesystem. User-supplied filenames
  are never used in paths.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from app.core.errors import FileTooLargeError, InvalidInputError, NotFoundError
from app.models.document import StoredFile

_STORAGE_KEY = re.compile(r"[0-9a-f]{64}")  # used with fullmatch: no trailing-newline loophole
_SPOOL_SUFFIX = ".part"
_READ_ONLY = stat.S_IREAD  # owner read-only; on Windows this sets the read-only attribute


@dataclass(frozen=True, slots=True)
class SpooledUpload:
    path: Path  # temporary file inside the store's tmp directory
    sha256: str
    size_bytes: int


class FileStore(Protocol):
    def spool(self, chunks: Iterable[bytes], *, max_bytes: int) -> SpooledUpload: ...

    def commit(self, spooled: SpooledUpload, *, media_type: str) -> StoredFile: ...

    def discard(self, spooled: SpooledUpload) -> None: ...

    def path_for(self, storage_key: str) -> Path: ...

    def open(self, storage_key: str) -> BinaryIO: ...


class LocalFileStore:
    """Filesystem implementation of :class:`FileStore` rooted at ``root``.

    Layout: ``<root>/tmp/<random>.part`` for spooled uploads and
    ``<root>/originals/<sha[:2]>/<sha>`` for committed originals. Directories are created on
    first use. Uses :mod:`pathlib` and :func:`os.replace` only, so it works on Linux and Windows.
    """

    def __init__(self, root: Path) -> None:
        self.root = root

    @property
    def _tmp_dir(self) -> Path:
        return self.root / "tmp"

    @property
    def _originals_dir(self) -> Path:
        return self.root / "originals"

    def spool(self, chunks: Iterable[bytes], *, max_bytes: int) -> SpooledUpload:
        """Stream ``chunks`` into a new temporary file, hashing as it goes.

        Raises :class:`FileTooLargeError` as soon as more than ``max_bytes`` arrive; the partial
        file is deleted, as it is on any other failure (e.g. a client disconnect).
        """
        self._tmp_dir.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(prefix="", suffix=_SPOOL_SUFFIX, dir=self._tmp_dir)
        path = Path(name)
        digest = hashlib.sha256()
        size = 0
        try:
            with open(descriptor, "wb") as handle:
                for chunk in chunks:
                    size += len(chunk)
                    if size > max_bytes:
                        raise FileTooLargeError(
                            f"The file is larger than the upload limit of {max_bytes:,} bytes.",
                            details={"max_bytes": max_bytes},
                        )
                    digest.update(chunk)
                    handle.write(chunk)
        except BaseException:
            path.unlink(missing_ok=True)
            raise
        return SpooledUpload(path=path, sha256=digest.hexdigest(), size_bytes=size)

    def commit(self, spooled: SpooledUpload, *, media_type: str) -> StoredFile:
        """Move a validated spool into content-addressed storage and make it read-only.

        If an original with the same hash already exists, the spool is discarded instead and
        the existing file is left untouched (deduplication).
        """
        self._require_own_spool(spooled)
        key = _validated_key(spooled.sha256)
        target = self._location(key)
        if target.exists():
            self.discard(spooled)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.replace(spooled.path, target)
            except OSError:
                if not target.exists():
                    raise
                self.discard(spooled)  # a concurrent commit stored the same bytes first
            else:
                os.chmod(target, _READ_ONLY)
        return StoredFile(
            storage_key=key, sha256=key, size_bytes=spooled.size_bytes, media_type=media_type
        )

    def discard(self, spooled: SpooledUpload) -> None:
        """Delete a spooled upload. Safe to call more than once."""
        self._require_own_spool(spooled)
        spooled.path.unlink(missing_ok=True)

    def path_for(self, storage_key: str) -> Path:
        """Path of a committed original.

        Raises :class:`InvalidInputError` unless ``storage_key`` is a 64-character lowercase hex
        SHA-256 (so no string can reach outside the store) and :class:`NotFoundError` when no
        original with that key exists.
        """
        path = self._location(_validated_key(storage_key))
        if not path.is_file():
            raise NotFoundError("The stored original file does not exist.")
        return path

    def open(self, storage_key: str) -> BinaryIO:
        """Open a committed original for binary reading; the caller closes the handle."""
        return self.path_for(storage_key).open("rb")

    def _location(self, key: str) -> Path:
        return self._originals_dir / key[:2] / key

    def _require_own_spool(self, spooled: SpooledUpload) -> None:
        """Refuse paths that this store did not spool, so commit/discard can never move or
        delete an arbitrary file. A mismatch is a programming error, not user input."""
        path = spooled.path
        in_tmp = path.parent.resolve() == self._tmp_dir.resolve()
        if not (in_tmp and path.name.endswith(_SPOOL_SUFFIX)):
            raise ValueError("The spooled upload does not belong to this file store.")


def _validated_key(storage_key: str) -> str:
    if not isinstance(storage_key, str) or _STORAGE_KEY.fullmatch(storage_key) is None:
        raise InvalidInputError("Invalid storage key.")
    return storage_key
