"""statistical.peer_price: unit prices far from comparable positions of the same bill."""

from __future__ import annotations

from decimal import Decimal

from app.models.issue import EvidenceClass, Severity
from app.validation.statistical.peer_price import (
    ROWS_WITHOUT_PEERS,
    RULE_ID,
    PeerPriceDetector,
)
from tests.support.builders import DatasetBuilder
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    boq_dataset,
    run,
)

COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]


def item(code, text, qty, unit, price):
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total), "EUR"]


def labour(code, price, qty="10"):
    return item(code, "Facharbeiter Stundenlohn Tiefbau", qty, "h", price)


def test_a_price_ten_times_too_low_is_a_high_signal_with_the_amount_at_stake(boq_profile) -> None:
    rows = [labour(f"1.{n}", p) for n, p in enumerate(["78.00", "80.00", "82.00", "85.00"], 1)]
    rows.append(labour("1.5", "8.00", qty="100"))  # 80.00 with a lost digit
    found = run(PeerPriceDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile)
    [issue] = found.issues
    assert issue.rule_id == RULE_ID
    assert issue.evidence_class == EvidenceClass.SUSPECTED_ANOMALY  # a signal, never confirmed
    assert issue.severity == Severity.HIGH
    assert issue.anomaly_score is not None and issue.anomaly_score.value < -6
    assert not issue.anomaly_score.calibrated
    impact = issue.estimated_financial_impact
    assert impact is not None and impact.kind == "reference_deviation"
    # 100 h × (8.00 − median 81.00 of the four peers)
    assert (impact.amount, impact.recomputed, impact.currency) == (
        Decimal("-7300.00"),
        Decimal("81.00"),
        "EUR",
    )
    assert issue.affected_cells[0].source.row_number == 6
    # Said as a share of the typical price, not as a distance in robust scales.
    assert issue.explanation.startswith(
        "The unit price 8.00 of 1.5 is about 10 % of the typical price (81.00, the median) of "
        "4 positions with similar text in the same unit."
    )
    assert_well_formed(found.issues)


def test_a_price_ten_times_too_high_is_found_as_well(boq_profile) -> None:
    rows = [labour(f"1.{n}", p) for n, p in enumerate(["78.00", "80.00", "82.00", "800.00"], 1)]
    [issue] = run(
        PeerPriceDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile
    ).issues
    assert issue.anomaly_score is not None and issue.anomaly_score.value > 6
    assert issue.estimated_financial_impact.amount > 0
    # Two decimals, as in the explanation (it was "Unit price 800 ... (median 80)").
    assert issue.title == "Unit price 800.00 far above comparable positions (median 80.00)"
    assert "is about 10 times the typical price (80.00, the median) of 3 positions" in (
        issue.explanation
    )


def test_ordinary_spread_and_lone_positions_raise_nothing(boq_profile) -> None:
    rows = [labour(f"1.{n}", p) for n, p in enumerate(["70.00", "80.00", "90.00", "95.00"], 1)]
    rows.append(item("2.1", "Baustelleneinrichtung", "1", "psch", "9000.00"))  # no peers
    foreign = labour("3.1", "800.00")
    foreign[-1] = "USD"  # same unit/text, but not comparable without currency conversion
    rows.append(foreign)
    found = run(PeerPriceDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile)
    assert found.issues == []
    assert found.coverage[ROWS_WITHOUT_PEERS] == 2  # counted, not silently passed


def test_a_price_two_and_a_half_times_the_group_is_left_to_the_reviewer(boq_profile) -> None:
    # Comparable work in a correct bill is often 2 to 3 times apart (min_ratio 3 in the profile).
    rows = [labour(f"1.{n}", p) for n, p in enumerate(["78.00", "80.00", "82.00", "200.00"], 1)]
    dataset = boq_dataset(boq_profile, rows, columns=COLUMNS)
    assert run(PeerPriceDetector, dataset, boq_profile).issues == []
    assert len(run(PeerPriceDetector, dataset, boq_profile, {"min_ratio": 1}).issues) == 1
    rows[-1] = labour("1.4", "260.00")  # 3.25 times the median of 80.00
    found = run(PeerPriceDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile)
    assert len(found.issues) == 1


def test_a_contingency_position_is_compared_with_normal_ones_but_never_their_peer(
    boq_profile,
) -> None:
    builder = DatasetBuilder(boq_profile)
    table = builder.table("LV", COLUMNS)
    for n, price in enumerate(["78.00", "80.00", "82.00", "85.00"], 1):
        table.row(labour(f"1.{n}", price))
    table.row(labour("1.5", "200.00"), in_totals=False)  # Bedarfsposition ohne Gesamtbetrag
    found = run(PeerPriceDetector, builder.build(), boq_profile)
    [issue] = found.issues  # the contingency price, not the normal positions it would distort
    assert issue.affected_cells[0].source.row_number == 6
    assert issue.estimated_financial_impact.recomputed == Decimal("81.00")


def test_close_matches_are_not_outvoted_by_looser_ones(boq_profile) -> None:
    # Pressure tests of a drain share words with laying the drain but are other work: the row's
    # own kind of work is its peer group, not the pipe laying that outnumbers it.
    rows = [
        item(f"1.{n}", "Druckprüfung der Abwasserleitung DN 150", "40", "m", price)
        for n, price in enumerate(["11.00", "12.00", "12.50", "13.00", "12.20"], 1)
    ]
    rows += [
        item(f"2.{n}", "Abwasserleitung DN 150 verlegen", "40", "m", price)
        for n, price in enumerate(["78.00", "80.00", "82.00", "85.00", "79.00", "81.00"], 1)
    ]
    found = run(PeerPriceDetector, boq_dataset(boq_profile, rows, columns=COLUMNS), boq_profile)
    assert found.issues == []
