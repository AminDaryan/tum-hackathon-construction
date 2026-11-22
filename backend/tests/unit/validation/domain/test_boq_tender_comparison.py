"""domain.boq_tender_comparison: a priced bill against the tender it answers."""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

import pytest

from app.models.dataset import Dataset, RowKind
from app.models.finding_category import FindingCategory
from app.models.issue import EvidenceClass, Severity
from app.models.profile import DomainProfile
from app.models.tender import Tender
from app.validation.contracts.detector import DetectorResult
from app.validation.domain.boq.tender_comparison import (
    ANONYMISED_NUMBERS,
    POSITIONS_COMPARED,
    REPEATED_NUMBERS,
    RULE_ADDED,
    RULE_MISSING,
    RULE_QUANTITY,
    RULE_TEXT,
    RULE_UNIT,
    TEXTS_CUT_OFF,
    TEXTS_NOT_IN_BID,
    TenderComparisonDetector,
)
from tests.support.builders import DatasetBuilder, make_context
from tests.unit.validation.deterministic.references_fixtures import (
    assert_well_formed,
    by_rule,
    resolve,
    run,
)

DETECTOR = TenderComparisonDetector
COLUMNS: list[tuple[str | None, str | None]] = [
    ("OZ", "item_code"),
    ("Kurztext", "description"),
    ("Menge", "quantity"),
    ("Einheit", "unit"),
    ("EP", "unit_price"),
    ("GP", "line_total"),
    ("Währung", "currency"),
    ("Langtext", "long_description"),
]
SECTION = ["01", "Erdarbeiten", None, None, None, None, None, None]


def bill(
    profile: DomainProfile,
    rows: Sequence[Sequence[Any]],
    *,
    priced: bool = True,
    document_id: str = "doc_bid",
) -> Dataset:
    """Item rows (OZ, short text, quantity, unit, unit price, long text) under section 01; a
    tender (``priced=False``) leaves the prices empty."""
    builder = DatasetBuilder(profile, document_id=document_id, dataset_id=f"ds_{document_id}")
    table = builder.table("LV", COLUMNS)
    table.row(SECTION, kind=RowKind.SECTION)
    for code, short, quantity, unit, price, long in rows:
        total = str(Decimal(quantity) * Decimal(price)) if priced and quantity and price else None
        table.row(
            [code, short, quantity, unit, price if priced else None, total, "EUR", long],
        )
    return builder.build()


def compare(
    profile: DomainProfile,
    bid_rows: Sequence[Sequence[Any]],
    tender_rows: Sequence[Sequence[Any]],
) -> DetectorResult:
    bid = bill(profile, bid_rows)
    tender = Tender("Ausschreibung.X83", bill(profile, tender_rows, priced=False, document_id="t"))
    context = dataclasses.replace(make_context(bid, profile), tender=tender)
    return run(DETECTOR, bid, profile, context=context)


ROW = ("01.0010", "Rohr DN 250 verlegen", "25", "m", "100.00", "Rohr DN 250, PN 16, verlegen.")


def test_a_changed_quantity_is_found_with_the_money_at_stake(boq_profile: DomainProfile) -> None:
    found = compare(boq_profile, [ROW], [("1.10", ROW[1], "20", "m", None, ROW[5])])
    [issue] = found.issues
    assert issue.rule_id == RULE_QUANTITY
    assert issue.title == "Bid prices 25 m of 01.0010, the tender asks for 20 m"
    assert (issue.severity, issue.evidence_class) == (
        Severity.HIGH,
        EvidenceClass.CONFIRMED_RULE_VIOLATION,
    )
    assert issue.finding_category is FindingCategory.INCONSISTENCY
    assert (issue.observed_value, issue.expected_value) == ("25", "20")
    assert issue.estimated_financial_impact is not None
    assert issue.estimated_financial_impact.amount == Decimal("500.00")  # (25 − 20) × 100
    assert "Ausschreibung.X83" in issue.explanation
    assert found.coverage[POSITIONS_COMPARED] == 1
    assert_well_formed(found.issues)


