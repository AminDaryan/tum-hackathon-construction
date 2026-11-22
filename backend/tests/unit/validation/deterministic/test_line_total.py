"""deterministic.line_total: quantity × unit price (× unit factor) against the line total."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from app.core.clock import FixedClock
from app.core.config import IngestionLimits
from app.core.errors import DetectorConfigError
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.adapter import Gaeb90Adapter, GaebAdapter
from app.models.dataset import Dataset, ExtractionWarning
from app.models.document import DocumentFormat
from app.models.issue import EvidenceClass, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.models.values import ValueMarker
from app.normalization.builder import build_dataset
from app.validation.deterministic.line_total import (
    PREVAILS_STATED_AMOUNT,
    PREVAILS_UNIT_PRICE,
    PREVAILS_UNLESS_LUMP_SUM,
    RULE_LINE_TOTAL,
    LineTotalConfig,
    LineTotalDetector,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import (
    DatasetBuilder,
    ambiguous_cell,
    marker_cell,
    number_cell,
    unit_cell,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    boq_dataset,
    resolve,
    run,
)

DETECTOR = LineTotalDetector


def _item(quantity: Any, price: Any, total: Any, unit: Any = None, code: str = "01") -> list[Any]:
    return [code, "Aushub", quantity, unit or unit_cell("m3", "m3"), price, total]


def _issues(profile: DomainProfile, rows: list[list[Any]], overrides: Any = None) -> list[Any]:
    return run(DETECTOR, boq_dataset(profile, rows), profile, overrides).issues


def test_consistent_rows(boq_profile: DomainProfile) -> None:
    rows = [_item("12", "40.00", "480.00"), _item("1250.50", "4.20", "5252.10", code="02")]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert result.issues == []
    assert result.coverage["rows_checked"] == 2 and result.coverage["rows_consistent"] == 2


def test_a_mismatch_is_a_confirmed_violation(boq_profile: DomainProfile) -> None:
    [issue] = _issues(boq_profile, [_item("12", "40.00", "500.00")])
    assert issue.rule_id == RULE_LINE_TOTAL
    assert issue.issue_category is IssueCategory.ARITHMETIC
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert issue.severity is Severity.HIGH
    assert issue.title == "Line total 500.00 does not match Quantity × Unit price = 480.00"
    assert issue.observed_value == "500.00" and issue.expected_value == "480.00"
    assert len(issue.input_cells) == 2 and len(issue.affected_cells) == 1
    calculation = issue.evidence[0].calculation
    assert issue.evidence[0].kind is EvidenceKind.CALCULATION and calculation is not None
    assert calculation.operation == "product" and calculation.exact_result == Decimal("480.00")
    assert calculation.difference == Decimal("20.00")
    assert issue.estimated_financial_impact is None  # no explicit currency
    assert_well_formed([issue])


def test_financial_impact_needs_an_explicit_currency(boq_profile: DomainProfile) -> None:
    total = number_cell("500.00", currency="EUR")
    [issue] = _issues(boq_profile, [_item("12", number_cell("40.00", currency="EUR"), total)])
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.kind == "discrepancy"
    assert impact.amount == Decimal("20.00") and impact.currency == "EUR"


def test_tolerance_boundary(boq_profile: DomainProfile) -> None:
    assert _issues(boq_profile, [_item("12", "40.00", "480.01")]) == []
    assert len(_issues(boq_profile, [_item("12", "40.00", "480.02")])) == 1


def test_exact_or_rounded_conventions(boq_profile: DomainProfile) -> None:
    assert _issues(boq_profile, [_item("3", "3.333", "10.00")]) == []  # rounded
    assert _issues(boq_profile, [_item("3", "3.333", "9.999")]) == []  # exact
    strict = {"tolerance": {"absolute": "0"}}
    assert len(_issues(boq_profile, [_item("1", "2.345", "2.34")], strict)) == 1  # half up
    half_even = {**strict, "rounding": {"decimal_places": 2, "mode": "half_even"}}
    assert _issues(boq_profile, [_item("1", "2.345", "2.34")], half_even) == []


def test_percent_items(boq_profile: DomainProfile) -> None:
    percent = unit_cell("%", "pct")
    assert _issues(boq_profile, [_item("5", "100000.00", "5000.00", percent)]) == []
    [issue] = _issues(boq_profile, [_item("5", "100000.00", "50000.00", percent)])
    assert all(e.label != "Possible scaling error" for e in issue.evidence)  # factor is not 1
    written = number_cell("0.05", raw="5 %", percent=True)  # already divided by 100
    assert _issues(boq_profile, [_item(written, "100000.00", "5000.00", percent)]) == []


def test_scaling_error_note(boq_profile: DomainProfile) -> None:
    rows = [_item("12", "40.00", "4800.00")]
    [issue] = _issues(boq_profile, rows)
    [note] = [e for e in issue.evidence if e.label == "Possible scaling error"]
    assert note.data["power_of_ten"] == 1
    assert note.kind is EvidenceKind.NOTE and "context, not proof" in note.detail


def test_a_decimal_slip_is_named_in_the_title(boq_profile: DomainProfile) -> None:
    rows = [_item("12", "40.00", "4800.00")]
    [issue] = _issues(boq_profile, rows)
    assert issue.title == (
        "Line total 4800.00 is 10 times Quantity × Unit price = 480.00: a decimal slip?"
    )
    assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
    assert (issue.observed_value, issue.expected_value) == ("4800.00", "480.00")
    [small] = _issues(boq_profile, [_item("12", "40.00", "4.80")])
    assert small.title == (
        "Line total 4.80 is 1/100 of Quantity × Unit price = 480.00: a decimal slip?"
    )
    scaling = [e for e in small.evidence if e.label == "Possible scaling error"]
    assert [e.data["power_of_ten"] for e in scaling] == [-2]
    # Only the words change: the same mismatch keeps its fingerprint and evidence digest.
    [plain] = _issues(boq_profile, rows, {"detect_scaling_errors": False})
    assert plain.title == "Line total 4800.00 does not match Quantity × Unit price = 480.00"
    assert (plain.fingerprint, plain.evidence_digest) == (
        issue.fingerprint,
        issue.evidence_digest,
    )
    assert plain.severity is issue.severity
    # Not a power of ten: the usual title.
    [other] = _issues(boq_profile, [_item("12", "40.00", "500.00")])
    assert "decimal slip" not in other.title


def test_abstentions(boq_profile: DomainProfile) -> None:
    rows = [
        _item("10", "40.00", None, code="01"),  # "nur EP"
        _item(marker_cell("psch", ValueMarker.LUMP_SUM), "2500.00", "2500.00", code="02"),
        _item(ambiguous_cell("1.234"), "40.00", "49.36", code="03"),
        _item("2", "40.00", "999.00", unit_cell("100 St", "pcs"), code="04"),
        _item(
            "12",
            number_cell("40.00", currency="EUR"),
            number_cell("999.00", currency="USD"),
            code="05",
        ),
    ]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert result.issues == []
    assert result.coverage["rows_skipped_missing_inputs"] == 1
    assert result.coverage["rows_skipped_marker"] == 1
    assert result.coverage["rows_skipped_unusable_inputs"] == 1
    assert result.coverage["rows_skipped_unit_multiplier"] == 1
    assert result.coverage["rows_skipped_currency_conflict"] == 1


def test_whole_euro_columns_round_to_their_precision(boq_profile: DomainProfile) -> None:
    rows = [_item("3", "33.3", "100", code="01"), _item("2", "40", "80", code="02")]
    result = run(DETECTOR, boq_dataset(boq_profile, rows), boq_profile)
    assert result.issues == []
    assert any("at most 0 decimal places" in note for note in result.notes)
    off = run(
        DETECTOR,
        boq_dataset(boq_profile, rows),
        boq_profile,
        {"infer_precision_from_column": False},
    )
    assert len(off.issues) == 1


def test_low_confidence_inputs_downgrade_the_finding(boq_profile: DomainProfile) -> None:
    total = number_cell("500.00", confidence=0.5)
    [issue] = _issues(boq_profile, [_item("12", "40.00", total)])
    assert issue.effective_evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY


def test_config_applicability_and_registry(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)  # the boq.yaml defaults validate
    assert config.rounding.decimal_places == 2 and config.tolerance.absolute == Decimal("0.01")
    assert LineTotalConfig.plannable_parameters() == {
        "quantity_field",
        "price_field",
        "total_field",
        "unit_field",
        "discount_field",
        "severity",
    }
    for bad in ({"unknown": 1}, {"rounding": {"decimal_places": 20}}, {"tolerance": {"x": 1}}):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
    columns = [column for column in BOQ_COLUMNS if column[1] != "unit_price"]
    no_price = boq_dataset(
        boq_profile, [["01", "x", "1", unit_cell("m", "m"), "1"]], columns=columns
    )
    assert not applicability(DETECTOR, no_price, boq_profile).applicable
    assert (
        "deterministic.line_total"
        in DetectorRegistry.from_packages(["app.validation.deterministic"]).ids()
    )


def test_fingerprints_are_unique_and_stable(boq_profile: DomainProfile) -> None:
    rows = [_item("12", "40.00", "500.00", code="01"), _item("2", "5.00", "11.00", code="02")]
    first = _issues(boq_profile, rows)
    second = _issues(boq_profile, rows)
    assert len(first) == 2
    assert_unique_fingerprints(first)
    assert [i.fingerprint for i in first] == [i.fingerprint for i in second]


DISCOUNT_COLUMNS = [*BOQ_COLUMNS, ("Nachlass %", "discount_percent")]


def _discounted(profile: DomainProfile, total: Any, discount: Any, exact: bool = False) -> Any:
    # GAEB DA XML 3.3 Fachdokumentation (2023-01), 4.6.17: 73.789 × 9.77 = 720.92; -1.5 % = 710.11
    rows = [[*_item("73.789", "9.77", total), discount]]
    overrides = {"tolerance": {"absolute": "0"}} if exact else None
    return run(DETECTOR, boq_dataset(profile, rows, columns=DISCOUNT_COLUMNS), profile, overrides)


def test_item_discount_follows_the_gaeb_rounding_rule(boq_profile: DomainProfile) -> None:
    assert _discounted(boq_profile, "710.11", "1.5", exact=True).issues == []
    # Without the intermediate rounding the total would be 710.10: one cent off, which the
    # profile's 0.01 tolerance allows, so the exact rule is shown with no tolerance.
    [exact] = _discounted(boq_profile, "710.10", "1.5", exact=True).issues
    assert exact.expected_value == "710.11"
    percent = number_cell("0.015", percent=True)  # "1,5 %": already divided by 100
    assert _discounted(boq_profile, "710.11", percent, exact=True).issues == []
    assert _discounted(boq_profile, "720.92", None).issues == []  # empty: no discount
    [issue] = _discounted(boq_profile, "720.92", "1.5").issues  # the discount was not taken
    calculation = issue.evidence[0].calculation
    assert calculation is not None
    [base, keep] = calculation.operands  # their product is the exact result, as written
    assert (base.value, keep.value) == (Decimal("720.92"), Decimal("0.985"))
    assert calculation.exact_result == base.value * keep.value == Decimal("710.1062")
    assert "73.789 × 9.77 = 720.91853 → 720.92; 720.92 × 0.985" in issue.evidence[0].detail
    assert "4.6.17" in issue.evidence[1].detail
    assert len(issue.evidence[0].cells) == 4  # quantity, price, total and the discount
    assert_well_formed([issue])


def test_an_unusable_discount_skips_the_row(boq_profile: DomainProfile) -> None:
    result = _discounted(boq_profile, "1.00", ambiguous_cell("1,500"))
    assert result.issues == []
    assert result.coverage["rows_skipped_unusable_inputs"] == 1


# ---------------------------------------------------------------- the unit price prevails (B2.2)
PREVAILING = "Prevailing value"
VOB_RULE = (
    "VOB/A §16c (2) Nr. 1: if the total of a position differs from quantity × unit price, the "
    "unit price prevails."
)
BID_NOTE = (
    "This bid (GAEB X84 or D84) does not say which positions are lump sums (the tender it "
    "answers does), so the lump-sum exception can only be checked with the tender."
)
ITEM_TYPE_COLUMNS = [*BOQ_COLUMNS, ("Positionsart", "item_type")]
GAEB_FIXTURES = Path(__file__).parents[3] / "fixtures" / "gaeb"


def _eur(value: str) -> Any:
    return number_cell(value, currency="EUR")


def _rule(issue: Any) -> Any:
    [rule] = [e for e in issue.evidence if e.label == PREVAILING]
    assert rule.kind is EvidenceKind.RULE
    return rule


def _assert_same_finding(first: Any, second: Any) -> None:
    """Only the words differ: values, amounts, severity and fingerprint stay the same."""
    assert (first.fingerprint, first.evidence_digest) == (
        second.fingerprint,
        second.evidence_digest,
    )
    assert (first.severity, first.evidence_class, first.title) == (
        second.severity,
        second.evidence_class,
        second.title,
    )
    assert (first.observed_value, first.expected_value) == (
        second.observed_value,
        second.expected_value,
    )
    one, other = first.estimated_financial_impact, second.estimated_financial_impact
    assert one is not None and other is not None
    assert (one.amount, one.reported, one.recomputed, one.currency) == (
        other.amount,
        other.reported,
        other.recomputed,
        other.currency,
    )


def _bid(profile: DomainProfile, rows: list[list[Any]], warning: ExtractionWarning) -> Dataset:
    builder = DatasetBuilder(profile, warnings=[warning])
    table = builder.table("LV", BOQ_COLUMNS)
    for values in rows:
        table.row(values)
    return builder.build()


def _bid_warning(table_id: str | None = None) -> ExtractionWarning:
    return ExtractionWarning(
        code="gaeb_bid_without_tender",
        message="An X84 bid carries prices but not the item flags.",
        table_id=table_id,
        needs_review=False,
    )


def test_sentences_show_amounts_with_two_decimals_and_the_values_stay_exact(
    boq_profile: DomainProfile,
) -> None:
    # Totals written with one decimal place: the recomputation is rounded to one, "2000.0".
    rows = [_item("200", "10", "1800.0"), _item("48", "13", "624.0", code="02")]
    [issue] = _issues(boq_profile, rows)
    assert issue.title == "Line total 1800.00 does not match Quantity × Unit price = 2000.00"
    assert "(difference -200.00, allowed" in issue.explanation
    assert issue.observed_value == "1800.0" and issue.expected_value == "2000.0"


def test_the_unit_price_prevails_with_the_boq_profile(boq_profile: DomainProfile) -> None:
    rows = [_item("12", _eur("40.00"), _eur("500.00"))]
    [issue] = _issues(boq_profile, rows)
    assert issue.explanation.endswith(
        "The Unit price prevails, so the corrected Line total is 480.00."
    )
    rule = _rule(issue)
    assert rule.detail == VOB_RULE
    assert rule.data == {"prevails": PREVAILS_UNIT_PRICE, "corrected_line_total": "480.00"}
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.amount == Decimal("20.00")
    assert impact.basis == "stated line total minus corrected line total (the unit price prevails)"
    assert issue.suggested_action == (
        "Confirm the Unit price 40.00: it prevails, so the Line total counts as 480.00. If "
        "500.00 was meant, the Unit price is the figure to correct."
    )
    # Without the rule (the default outside the BoQ profile): the words of before.
    [plain] = _issues(boq_profile, rows, {"prevailing_value": "none"})
    assert all(e.label != PREVAILING for e in plain.evidence)
    assert plain.explanation.endswith("(difference 20.00, allowed ±0.01).")
    assert plain.suggested_action == (
        "Check Quantity, Unit price and Line total in the source document: one of them is "
        "wrong (the recomputation does not show which)."
    )
    plain_impact = plain.estimated_financial_impact
    assert plain_impact is not None
    assert plain_impact.basis == "stated line total minus recomputed line total"
    _assert_same_finding(plain, issue)
    assert LineTotalConfig().prevailing_value == "none"


def test_the_corrected_total_keeps_the_item_discount(boq_profile: DomainProfile) -> None:
    [issue] = _discounted(boq_profile, "720.92", "1.5").issues  # the discount was not taken
    assert _rule(issue).data["corrected_line_total"] == "710.11"
    assert issue.explanation.endswith("so the corrected Line total is 710.11.")


def test_a_decimal_slip_states_the_corrected_total_too(boq_profile: DomainProfile) -> None:
    [issue] = _issues(boq_profile, [_item("12", "40.00", "4800.00")])
    assert "a decimal slip?" in issue.title
    assert _rule(issue).data["corrected_line_total"] == "480.00"


def test_a_lump_sum_keeps_its_stated_amount(boq_profile: DomainProfile) -> None:
    rows = [_item("1", _eur("2500.00"), _eur("2400.00"), unit_cell("psch", "ls"))]
    [issue] = _issues(boq_profile, rows)
    assert issue.explanation.endswith(
        "The position is a lump sum (unit psch), so its stated Line total 2400.00 prevails, "
        "not Quantity × Unit price."
    )
    rule = _rule(issue)
    assert "VOB-Stelle Rheinland-Pfalz" in rule.detail
    assert '"Pauschalsumme gilt immer unverändert' in rule.detail
    assert rule.data == {
        "prevails": PREVAILS_STATED_AMOUNT,
        "corrected_line_total": "2400.00",
        "lump_sum_by": "unit",
    }
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.amount == Decimal("-100.00")
    assert impact.basis == (
        "stated line total minus recomputed line total (a lump sum: the stated amount prevails)"
    )
    assert issue.suggested_action == (
        "Confirm that 2400.00 is the lump sum meant: it stands as stated, whatever Quantity × "
        "Unit price gives."
    )
    [plain] = _issues(boq_profile, rows, {"prevailing_value": "none"})
    _assert_same_finding(plain, issue)


@pytest.mark.parametrize(
    ("item_type", "prevails"),
    [
        ("Pauschalposition", PREVAILS_STATED_AMOUNT),
        ("Grundposition, Pauschalposition", PREVAILS_STATED_AMOUNT),
        ("Normalposition", PREVAILS_UNIT_PRICE),
        (None, PREVAILS_UNIT_PRICE),
    ],
)
def test_the_item_type_can_name_a_lump_sum(
    boq_profile: DomainProfile, item_type: str | None, prevails: str
) -> None:
    rows = [[*_item("12", "40.00", "500.00"), item_type]]
    dataset = boq_dataset(boq_profile, rows, columns=ITEM_TYPE_COLUMNS)
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    rule = _rule(issue)
    assert rule.data["prevails"] == prevails
    if prevails == PREVAILS_STATED_AMOUNT:
        assert "(Item type Pauschalposition)" in issue.explanation
        assert rule.data["lump_sum_by"] == "item_type"


def test_a_bid_cannot_say_which_positions_are_lump_sums(boq_profile: DomainProfile) -> None:
    rows = [_item("12", _eur("40.00"), _eur("500.00"))]
    [issue] = run(DETECTOR, _bid(boq_profile, rows, _bid_warning()), boq_profile).issues
    assert issue.explanation.endswith(
        "The Unit price prevails, so the corrected Line total is 480.00, unless the position is "
        f"a lump sum, whose stated amount stands. {BID_NOTE}"
    )
    assert _rule(issue).data == {
        "prevails": PREVAILS_UNLESS_LUMP_SUM,
        "corrected_line_total": "480.00",
    }
    [caveat] = [e for e in issue.evidence if e.label == "Lump sums not known"]
    assert caveat.kind is EvidenceKind.NOTE and caveat.detail == BID_NOTE
    impact = issue.estimated_financial_impact
    assert impact is not None
    assert impact.basis == (
        "stated line total minus corrected line total (the unit price prevails unless the "
        "position is a lump sum)"
    )
    assert issue.suggested_action == (
        "Confirm the Unit price 40.00: it prevails, so the Line total counts as 480.00 unless "
        "the position is a lump sum (then 500.00 stands). If 500.00 was meant and the position "
        "is no lump sum, the Unit price is the figure to correct."
    )
    [plain] = _issues(boq_profile, rows)
    _assert_same_finding(plain, issue)
    # A unit that says lump sum settles it, even in a bid.
    lump = [_item("1", "2500.00", "2400.00", unit_cell("psch", "ls"))]
    [lump_issue] = run(DETECTOR, _bid(boq_profile, lump, _bid_warning()), boq_profile).issues
    assert _rule(lump_issue).data["prevails"] == PREVAILS_STATED_AMOUNT
    # A warning about another table does not make this one a bid.
    elsewhere = _bid(boq_profile, rows, _bid_warning("tbl_999999"))
    [other] = run(DETECTOR, elsewhere, boq_profile).issues
    assert _rule(other).data["prevails"] == PREVAILS_UNIT_PRICE


def test_a_gaeb_bid_carries_the_lump_sum_caveat(boq_profile: DomainProfile, tmp_path: Path) -> None:
    x84 = (GAEB_FIXTURES / "small.x84").read_text(encoding="utf-8")
    changed = x84.replace("<IT>710.11</IT>", "<IT>720.92</IT>")  # the discount was not taken
    assert changed != x84
    path = tmp_path / "bid.x84"
    path.write_text(changed, encoding="utf-8")
    raw = GaebAdapter("84").extract(path, IngestionLimits())
    assert "gaeb_bid_without_tender" in {w.code for w in raw.warnings}
    dataset = build_dataset(
        raw, profile=boq_profile, document_id="doc", ids=SequentialIdFactory(), clock=FixedClock()
    )
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert (issue.observed_value, issue.expected_value) == ("720.92", "710.11")
    assert _rule(issue).data == {
        "prevails": PREVAILS_UNLESS_LUMP_SUM,
        "corrected_line_total": "710.11",
    }
    assert issue.explanation.endswith(BID_NOTE)


def test_a_gaeb_90_bid_carries_the_lump_sum_caveat(
    boq_profile: DomainProfile, tmp_path: Path
) -> None:
    # A D84 made from small.d86 (small.d84 has no quantities): phase 84 in record 00, and the
    # total of 01.01.10 (125 m3 at 42.50) stated as 631.25.
    lines = (GAEB_FIXTURES / "small.d86").read_bytes().decode("cp850").split("\r\n")
    assert lines[0][10:12] == "86"
    lines[0] = f"{lines[0][:10]}84{lines[0][12:]}"
    [at] = [i for i, line in enumerate(lines) if line.startswith("230101  10")]
    assert "000000053125" in lines[at]
    lines[at] = lines[at].replace("000000053125", "000000063125")
    path = tmp_path / "bid.d84"
    path.write_bytes("\r\n".join(lines).encode("cp850"))
    raw = Gaeb90Adapter("84").extract(path, IngestionLimits())
    assert raw.format is DocumentFormat.GAEB_D84
    [bid] = [w for w in raw.warnings if w.code == "gaeb_bid_without_tender"]
    assert "A D84 bid" in bid.message
    dataset = build_dataset(
        raw, profile=boq_profile, document_id="doc", ids=SequentialIdFactory(), clock=FixedClock()
    )
    [issue] = run(DETECTOR, dataset, boq_profile).issues
    assert (issue.observed_value, issue.expected_value) == ("631.25", "531.25")
    assert _rule(issue).data["prevails"] == PREVAILS_UNLESS_LUMP_SUM
    assert issue.explanation.endswith(BID_NOTE)
    [caveat] = [e for e in issue.evidence if e.label == "Lump sums not known"]
    assert caveat.detail == BID_NOTE


def test_the_prevailing_value_settings_are_checked(boq_profile: DomainProfile) -> None:
    config = resolve(DETECTOR, boq_profile)
    assert (config.prevailing_value, config.prevailing_rule) == ("unit_price", VOB_RULE)
    assert config.lump_sums.unit_dimensions == ["lump_sum"]
    assert config.lump_sums.text_field == "item_type"
    assert config.lump_sums.undetermined_warnings == ["gaeb_bid_without_tender"]
    assert config.lump_sums.undetermined_note == BID_NOTE
    for bad in (
        {"prevailing_value": "line_total"},
        {"lump_sums": {"text_pattern": None}},  # text_field without a pattern
        {"lump_sums": {"text_pattern": "x*"}},  # matches the empty text
        {"lump_sums": {"text_pattern": "(unclosed"}},
        {"lump_sums": {"text_field": "Item type"}},  # not a field id
        {"lump_sums": {"undetermined_note": " "}},  # warnings without a note
        {"lump_sums": {"unknown": 1}},
    ):
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, bad)
