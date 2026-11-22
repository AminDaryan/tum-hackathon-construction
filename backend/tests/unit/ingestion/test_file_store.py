"""Write-once, content-addressed storage of original uploads."""

from __future__ import annotations

import hashlib
import inspect
import itertools
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.core.errors import FileTooLargeError, InvalidInputError, NotFoundError
from app.storage import file_store
from app.storage.file_store import LocalFileStore, SpooledUpload

CONTENT = b"Position;Menge\n01.001;12,5\n"
SHA = hashlib.sha256(CONTENT).hexdigest()


@pytest.fixture
def store(tmp_path: Path) -> LocalFileStore:
    return LocalFileStore(tmp_path / "store")  # not created yet: directories appear on first use


def _chunks(data: bytes, size: int = 7) -> Iterator[bytes]:
    for start in range(0, len(data), size):
        yield data[start : start + size]


def _files(directory: Path) -> list[Path]:
    return sorted(path for path in directory.rglob("*") if path.is_file())


class TestSpool:
    def test_streams_hashes_and_measures(self, store: LocalFileStore) -> None:
        spooled = store.spool(_chunks(CONTENT), max_bytes=len(CONTENT))
        assert (spooled.sha256, spooled.size_bytes) == (SHA, len(CONTENT))
        assert spooled.path.parent == store.root / "tmp"
        assert spooled.path.suffix == ".part"
        assert spooled.path.read_bytes() == CONTENT

    def test_spools_get_distinct_files(self, store: LocalFileStore) -> None:
        first = store.spool([CONTENT], max_bytes=100)
        second = store.spool([CONTENT], max_bytes=100)
        assert first.path != second.path
        assert len(_files(store.root / "tmp")) == 2

    def test_empty_upload(self, store: LocalFileStore) -> None:
        spooled = store.spool([], max_bytes=10)
        assert (spooled.sha256, spooled.size_bytes) == (hashlib.sha256().hexdigest(), 0)

    def test_too_large_leaves_no_file(self, store: LocalFileStore) -> None:
        with pytest.raises(FileTooLargeError) as excinfo:
            store.spool(_chunks(CONTENT), max_bytes=len(CONTENT) - 1)
        assert excinfo.value.code == "file_too_large"
        assert excinfo.value.details == {"max_bytes": len(CONTENT) - 1}
        assert str(store.root) not in excinfo.value.message
        assert _files(store.root) == []

    def test_limit_is_enforced_while_streaming(self, store: LocalFileStore) -> None:
        endless = itertools.repeat(b"x" * 1024)  # a client that never stops sending
        with pytest.raises(FileTooLargeError):
            store.spool(endless, max_bytes=10 * 1024)
        assert _files(store.root) == []

    def test_failing_stream_leaves_no_file(self, store: LocalFileStore) -> None:
        def disconnecting() -> Iterator[bytes]:
            yield b"first chunk"
            raise ConnectionResetError("client went away")

        with pytest.raises(ConnectionResetError):
            store.spool(disconnecting(), max_bytes=1000)
        assert _files(store.root) == []