def test_positions_added_to_the_bid_or_left_out_of_it_are_found(
    boq_profile: DomainProfile,
) -> None:
    added = ("01.0020", "Zulage Handaushub", "2", "m3", "40.00", "")
    left_out = ("01.0030", "Verfüllen", "10", "m3", None, "")
    found = compare(boq_profile, [ROW, added], [ROW, left_out])
    [extra] = by_rule(found.issues, RULE_ADDED)
    [missing] = by_rule(found.issues, RULE_MISSING)
    assert extra.title == "Position 01.0020 is not in the tender"
    assert extra.estimated_financial_impact is not None
    assert extra.estimated_financial_impact.amount == Decimal("80.00")  # its line total
    assert extra.finding_category is FindingCategory.INCONSISTENCY
    assert missing.title == "Tender position 01.0030 is missing from the bid"
    assert missing.severity is Severity.HIGH
    assert missing.finding_category is FindingCategory.OMISSION
    assert "Section 01 of the bid has no position 01.0030." in missing.explanation
    assert missing.row_id is not None  # on the section the number belongs to
    assert_well_formed(found.issues)


def test_a_changed_word_or_number_in_a_text_is_found(boq_profile: DomainProfile) -> None:
    bid = (*ROW[:5], "Rohr DN 250, PN 6, verlegen, Schrauben aus verzinktem PER89.")
    tender = (*ROW[:5], "Rohr DN 250, PN 16, verlegen, Schrauben aus nichtrostendem PER89.")
    [issue] = compare(boq_profile, [bid], [tender]).issues
    assert issue.rule_id == RULE_TEXT
    assert issue.title == "The long text of 01.0010 differs from the tender"
    assert "'16' became '6'" in issue.explanation
    assert "'nichtrostendem' became 'verzinktem'" in issue.explanation
    assert (issue.expected_value, issue.observed_value) == ("16", "6")
    assert issue.severity is Severity.MEDIUM


@pytest.mark.parametrize(
    ("tender_text", "bid_text"),
    [
        ("Rohr DN 250 verlegen", "rohr  DN 250\nverlegen"),  # case and spacing
        ("Lieferantund Hochleistungs- Pumpe", "Lieferant und HochleistungsPumpe"),  # line joins
        ("Doku in [PERSON_097] liefern", "Doku in PERSON_097 liefern"),  # tokens of two widths
        ("Schrauben aus Stahl", "Schrauben aus PER89"),  # a word anonymised in one file
        ("[PERSON_097] , in Ordnern", "Bestands-Dokumentation in PERSON_097, in Ordnern"),
        ("Fabrikat: ..........", "Fabrikat: Muster AG"),  # the bidder filled in a blank
        (
            "gemäß Einzelbeschreibung, Nr 4 Anschluss",
            "gemäß [TA11 Einzelbeschreibung, [ Nr 4 ] ] Anschluss",
        ),
    ],
)
def test_differences_of_writing_or_format_are_not_changes(
    boq_profile: DomainProfile, tender_text: str, bid_text: str
) -> None:
    found = compare(boq_profile, [(*ROW[:5], bid_text)], [(*ROW[:5], tender_text)])
    assert found.issues == []


def test_a_short_text_cut_at_the_gaeb_90_width_is_not_a_change(
    boq_profile: DomainProfile,
) -> None:
    full = "Bordstein Beton abbrechen TB10/25 24kN/m3 Geräteeinsatz mgl. laden transp. LKW AN"
    cut = full[:70]
    repeat = "Wie Position 1. 2. 7., jedoch " + full[:70]
    found = compare(
        boq_profile,
        [("01.0010", cut, "25", "m", "100.00", ""), ("01.0020", repeat, "5", "m", "9.00", "")],
        [("01.0010", full, "25", "m", None, ""), ("01.0020", full, "5", "m", None, "")],
    )
    assert found.issues == []
    assert found.coverage[TEXTS_CUT_OFF] == 2


