"""domain.boq_bid_prices: positions not offered, zero and token prices, and hourly rates below
the floor (plan section 8, B2.1, and plan section 5a)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.clock import FixedClock
from app.core.config import IngestionLimits
from app.core.ids import SequentialIdFactory
from app.ingestion.gaeb.adapter import GaebAdapter
from app.models.dataset import ExtractionWarning
from app.models.issue import EvidenceClass, Severity
from app.models.values import ValueMarker
from app.normalization.builder import build_dataset
from app.validation.contracts.conditions import Coverage
from app.validation.deterministic.line_total import LineTotalDetector
from app.validation.deterministic.required_values import RequiredValuesDetector
from app.validation.deterministic.unit_price_components import UnitPriceComponentsDetector
from app.validation.domain.boq.bid_prices import (
    OTHER_CURRENCY,
    RULE_FLOOR,
    RULE_NEGATIVE,
    RULE_NOMINAL,
    RULE_NOT_OFFERED,
    RULE_TAX,
    RULE_ZERO,
    BoqBidPricesConfig,
    BoqBidPricesDetector,
)
from tests.support.builders import DatasetBuilder, marker_cell, number_cell
from tests.unit.validation.deterministic.references_fixtures import (
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    by_rule,
    resolve,
    run,
    run_pipeline,
)

DETECTOR = BoqBidPricesDetector
GAEB_FIXTURES = Path(__file__).parents[3] / "fixtures" / "gaeb"
COLUMNS = [
    ("Pos.", "item_code"),
    ("Kurztext", "description"),
    ("Menge", "quantity"),
    ("ME", "unit"),
    ("EP", "unit_price"),
    ("Positionsart", "item_type"),
]


BID_WARNING = ExtractionWarning(
    code="gaeb_bid_without_tender",
    message="An X84 bid carries prices but not the item flags.",
    needs_review=False,
)


def dataset(profile, rows, in_totals=None, warnings=()):
    builder = DatasetBuilder(profile, warnings=warnings)
    table = builder.table("LV", COLUMNS)
    for index, values in enumerate(rows):
        table.row(values, in_totals=(in_totals or {}).get(index, True))
    return builder.build()


def priced(*rows):
    """``rows`` after enough priced positions to make the table a bid."""
    normal = [[f"09.00{n}0", "Boden lösen", "10", "m3", "9.00", "Normalposition"] for n in range(5)]
    return [*normal, *rows]


def result(profile, rows, in_totals=None, warnings=()):
    return run(DETECTOR, dataset(profile, rows, in_totals, warnings), profile)


class TestZeroAndTokenPrices:
    def test_a_zero_price_and_a_token_price_are_two_rules(self, boq_profile) -> None:
        rows = priced(
            ["01.0010", "Verbau", "100", "m2", "0.01", "Normalposition"],
            ["01.0020", "Wasserhaltung", "1", "psch", "0.00", "Pauschalposition"],
            ["01.0030", "Pflaster", "10", "m2", "0.10", "Normalposition"],
        )
        found = result(boq_profile, rows)
        [token] = by_rule(found.issues, RULE_NOMINAL)
        [zero] = by_rule(found.issues, RULE_ZERO)
        assert token.rule_id == "token_price"  # the test set's key uses this rule id
        assert zero.rule_id == "zero_price"
        for issue in (token, zero):  # plan section 8: suspected anomaly, medium
            assert (issue.severity, issue.evidence_class) == (
                Severity.MEDIUM,
                EvidenceClass.SUSPECTED_ANOMALY,
            )
        assert token.title == "Token unit price 0.01 in 01.0010"
        assert zero.title == "Unit price 0.00 in 01.0020"
        assert zero.explanation == (
            "01.0020 has a unit price of 0.00 for a quantity of 1: the work is offered free of "
            "charge, or its price was left out."
        )
        assert {c.source.a1 for c in token.affected_cells} == {"E7"}
        assert {c.source.a1 for c in zero.affected_cells} == {"E8"}
        assert "X ZB 7/04" in (token.suggested_action or "")
        assert "free of charge" in (zero.suggested_action or "")
        for issue in (token, zero):  # plan 5a: no cost moved elsewhere, no note in the bill
            action = issue.suggested_action or ""
            assert "this position's own cost, never priced into other positions" in action
            assert "ask a bidder question instead of writing a note into the bill" in action
            assert "note where" not in action
        assert len(found.issues) == 2
        assert_unique_fingerprints(found.issues)
        assert_well_formed(found.issues)

    def test_the_token_prices_come_from_the_profile(self, boq_profile) -> None:
        assert resolve(DETECTOR, boq_profile).token_prices == (Decimal("0.01"),)
        assert BoqBidPricesConfig().token_prices == (Decimal("0.01"),)
        rows = priced(["01.0010", "Verbau", "100", "m2", "0.10", "Normalposition"])
        found = run(DETECTOR, dataset(boq_profile, rows), boq_profile, {"token_prices": ["0.10"]})
        assert [i.rule_id for i in found.issues] == [RULE_NOMINAL]

    def test_a_zero_price_on_a_quantity_of_zero_is_no_finding(self, boq_profile) -> None:
        rows = priced(["01.0010", "Verbau", "0", "m2", "0.00", "Normalposition"])
        assert result(boq_profile, rows).issues == []

    def test_a_zero_price_without_a_quantity_is_a_finding(self, boq_profile) -> None:
        rows = priced(["01.0010", "Verbau", None, "m2", "0.00", "Normalposition"])
        [issue] = result(boq_profile, rows).issues
        assert issue.rule_id == RULE_ZERO
        assert issue.explanation.startswith("01.0010 has a unit price of 0.00: the work")

    def test_positions_outside_the_sum_are_flagged(self, boq_profile) -> None:
        """Changed on purpose in B2.1: an alternative or contingency position must be priced
        too (GAEB 3.3 §4.5.2), so a position outside the sum is no longer skipped."""
        rows = priced(
            ["01.0010", "Verbau", "100", "m2", "0.01", "Bedarfsposition ohne GB"],
            ["01.0020", "Verbau", "100", "m2", "0.00", "Wahlposition"],
        )
        found = result(boq_profile, rows, in_totals={5: False, 6: False})
        assert [i.rule_id for i in found.issues] == [RULE_NOMINAL, RULE_ZERO]
        for issue in found.issues:
            assert issue.explanation.endswith(
                "The position does not count toward the total, but an alternative or "
                "contingency position must be priced too (GAEB 3.3 §4.5.2)."
            )

    def test_positions_omitted_or_not_offered_are_not_flagged(self, boq_profile) -> None:
        rows = priced(
            ["01.0010", "Verbau", "100", "m2", "0.01", "Normalposition, entfällt"],
            ["01.0020", "Verbau", "100", "m2", "0.00", "entfällt"],
        )
        assert result(boq_profile, rows, in_totals={5: False, 6: False}).issues == []

    def test_a_position_whose_count_is_unknown_is_flagged(self, boq_profile) -> None:
        # A GAEB bid (X84) leaves counts_toward_totals unknown on every row.
        rows = priced(["01.0010", "Verbau", "100", "m2", "0.01", "Normalposition"])
        found = result(boq_profile, rows, in_totals={5: None})
        assert [i.rule_id for i in found.issues] == [RULE_NOMINAL]


class TestNotOffered:
    def test_a_position_not_offered(self, boq_profile) -> None:
        rows = priced(["01.0010", "Pflaster", "10", "m2", None, "Normalposition, nicht angeboten"])
        [issue] = result(boq_profile, rows).issues
        assert issue.rule_id == RULE_NOT_OFFERED
        assert (issue.severity, issue.evidence_class) == (
            Severity.HIGH,
            EvidenceClass.CONFIRMED_RULE_VIOLATION,
        )
        assert issue.title == "01.0010 is not offered"
        assert issue.explanation == (
            "01.0010 is marked 'nicht angeboten' (item type 'Normalposition, nicht angeboten'), "
            "so the bid has no price for it."
        )
        assert {c.source.a1 for c in issue.affected_cells} == {"F7", "E7"}
        assert "§ 16a (2) VOB/A" in (issue.suggested_action or "")

    def test_a_token_price_on_a_position_not_offered_is_one_finding(self, boq_profile) -> None:
        rows = priced(["01.0010", "Pflaster", "10", "m2", "0.00", "nicht angeboten"])
        assert [i.rule_id for i in result(boq_profile, rows).issues] == [RULE_NOT_OFFERED]

    @pytest.mark.parametrize("written", ["nicht angeboten", "Not offered"])
    def test_a_spreadsheet_marker_in_the_unit_price(self, boq_profile, written) -> None:
        price = marker_cell(written, ValueMarker.NOT_OFFERED)
        rows = priced(["01.0010", "Pflaster", "10", "m2", price, "Normalposition"])
        [issue] = result(boq_profile, rows).issues
        assert (issue.rule_id, issue.severity) == (RULE_NOT_OFFERED, Severity.HIGH)
        assert issue.explanation == (
            f"01.0010 has '{written}' as its unit price, so the bid has no price for it."
        )
        assert issue.observed_value == written
        assert {c.source.a1 for c in issue.affected_cells} == {"E7"}
        assert_well_formed([issue])

    def test_the_marker_is_read_from_the_profile_tokens(self, boq_profile) -> None:
        rows = priced(["01.0010", "Pflaster", "10", "m2", "nicht angeboten", "Normalposition"])
        built = dataset(boq_profile, rows)
        table = built.tables[0]
        price = table.column_for_field("unit_price")
        assert price is not None
        assert table.rows[5].cells[price.column_id].marker is ValueMarker.NOT_OFFERED
        assert [i.rule_id for i in run(DETECTOR, built, boq_profile).issues] == [RULE_NOT_OFFERED]

    def test_a_position_outside_the_sum_is_medium(self, boq_profile) -> None:
        rows = priced(["01.0010", "Pflaster", "10", "m2", None, "Wahlposition, nicht angeboten"])
        [issue] = result(boq_profile, rows, in_totals={5: False}).issues
        assert (issue.rule_id, issue.severity) == (RULE_NOT_OFFERED, Severity.MEDIUM)
        assert "declared outside the sum" in issue.explanation
        assert "GAEB 3.3 §4.5.2" in issue.explanation
        rule = next(e for e in issue.evidence if e.label == "Not offered")
        assert rule.data == {"rule_id": RULE_NOT_OFFERED, "outside_the_sum": True}

    def test_in_a_bid_the_finding_points_to_the_tender(self, boq_profile) -> None:
        rows = priced(["01.0010", "Pflaster", "10", "m2", None, "nicht angeboten"])
        found = result(boq_profile, rows, in_totals={5: None}, warnings=[BID_WARNING])
        [issue] = found.issues
        assert issue.severity is Severity.HIGH  # the count is unknown, not outside the sum
        assert issue.explanation.endswith(
            "This bid (GAEB X84 or D84) does not say whether the position counts toward the "
            "total (the tender it answers does), so check its kind in the tender."
        )
        # A warning about another table does not make this one a bid.
        other = ExtractionWarning(**{**BID_WARNING.model_dump(), "table_id": "tbl_999999"})
        [plain] = result(boq_profile, rows, in_totals={5: None}, warnings=[other]).issues
        assert "GAEB X84" not in plain.explanation

    def test_the_bid_note_settings_are_checked(self, boq_profile) -> None:
        config = resolve(DETECTOR, boq_profile)
        assert config.undetermined_count_warnings == ["gaeb_bid_without_tender"]
        assert "GAEB X84" in config.undetermined_count_note
        with pytest.raises(ValidationError):
            BoqBidPricesConfig(undetermined_count_warnings=["gaeb_bid_without_tender"])


def test_the_other_checks_abstain_on_a_position_not_offered(boq_profile) -> None:
    """The not_offered marker is one finding, here: required_values does not report the cell
    as empty, and line_total and unit_price_components skip the row as a marker."""
    columns = [*COLUMNS, ("GP", "line_total"), ("EP-Anteil Lohn", "unit_price_component_1")]
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", columns)
    for n in range(5):
        normal = [f"09.00{n}0", "Boden lösen", "10", "m3", "9.00", "Normalposition"]
        table.row([*normal, "90.00", None])
    not_offered = marker_cell("nicht angeboten", ValueMarker.NOT_OFFERED)
    table.row(["01.0010", "Pflaster", "10", "m2", not_offered, "Normalposition", "0.00", "5.00"])
    built = builder.build()
    assert [i.rule_id for i in run(DETECTOR, built, boq_profile).issues] == [RULE_NOT_OFFERED]
    assert run(RequiredValuesDetector, built, boq_profile).issues == []
    lines = run(LineTotalDetector, built, boq_profile)
    assert lines.issues == [] and lines.coverage[Coverage.ROWS_SKIPPED_MARKER] == 1
    components = run(UnitPriceComponentsDetector, built, boq_profile)
    assert components.issues == [] and components.coverage[Coverage.ROWS_SKIPPED_MARKER] == 1


class TestHourlyFloor:
    def test_an_hourly_labour_rate_below_the_minimum_wage(self, boq_profile) -> None:
        rows = priced(
            ["03.05.0001", "Facharbeiter", "10", "h", "80.00", "Normalposition"],
            [
                "03.05.0002",
                "Wie Position 3. 5. 1., jedoch Bauwerker/-in",
                "10",
                "h",
                "8.00",
                "Normalposition",
            ],
            ["03.05.0003", "Helfer", "10", "Std", "13.89", "Normalposition"],
            ["03.05.0004", "Stunden", "10", "h", "12.00", "Stundenlohnarbeiten"],
            ["03.05.0005", "Helfer", "10", "h", "13.90", "Normalposition"],
        )
        found = result(boq_profile, rows)
        issues = by_rule(found.issues, RULE_FLOOR)
        assert [i.title for i in issues] == [
            "Hourly rate 8.00 in 03.05.0002 is below the minimum wage",
            "Hourly rate 13.89 in 03.05.0003 is below the minimum wage",
            "Hourly rate 12.00 in 03.05.0004 is below the minimum wage",
        ]
        first = issues[0]
        assert (first.severity, first.evidence_class) == (
            Severity.HIGH,
            EvidenceClass.SUSPECTED_ANOMALY,
        )
        assert "13,90 EUR gross per hour since 2026-01-01" in first.explanation
        assert first.expected_value == ">= 13.90"
        assert (first.suggested_action or "").startswith(
            "An hourly rate below 13.90 EUR cannot cover the wage"
        )
        assert_well_formed(found.issues)

    def test_hours_without_labour_and_other_units_have_no_floor(self, boq_profile) -> None:
        rows = priced(
            ["01.0010", "Container vorhalten", "100", "Std", "2.50", "Normalposition"],
            ["01.0020", "Bauwerker", "10", "d", "9.00", "Normalposition"],
            ["01.0030", "Pumpe mit Schlauch", "10", "h", "6.00", "Normalposition"],
        )
        assert result(boq_profile, rows).issues == []

    def test_a_token_hourly_rate_is_one_finding(self, boq_profile) -> None:
        rows = priced(["01.0010", "Bauwerker", "10", "h", "0.01", "Normalposition"])
        assert [i.rule_id for i in result(boq_profile, rows).issues] == [RULE_NOMINAL]
        rows = priced(["01.0010", "Bauwerker", "10", "h", "0.00", "Normalposition"])
        assert [i.rule_id for i in result(boq_profile, rows).issues] == [RULE_ZERO]

    def test_a_rate_in_another_currency_is_not_compared(self, boq_profile) -> None:
        price = number_cell("8.00", currency="CHF")
        rows = priced(["01.0010", "Bauwerker", "10", "h", price, "Normalposition"])
        found = result(boq_profile, rows)
        assert found.issues == []
        assert found.coverage[OTHER_CURRENCY] == 1

    def test_the_floor_is_set_in_the_profile(self, boq_profile) -> None:
        """The floor changes each January: it is set in boq.yaml, not only in the code."""
        defaults = boq_profile.detector_defaults["domain.boq_bid_prices"]
        assert Decimal(str(defaults["hourly_wage_floor"])) == Decimal("13.90")
        assert defaults["floor_currency"] == "EUR"
        assert "since 2026-01-01" in defaults["floor_source"]
        config = resolve(DETECTOR, boq_profile)
        assert config.hourly_wage_floor == Decimal("13.90")
        assert config.floor_source == defaults["floor_source"]

    def test_the_floor_is_configurable(self, boq_profile) -> None:
        rows = priced(["01.0010", "Bauwerker", "10", "h", "14.00", "Normalposition"])
        source = "statutory minimum wage (MiLoG), 14,60 EUR gross per hour since 2027-01-01"
        overrides = {"hourly_wage_floor": "14.60", "floor_source": source}
        found = run(DETECTOR, dataset(boq_profile, rows), boq_profile, overrides)
        [issue] = found.issues
        assert issue.expected_value == ">= 14.60"
        assert source in issue.explanation
        # The recommendation names the configured floor, not the default one.
        action = issue.suggested_action or ""
        assert action.startswith("An hourly rate below 14.60 EUR cannot cover the wage")
        assert "13,90" not in action and "13.90" not in action
        with pytest.raises(ValidationError):
            BoqBidPricesConfig(hourly_wage_floor=Decimal("0"))
        with pytest.raises(ValidationError):
            BoqBidPricesConfig(labour_pattern="")


class TestApplicability:
    def test_a_tender_without_prices_is_not_checked(self, boq_profile) -> None:
        """An unpriced bill (a tender: the unit price is empty on every item row) is noted
        once, and the check abstains (plan section 8, B2.1)."""
        rows = [
            ["01.0010", "Boden lösen", "10", "m3", None, "Normalposition"],
            ["01.0020", "Verbau", "10", "m2", None, "Normalposition, entfällt"],
            ["01.0030", "Pflaster", "10", "m2", None, "Bedarfsposition ohne GB"],
        ]
        verdict = applicability(DETECTOR, dataset(boq_profile, rows), boq_profile)
        assert not verdict.applicable
        assert verdict.reasons == (
            "No table has a unit price on any item row (an unpriced bill, such as a tender).",
        )

    def test_a_bid_is_checked(self, boq_profile) -> None:
        rows = priced()
        assert applicability(DETECTOR, dataset(boq_profile, rows), boq_profile).applicable

    def test_a_position_not_offered_and_a_zero_price_make_a_bid(self, boq_profile) -> None:
        """A position marked "nicht angeboten" and an explicit 0,00 are price states only a bid
        has (GAEB 3.3 §4.6.4), however few positions carry a price. This bill was once taken
        for a tender, and neither position was reported."""
        rows = [
            ["01.0010", "Boden lösen", "10", "m3", None, "Normalposition"],
            ["01.0020", "Verbau", "10", "m2", None, "nicht angeboten"],
            ["01.0030", "Pflaster", "10", "m2", "0.00", "Normalposition"],
        ]
        found = result(boq_profile, rows)
        [not_offered] = by_rule(found.issues, RULE_NOT_OFFERED)
        [zero] = by_rule(found.issues, RULE_ZERO)
        assert (not_offered.title, not_offered.severity) == (
            "01.0020 is not offered",
            Severity.HIGH,
        )
        assert zero.title == "Unit price 0.00 in 01.0030"
        assert len(found.issues) == 2
        assert found.coverage["priced_tables"] == 1

    @pytest.mark.parametrize("marked", ["item type", "unit price"])
    def test_a_bid_that_offers_few_positions_is_checked(self, boq_profile, marked) -> None:
        """Two of three positions not offered, by the GAEB item type or by the spreadsheet
        marker in the unit price: both are reported, and the third, priced, is not."""
        if marked == "item type":
            first = ["01.0010", "Verbau", "10", "m2", None, "nicht angeboten"]
            second = ["01.0020", "Pflaster", "3", "m2", None, "Normalposition, nicht angeboten"]
        else:
            price = marker_cell("nicht angeboten", ValueMarker.NOT_OFFERED)
            first = ["01.0010", "Verbau", "10", "m2", price, "Normalposition"]
            second = ["01.0020", "Pflaster", "3", "m2", price, "Normalposition"]
        rows = [first, second, ["01.0050", "Boden lösen", "1", "m3", "1000.00", "Normalposition"]]
        found = result(boq_profile, rows)
        assert [(i.rule_id, i.severity, i.title) for i in found.issues] == [
            (RULE_NOT_OFFERED, Severity.HIGH, "01.0010 is not offered"),
            (RULE_NOT_OFFERED, Severity.HIGH, "01.0020 is not offered"),
        ]

    def test_a_gaeb_bid_that_offers_few_positions_is_checked(
        self, boq_profile, tmp_path: Path
    ) -> None:
        """An X84 with two of its three positions NotOffered: both are reported once, here,
        and required_values leaves their empty prices to this check."""
        x84 = (GAEB_FIXTURES / "small.x84").read_text(encoding="utf-8")
        not_offered = (
            '<Item ID="I2" RNoPart="0020"><NotOffered>Yes</NotOffered><Qty>10</Qty></Item>'
            '<Item ID="I3" RNoPart="0030"><NotOffered>Yes</NotOffered><Qty>3</Qty></Item>'
        )
        changed = x84.replace(
            "</Item>\n            </Itemlist>", "</Item>" + not_offered + "</Itemlist>"
        )
        assert changed != x84
        path = tmp_path / "bid.x84"
        path.write_text(changed, encoding="utf-8")
        raw = GaebAdapter("84").extract(path, IngestionLimits())
        built = build_dataset(
            raw,
            profile=boq_profile,
            document_id="doc",
            ids=SequentialIdFactory(),
            clock=FixedClock(),
        )
        found = run(DETECTOR, built, boq_profile)
        assert [(i.rule_id, i.severity, i.title) for i in found.issues] == [
            (RULE_NOT_OFFERED, Severity.HIGH, "01.0020 is not offered"),
            (RULE_NOT_OFFERED, Severity.HIGH, "01.0030 is not offered"),
        ]
        assert all("GAEB X84" in i.explanation for i in found.issues)
        required = run(RequiredValuesDetector, built, boq_profile)
        assert required.issues == []
        assert required.coverage["cells_exempt"] == 4  # unit price and line total, twice


def test_findings_pass_the_pipeline_evidence_policy(boq_profile) -> None:
    rows = priced(
        ["01.0010", "Verbau", "100", "m2", "0.01", "Normalposition"],
        ["01.0020", "Pflaster", "10", "m2", None, "nicht angeboten"],
        ["01.0030", "Bauwerker", "10", "h", "8.00", "Normalposition"],
        ["01.0040", "Verbau", "100", "m2", "0.00", "Normalposition"],
        ["01.0050", "Pflaster", "10", "m2", "not offered", "Normalposition"],
    )
    outcome = run_pipeline(DETECTOR, dataset(boq_profile, rows), boq_profile)
    assert sorted(i.rule_id for i in outcome.issues) == sorted(
        [RULE_NOMINAL, RULE_NOT_OFFERED, RULE_FLOOR, RULE_ZERO, RULE_NOT_OFFERED]
    )
    assert_unique_fingerprints(outcome.issues)
    assert_well_formed(outcome.issues)


class TestNegativePrices:
    def test_a_price_below_zero_is_a_finding_although_the_total_multiplies(
        self, boq_profile
    ) -> None:
        rows = priced(["01.0010", "Kabelortung", "52", "m2", "-5.80", "Normalposition"])
        [issue] = by_rule(result(boq_profile, rows).issues, RULE_NEGATIVE)
        assert (issue.severity, issue.evidence_class) == (
            Severity.HIGH,
            EvidenceClass.SUSPECTED_ANOMALY,
        )
        assert issue.title == "Negative unit price -5.80 in 01.0010"
        assert "the sign is wrong or a credit is not declared" in issue.explanation
        assert {c.source.a1 for c in issue.affected_cells} == {"E7"}
        assert_well_formed([issue])

    @pytest.mark.parametrize(
        "text",
        ["Gutschrift für Altmetall", "Schrotterlös Stahlrohr", "Abzug für entfallene Leistung"],
    )
    def test_a_declared_credit_is_no_finding(self, boq_profile, text) -> None:
        rows = priced(["01.0010", text, "1", "psch", "-250.00", "Normalposition"])
        assert result(boq_profile, rows).issues == []

    def test_a_position_that_is_omitted_is_no_finding(self, boq_profile) -> None:
        rows = priced(["01.0010", "Verbau", "10", "m2", "-5.00", "entfällt"])
        assert by_rule(result(boq_profile, rows).issues, RULE_NEGATIVE) == []

    def test_a_negative_hourly_rate_is_one_finding(self, boq_profile) -> None:
        rows = priced(["01.0010", "Facharbeiter", "10", "h", "-48.00", "Stundenlohnarbeiten"])
        assert [i.rule_id for i in result(boq_profile, rows).issues] == [RULE_NEGATIVE]

    def test_the_credit_words_are_configurable(self, boq_profile) -> None:
        rows = priced(["01.0010", "Bonus für den Bauherrn", "1", "psch", "-250.00", ""])
        found = run(
            DETECTOR, dataset(boq_profile, rows), boq_profile, {"credit_pattern": r"\bbonus\b"}
        )
        assert found.issues == []


class TestTaxInUnitPrice:
    @pytest.mark.parametrize(
        ("price", "net"),
        [("9.99600", "8.40"), ("330.22500", "277.50"), ("1282.225", "1077.50")],
    )
    def test_a_price_that_is_a_cent_amount_plus_vat(self, boq_profile, price, net) -> None:
        rows = priced(["01.0010", "Druckprobe", "350", "m", price, "Normalposition"])
        [issue] = result(boq_profile, rows).issues
        assert issue.rule_id == RULE_TAX
        assert (issue.severity, issue.evidence_class) == (
            Severity.MEDIUM,
            EvidenceClass.SUSPECTED_ANOMALY,
        )
        assert issue.expected_value == net
        assert f"is {net} plus 19% VAT" in issue.title
        assert {c.source.a1 for c in issue.affected_cells} == {"E7"}
        assert_well_formed([issue])

    @pytest.mark.parametrize(
        "price",
        [
            "833.00",  # 700,00 plus 19 %, but a whole cent amount: looks like a net price
            "833.000",
            "9.995",  # no cent amount, and no cent amount plus 19 % either
            "0.125",
        ],
    )
    def test_other_prices_are_no_finding(self, boq_profile, price) -> None:
        rows = priced(["01.0010", "Druckprobe", "350", "m", price, "Normalposition"])
        assert result(boq_profile, rows).issues == []

    def test_the_rates_come_from_the_settings(self, boq_profile) -> None:
        assert BoqBidPricesConfig().vat_rates == (Decimal("19"),)
        rows = priced(["01.0010", "Druckprobe", "350", "m", "8.988", "Normalposition"])
        assert result(boq_profile, rows).issues == []
        found = run(DETECTOR, dataset(boq_profile, rows), boq_profile, {"vat_rates": ["7"]})
        [issue] = found.issues
        assert (issue.rule_id, issue.expected_value) == (RULE_TAX, "8.40")
        with pytest.raises(ValidationError):
            BoqBidPricesConfig(vat_rates=(Decimal("0"),))
