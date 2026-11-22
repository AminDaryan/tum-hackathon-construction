"""Versioned encoding of immutable dataset revisions into compact snapshots.

A dataset revision is never updated, so it is stored as one blob plus the tag of the codec
that wrote it. Decoding dispatches on that tag and refuses tags it does not know, so a
snapshot written by a newer (or foreign) build is reported, never misread.

``json+zlib/1`` is zlib-compressed UTF-8 JSON of ``Dataset.model_dump(mode="json")``: compact
separators, no NaN/Infinity, decimals as exact strings. Keys keep the model's field order and
the mappings' insertion order (they are not sorted), so the encoding is deterministic for a
given dataset and mappings such as ``Row.cells`` come back in column order. Encoding and
decoding share the payload rules of :mod:`app.repositories.records`.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass
from typing import Protocol

from app.models.dataset import Dataset
from app.repositories.errors import CorruptSnapshotError, UnknownSnapshotCodecError
from app.repositories.records import describe, encode_json, json_dump, load_model

DEFAULT_SNAPSHOT_NAME = "dataset snapshot"  # how errors name a snapshot of unknown identity


@dataclass(frozen=True, slots=True)
class EncodedSnapshot:
    codec: str  # codec tag, e.g. "json+zlib/1"
    data: bytes


class SnapshotCodec(Protocol):
    tag: str

    def encode(self, dataset: Dataset) -> bytes: ...

    def decode(self, data: bytes, *, what: str) -> Dataset:
        """``what`` names the snapshot in errors."""
        ...


class JsonZlibCodec:
    """``json+zlib/1``: zlib-compressed JSON of the canonical dataset."""

    tag = "json+zlib/1"

    def __init__(self, *, level: int = 6) -> None:
        self._level = level

    def encode(self, dataset: Dataset) -> bytes:
        text = encode_json(json_dump(dataset), what=describe(dataset))
        return zlib.compress(text.encode("utf-8"), self._level)

    def decode(self, data: bytes, *, what: str) -> Dataset:
        try:
            document = json.loads(zlib.decompress(data))
        except (zlib.error, ValueError) as exc:  # JSON and UTF-8 errors are ValueErrors
            raise CorruptSnapshotError(f"The {what} is damaged: {exc}") from exc
        return load_model(Dataset, document, what=what)


CURRENT_CODEC: SnapshotCodec = JsonZlibCodec()
_CODECS: dict[str, SnapshotCodec] = {CURRENT_CODEC.tag: CURRENT_CODEC}


def supported_codecs() -> frozenset[str]:
    return frozenset(_CODECS)


def encode_dataset(dataset: Dataset) -> EncodedSnapshot:
    """Encode with the current codec."""
    return EncodedSnapshot(codec=CURRENT_CODEC.tag, data=CURRENT_CODEC.encode(dataset))


def decode_dataset(snapshot: EncodedSnapshot, *, what: str = DEFAULT_SNAPSHOT_NAME) -> Dataset:
    """Decode with the codec named by the snapshot; unknown codecs are refused. ``what`` names
    the snapshot in errors."""
    codec = _CODECS.get(snapshot.codec)
    if codec is None:
        raise UnknownSnapshotCodecError(
            f"The {what} uses codec {snapshot.codec!r}, which this build does not support "
            f"(supported: {', '.join(sorted(_CODECS))}).",
            details={"codec": snapshot.codec, "supported": sorted(_CODECS)},
        )
    return codec.decode(snapshot.data, what=what)
