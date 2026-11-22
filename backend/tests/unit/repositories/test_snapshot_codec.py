"""The dataset snapshot codec: lossless, deterministic, versioned, and loud about bad input."""

from __future__ import annotations

import json
import zlib

import pytest

from app.models.dataset import Dataset
from app.repositories.errors import (
    CorruptSnapshotError,
    IncompatibleRecordError,
    PayloadEncodingError,
    UnknownSnapshotCodecError,
)
from app.repositories.snapshot_codec import (
    EncodedSnapshot,
    decode_dataset,
    encode_dataset,
    supported_codecs,
)


def test_round_trip_is_lossless(dataset: Dataset) -> None:
    snapshot = encode_dataset(dataset)
    assert snapshot.codec == "json+zlib/1"
    assert snapshot.codec in supported_codecs()
    assert decode_dataset(snapshot) == dataset


def test_snapshot_is_compressed_json_of_the_json_mode_dump(dataset: Dataset) -> None:
    snapshot = encode_dataset(dataset)
    text = zlib.decompress(snapshot.data).decode("utf-8")
    assert json.loads(text) == dataset.model_dump(mode="json")
    assert len(snapshot.data) < len(text.encode("utf-8"))
    assert "m³" in text  # UTF-8, not \\u escapes
    assert '"10.500"' in text  # decimals as exact strings


def test_encoding_is_deterministic(dataset: Dataset) -> None:
    assert encode_dataset(dataset).data == encode_dataset(dataset.model_copy()).data


def test_unknown_codec_is_refused(dataset: Dataset) -> None:
    snapshot = EncodedSnapshot(codec="json+zlib/2", data=encode_dataset(dataset).data)
    with pytest.raises(UnknownSnapshotCodecError, match="json\\+zlib/2"):
        decode_dataset(snapshot)


@pytest.mark.parametrize(
    "data",
    [b"definitely not zlib", zlib.compress(b"{not json"), zlib.compress(b"\xff\xfe")],
    ids=["not-zlib", "not-json", "not-utf8"],
)
def test_damaged_bytes_are_refused(data: bytes) -> None:
    with pytest.raises(CorruptSnapshotError):
        decode_dataset(EncodedSnapshot(codec="json+zlib/1", data=data))


def test_json_of_another_shape_is_reported_as_incompatible() -> None:
    snapshot = EncodedSnapshot(codec="json+zlib/1", data=zlib.compress(b'{"dataset_id": "x"}'))
    with pytest.raises(IncompatibleRecordError, match="Dataset model"):
        decode_dataset(snapshot)


def test_non_finite_floats_are_refused_when_encoding(dataset: Dataset) -> None:
    extraction = dataset.extraction.evolve(details={"score": float("inf")})
    with pytest.raises(PayloadEncodingError, match="ds_000001"):
        encode_dataset(dataset.evolve(extraction=extraction))