class TestCommit:
    def test_moves_to_content_addressed_read_only_original(self, store: LocalFileStore) -> None:
        spooled = store.spool(_chunks(CONTENT), max_bytes=1000)
        stored = store.commit(spooled, media_type="text/csv")
        target = store.root / "originals" / SHA[:2] / SHA
        assert stored.model_dump() == {
            "storage_key": SHA,
            "sha256": SHA,
            "size_bytes": len(CONTENT),
            "media_type": "text/csv",
        }
        assert target.read_bytes() == CONTENT
        assert stat.S_IMODE(target.stat().st_mode) & 0o222 == 0  # no write permission
        assert not spooled.path.exists()
        assert _files(store.root / "tmp") == []

    def test_same_bytes_twice_are_stored_once(self, store: LocalFileStore) -> None:
        first = store.commit(store.spool([CONTENT], max_bytes=1000), media_type="text/csv")
        target = store.path_for(first.storage_key)
        before = target.stat()
        second_spool = store.spool([CONTENT], max_bytes=1000)
        second = store.commit(second_spool, media_type="text/csv")
        assert second == first
        after = target.stat()
        assert (after.st_ino, after.st_mtime_ns) == (before.st_ino, before.st_mtime_ns)
        assert not second_spool.path.exists()
        assert _files(store.root / "originals") == [target]

    def test_different_bytes_are_stored_separately(self, store: LocalFileStore) -> None:
        keys = {
            store.commit(store.spool([data], max_bytes=1000), media_type="text/csv").storage_key
            for data in (b"a", b"b")
        }
        assert len(keys) == 2
        assert len(_files(store.root / "originals")) == 2

    def test_concurrent_commit_of_the_same_bytes(
        self, store: LocalFileStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spooled = store.spool([CONTENT], max_bytes=1000)
        target = store.root / "originals" / SHA[:2] / SHA

        def replace_after_another_commit(source: Path, destination: Path) -> None:
            Path(destination).write_bytes(CONTENT)  # the other request won the race
            raise PermissionError("target exists")  # what Windows reports in this case

        monkeypatch.setattr(file_store.os, "replace", replace_after_another_commit)
        stored = store.commit(spooled, media_type="text/csv")
        assert stored.storage_key == SHA
        assert target.read_bytes() == CONTENT
        assert not spooled.path.exists()

    def test_other_move_failures_propagate(
        self, store: LocalFileStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spooled = store.spool([CONTENT], max_bytes=1000)

        def failing_replace(source: Path, destination: Path) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(file_store.os, "replace", failing_replace)
        with pytest.raises(OSError, match="disk full"):
            store.commit(spooled, media_type="text/csv")
        assert spooled.path.exists()  # the caller still owns the spool and discards it

    def test_refuses_a_file_it_did_not_spool(self, store: LocalFileStore, tmp_path: Path) -> None:
        foreign = tmp_path / "elsewhere.part"
        foreign.write_bytes(CONTENT)
        with pytest.raises(ValueError, match="does not belong"):
            store.commit(SpooledUpload(foreign, SHA, len(CONTENT)), media_type="text/csv")
        with pytest.raises(ValueError, match="does not belong"):
            store.discard(SpooledUpload(foreign, SHA, len(CONTENT)))
        assert foreign.read_bytes() == CONTENT

    def test_refuses_files_in_tmp_that_are_not_spools(self, store: LocalFileStore) -> None:
        spooled = store.spool([CONTENT], max_bytes=1000)
        other = spooled.path.with_suffix(".txt")
        other.write_bytes(CONTENT)
        with pytest.raises(ValueError, match="does not belong"):
            store.discard(SpooledUpload(other, SHA, len(CONTENT)))
        assert other.exists()


class TestDiscard:
    def test_removes_the_spool_and_is_repeatable(self, store: LocalFileStore) -> None:
        spooled = store.spool([CONTENT], max_bytes=1000)
        store.discard(spooled)
        store.discard(spooled)
        assert _files(store.root) == []


class TestLookup:
    @pytest.fixture
    def key(self, store: LocalFileStore) -> str:
        return store.commit(store.spool([CONTENT], max_bytes=1000), media_type="text/csv").sha256

    def test_path_for(self, store: LocalFileStore, key: str) -> None:
        assert store.path_for(key) == store.root / "originals" / key[:2] / key

    def test_open_reads_binary(self, store: LocalFileStore, key: str) -> None:
        with store.open(key) as handle:
            assert handle.read() == CONTENT

    @pytest.mark.parametrize(
        "bad_key",
        [
            "",
            "../x",
            "../../etc/passwd",
            "G" * 64,
            "g" * 64,
            SHA.upper(),
            SHA[:63],
            SHA + "0",
            SHA + "\n",
            f"{SHA[:2]}/{SHA}",
            f"{SHA[:-1]}\x00",
        ],
    )
    def test_rejects_malformed_keys(self, store: LocalFileStore, key: str, bad_key: str) -> None:
        with pytest.raises(InvalidInputError) as excinfo:
            store.path_for(bad_key)
        assert excinfo.value.code == "invalid_input"
        with pytest.raises(InvalidInputError):
            store.open(bad_key)

    def test_unknown_key(self, store: LocalFileStore, key: str) -> None:
        missing = hashlib.sha256(b"never stored").hexdigest()
        with pytest.raises(NotFoundError) as excinfo:
            store.path_for(missing)
        assert str(store.root) not in excinfo.value.message
        with pytest.raises(NotFoundError):
            store.open(missing)


class TestRelativeRoot:
    def test_spool_commit_and_lookup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        store = LocalFileStore(Path("data") / "files")
        stored = store.commit(store.spool([CONTENT], max_bytes=1000), media_type="text/csv")
        assert store.path_for(stored.storage_key).read_bytes() == CONTENT
        assert (tmp_path / "data" / "files" / "originals" / SHA[:2] / SHA).is_file()


class TestNamesNeverReachPaths:
    def test_no_store_operation_takes_a_file_name(self) -> None:
        # The display name (sanitize_filename) is metadata only: storage is keyed by SHA-256.
        for method in ("spool", "commit", "discard", "path_for", "open"):
            parameters = inspect.signature(getattr(LocalFileStore, method)).parameters
            assert not {"name", "filename", "original_filename"} & set(parameters), method

    def test_the_stored_path_depends_only_on_the_content(self, store: LocalFileStore) -> None:
        stored = store.commit(store.spool([CONTENT], max_bytes=1000), media_type="text/csv")
        path = store.path_for(stored.storage_key)
        assert path.relative_to(store.root).parts == ("originals", SHA[:2], SHA)
