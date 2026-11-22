"""Profile data that used to be constants in code: yes/no words, the markers that count as
zero in totals, and the normalization thresholds (defaults equal the former constants)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.errors import ProfileError
from app.models.dataset import HeaderMethod, MappingMethod
from app.models.profile import (
    BooleanWords,
    DomainProfile,
    NormalizationThresholds,
    SemanticField,
)
from app.models.values import BooleanValue, DataType, ParseStatus, ValueMarker
from app.normalization.mapping import HeaderMatcher
from app.profiles.currency import CurrencyResolver
from app.profiles.loader import load_profile
from tests.unit.normalization.raw_builders import by_source_row, codes, normalize, sheet, workbook

FORMER_TRUE = {"true", "yes", "ja", "wahr", "y", "j", "x"}
FORMER_FALSE = {"false", "no", "nein", "falsch", "n"}
FORMER_ZERO = [
    ValueMarker.NIL,
    ValueMarker.INCLUDED_ELSEWHERE,
    ValueMarker.NOT_APPLICABLE,
    ValueMarker.BY_OTHERS,
]


def test_defaults_are_the_former_constants(
    boq_profile: DomainProfile, generic_profile: DomainProfile
) -> None:
    bare = DomainProfile(profile_id="bare", name="Bare", version="1.0.0")
    assert bare.zero_contribution_markers == FORMER_ZERO
    assert bare.normalization == NormalizationThresholds(
        type_mismatch_share=0.5,
        type_mismatch_min_values=3,
        min_contains_chars=4,
        min_fuzzy_chars=4,
        structural_lookahead_rows=3,
        data_lookahead_rows=20,
    )
    assert bare.boolean_words == BooleanWords()  # words come from the profile files
    for shipped in (boq_profile, generic_profile):
        assert set(shipped.boolean_words.true_words) == FORMER_TRUE
        assert set(shipped.boolean_words.false_words) == FORMER_FALSE
        assert shipped.normalization == bare.normalization
    # B2.1 adds the boq profile's not_offered marker: a position not offered adds nothing.
    assert boq_profile.zero_contribution_markers == [*FORMER_ZERO, ValueMarker.NOT_OFFERED]
    assert generic_profile.zero_contribution_markers == FORMER_ZERO


@pytest.mark.parametrize(
    "change",
    [
        {"zero_contribution_markers": ["nil", "nil"]},
        {"zero_contribution_markers": ["nothing"]},
        {"boolean_words": {"true_words": ["ja"], "false_words": [" JA "]}},
        {"boolean_words": {"true_words": [" "]}},
        {"normalization": {"type_mismatch_share": 0}},
        {"normalization": {"min_contains_chars": 0}},
        {"normalization": {"unknown": 1}},
    ],
)
def test_invalid_settings_are_rejected(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        DomainProfile.model_validate(
            {"profile_id": "bad", "name": "Bad", "version": "1.0.0", **change}
        )


def test_unquoted_yaml_booleans_are_not_words(tmp_path: Path) -> None:
    path = tmp_path / "words.yaml"
    path.write_text(
        "profile_id: words\nname: Words\nversion: 1.0.0\n"
        "boolean_words:\n  true_words: [yes]\n",  # YAML reads an unquoted yes as true
        encoding="utf-8",
    )
    with pytest.raises(ProfileError, match=r"words\.yaml"):
        load_profile(path)


def _with_approval_field(profile: DomainProfile, **changes: object) -> DomainProfile:
    approved = SemanticField(
        field_id="approved",
        label="Approved",
        data_type=DataType.BOOLEAN,
        header_synonyms=["freigegeben"],
    )
    return profile.evolve(fields=[*profile.fields, approved], **changes)


def _approvals(profile: DomainProfile) -> dict[str, tuple[ParseStatus, object]]:
    rows = [["OZ", "Kurztext", "Menge", "EP", "Freigegeben"]]
    rows += [[str(i), "Text", "1", "2", word] for i, word in enumerate(["ja", "NEIN", "oui"], 1)]
    table = normalize(workbook(sheet(rows)), profile).tables[0]
    column = table.column_for_field("approved")
    assert column is not None
    found = {}
    for number, word in ((2, "ja"), (3, "NEIN"), (4, "oui")):
        cell = by_source_row(table)[number].cells[column.column_id]
        found[word] = (cell.parse_status, cell.normalized_value)
    return found


def test_yes_no_words_come_from_the_profile(boq_profile: DomainProfile) -> None:
    shipped = _approvals(_with_approval_field(boq_profile))
    assert shipped["ja"] == (ParseStatus.EXACT, BooleanValue(value=True))
    assert shipped["NEIN"] == (ParseStatus.EXACT, BooleanValue(value=False))
    assert shipped["oui"][0] is ParseStatus.FAILED
    french = BooleanWords(true_words=["oui"], false_words=["non"])
    custom = _approvals(_with_approval_field(boq_profile, boolean_words=french))
    assert custom["oui"] == (ParseStatus.EXACT, BooleanValue(value=True))
    assert custom["ja"][0] is ParseStatus.FAILED  # no built-in words behind the profile


def _thresholds(profile: DomainProfile, **values: object) -> DomainProfile:
    return profile.evolve(normalization=profile.normalization.evolve(**values))


def test_type_mismatch_thresholds(boq_profile: DomainProfile) -> None:
    rows = [
        ["OZ", "Kurztext", "Menge", "EP"],
        ["1", "a", "viel", "2"],
        ["2", "b", "wenig", "3"],
        ["3", "c", "7", "4"],
    ]

    def mapped(profile: DomainProfile) -> bool:
        dataset = normalize(workbook(sheet(rows)), profile)
        quantity = dataset.tables[0].column_for_field("quantity") is not None
        assert quantity is ("mapping_rejected_type_mismatch" not in codes(dataset))
        return quantity

    assert not mapped(boq_profile)  # 1 number of 3 values is below half
    assert mapped(_thresholds(boq_profile, type_mismatch_share=0.3))
    assert mapped(_thresholds(boq_profile, type_mismatch_min_values=4))


def test_header_matching_thresholds(boq_profile: DomainProfile) -> None:
    def methods(profile: DomainProfile, header: str) -> set[MappingMethod]:
        matcher = HeaderMatcher(profile, CurrencyResolver(), 0.85)
        return {match.method for match in matcher.matches(header)}

    assert MappingMethod.HEADER_CONTAINS in methods(boq_profile, "Menge gesamt")
    strict = _thresholds(boq_profile, min_contains_chars=6)
    assert MappingMethod.HEADER_CONTAINS not in methods(strict, "Menge gesamt")
    assert MappingMethod.HEADER_FUZZY in methods(boq_profile, "Mnge")
    assert MappingMethod.HEADER_FUZZY not in methods(
        _thresholds(boq_profile, min_fuzzy_chars=5), "Mnge"
    )


def test_structural_header_lookahead(generic_profile: DomainProfile) -> None:
    rows = [["Name", "Amount"], ["x", "y"], ["z", "w"], ["q", "r"], ["a", "5"]]

    def header(profile: DomainProfile) -> tuple[HeaderMethod, list[int]]:
        table = normalize(workbook(sheet(rows)), profile).tables[0]
        return table.header.method, table.header.header_row_numbers

    assert header(generic_profile) == (HeaderMethod.STRUCTURAL, [2])  # a number within 3 rows
    wider = _thresholds(generic_profile, structural_lookahead_rows=4)
    assert header(wider) == (HeaderMethod.STRUCTURAL, [1])
