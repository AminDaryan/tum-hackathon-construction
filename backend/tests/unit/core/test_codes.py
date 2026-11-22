"""Canonical form of hierarchical codes (shared by normalization and the detectors)."""

from __future__ import annotations

import pytest

from app.core.codes import (
    MAX_CODE_SEGMENT_CHARS,
    code_segments,
    is_strict_prefix,
    normalize_code,
    same_code,
)
from app.validation.deterministic import _support


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("01.02.0030", "01.02.0030"),
        (" 01.02.0030. ", "01.02.0030"),
        ("01 . 02", "01.02"),
        ("A.1.3", "a.1.3"),
        ("Ａ１", "a1"),  # full-width characters fold under NFKC
        ("", None),
        ("   ", None),
        (".", None),
        (None, None),
        ("1" * 201, None),
    ],
)
def test_normalize_code(text, key) -> None:
    assert normalize_code(text) == key


@pytest.mark.parametrize(
    ("text", "segments"),
    [
        ("01.02.0030", ("1", "2", "30")),
        ("1.2.30", ("1", "2", "30")),
        ("01/02", ("1", "2")),
        ("00.000", ("0", "0")),
        ("A.01.b", ("a", "1", "b")),
        ("01..02", ("1", "2")),
        ("١٢.3", ("١٢", "3")),  # Arabic-Indic digits stay text: never converted silently
        ("1" * MAX_CODE_SEGMENT_CHARS, ("1" * MAX_CODE_SEGMENT_CHARS,)),
        ("2" + "1" * MAX_CODE_SEGMENT_CHARS, None),
        (None, None),
    ],
)
def test_code_segments(text, segments) -> None:
    assert code_segments(text) == segments


def test_strict_prefix_and_equality() -> None:
    assert is_strict_prefix(("1",), ("1", "2"))
    assert not is_strict_prefix(("1", "2"), ("1", "2"))
    assert not is_strict_prefix(("1", "3"), ("1", "2", "4"))
    assert not is_strict_prefix(None, ("1",))
    assert same_code("01.02.0030.", "1.2.30")
    assert not same_code("01.02", "01.02.1")
    assert not same_code(None, None)


def test_detector_support_reexports_the_core_helpers() -> None:
    assert _support.code_segments is code_segments
    assert _support.normalize_code is normalize_code
    assert _support.is_strict_prefix is is_strict_prefix