def test_a_shortened_text_that_is_not_cut_at_the_width_is_a_change(
    boq_profile: DomainProfile,
) -> None:
    tender = "Rohr DN 250 verlegen, einschließlich Formstücke und Dichtungen"
    bid = "Rohr DN 250 verlegen, einschließlich Formstücke"
    [issue] = compare(boq_profile, [(*ROW[:5], bid)], [(*ROW[:5], tender)]).issues
    assert issue.rule_id == RULE_TEXT
    assert "'und Dichtungen' left out" in issue.explanation


def test_the_row_s_own_quantity_and_unit_after_a_short_text_are_not_a_change(
    boq_profile: DomainProfile,
) -> None:
    # A printed tender read from a PDF can run the quantity and unit into the short text.
    found = compare(
        boq_profile,
        [
            ("01.0010", "Baustelle einrichten", "1", "psch", "1800.00", ""),
            ("01.0020", "Beton liefern", "1209.6", "m3", "175.00", ""),
        ],
        [
            ("01.0010", "Baustelle einrichten 1 psch", "1", "psch", None, ""),
            ("01.0020", "Beton liefern 1.209,6 m3", "1209.6", "m3", None, ""),
        ],
    )
    assert [i.title for i in found.issues] == [], [i.explanation for i in found.issues]
    # Another number than the row's quantity is part of the text.
    [issue] = compare(
        boq_profile,
        [("01.0010", "Rohr verlegen", "25", "m", "100.00", "")],
        [("01.0010", "Rohr verlegen 30 m", "25", "m", None, "")],
    ).issues
    assert issue.rule_id == RULE_TEXT


def test_a_bid_without_texts_is_compared_by_its_numbers_only(
    boq_profile: DomainProfile,
) -> None:
    found = compare(boq_profile, [("01.0010", "", "25", "", "100.00", "")], [(*ROW[:5], "x")])
    assert found.issues == []  # no text and no unit in the bid, the same quantity
    assert found.coverage[TEXTS_NOT_IN_BID] == 1


def test_a_changed_unit_is_found_and_spellings_of_one_unit_are_not(
    boq_profile: DomainProfile,
) -> None:
    found = compare(
        boq_profile,
        [
            ("01.0010", "Pflaster", "25", "m", "10.00", ""),
            ("01.0020", "Rasen", "5", "m²", "2.00", ""),
        ],
        [("01.0010", "Pflaster", "25", "m2", None, ""), ("01.0020", "Rasen", "5", "m2", None, "")],
    )
    [issue] = found.issues
    assert issue.rule_id == RULE_UNIT
    assert issue.title == "Bid measures 01.0010 in m, the tender in m2"
    assert (issue.observed_value, issue.expected_value) == ("m", "m2")


def test_repeated_and_anonymised_item_numbers_are_left_out(boq_profile: DomainProfile) -> None:
    repeated = ("01.0040", "Schacht", "1", "St", "500.00", "")
    found = compare(
        boq_profile,
        [ROW, repeated, repeated, ("TEL00009", "Kupplung", "1", "St", "5.00", "")],
        [ROW, repeated],
    )
    assert found.issues == []
    assert (found.coverage[REPEATED_NUMBERS], found.coverage[ANONYMISED_NUMBERS]) == (1, 1)


def test_without_a_tender_the_check_does_not_apply(boq_profile: DomainProfile) -> None:
    bid = bill(boq_profile, [ROW])
    config = resolve(DETECTOR, boq_profile)
    applicability = DETECTOR().applicability(make_context(bid, boq_profile), config)
    assert not applicability.applicable
    assert applicability.reasons == (
        "No tender for this bill in its project: a bill with prices is compared with an "
        "unpriced bill whose positions match it.",
    )
