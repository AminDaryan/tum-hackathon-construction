"""Size bands of the price checks' findings, read from the findings the checks really make."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.evaluation import reading_list
from app.evaluation.evidence_bands import IDENTICAL_PRICES, PEER_PRICE, finding_band, with_band
from app.evaluation.scoring import Finding, findings_of
from app.validation.statistical.peer_price import PeerPriceDetector
from app.validation.statistical.rate_consistency import RateConsistencyDetector
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    boq_dataset,
    run,
)

COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]
LABOUR = "Facharbeiter Stundenlohn Tiefbau"
WALL = "Mauerwerk Kalksandstein 24 cm"


def item(code: str, text: str, price: str, qty: str = "10", unit: str = "h") -> list[str]:
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total), "EUR"]


def checked(detector, profile, rows, overrides=None) -> list[Finding]:
    """The detector's findings as the scorer and the reading list read them (source row 1 is
    the header)."""
    dataset = boq_dataset(profile, rows, columns=COLUMNS)
    return findings_of(run(detector, dataset, profile, overrides).issues, dataset)


def finding(rule: tuple[str, str], title: str = "", rows: frozenset[int] = frozenset()) -> Finding:
    return Finding(
        issue_id="iss",
        detector_id=rule[0],
        rule_id=rule[1],
        severity="medium",
        title=title,
        rows=rows,
        cells=frozenset(),
    )


@pytest.mark.parametrize(
    ("price", "band"),
    [
        ("8.00", "tenfold"),  # 81.00 with a lost digit
        ("800.00", "tenfold"),
        ("20.00", "below_tenfold"),
        ("200.00", "below_tenfold"),
    ],
)
def test_a_peer_price_finding_is_banded_by_how_far_it_is_off_the_median(
    boq_profile, price: str, band: str
) -> None:
    rows = [
        item(f"1.{n}", LABOUR, p) for n, p in enumerate(["78.00", "80.00", "82.00", "84.00"], 1)
    ]
    rows.append(item("1.5", LABOUR, price))
    findings = checked(PeerPriceDetector, boq_profile, rows, {"min_ratio": 1})
    [odd] = [f for f in findings if f.rows == {6}]  # the band is read from the check's own title
    assert (odd.detector_id, odd.rule_id) == PEER_PRICE
    assert finding_band(odd) == band


def test_eight_times_the_median_is_the_first_tenfold_price() -> None:
    title = "Unit price {} far above comparable positions (median {})"
    assert finding_band(finding(PEER_PRICE, title.format("10.00", "1.25"))) == "tenfold"
    assert finding_band(finding(PEER_PRICE, title.format("10.00", "1.26"))) == "below_tenfold"
    assert finding_band(finding(PEER_PRICE, "a title in other words")) is None


@pytest.mark.parametrize(
    ("second", "band"),
    [
        ("458.00", "far_apart"),  # a slipped decimal point
        ("54.50", "far_apart"),  # 45.80 plus 19 % VAT, to the cent
        ("54.80", "close"),  # two digits swapped: a slip the band does not see
        ("60.00", "close"),
    ],
)
def test_two_identical_positions_are_banded_by_how_far_their_prices_are_apart(
    boq_profile, second: str, band: str
) -> None:
    rows = [item("1.1", WALL, "45.80", unit="m2"), item("2.1", WALL, second, unit="m2")]
    [both] = checked(RateConsistencyDetector, boq_profile, rows)
    assert (both.detector_id, both.rule_id) == IDENTICAL_PRICES
    assert finding_band(both) == band


def test_a_group_of_identical_positions_names_no_two_prices_and_keeps_its_rule(
    boq_profile,
) -> None:
    rows = [item(f"{n}.1", WALL, "45.80", unit="m2") for n in (1, 2, 3)]
    rows.append(item("4.1", WALL, "458.00", unit="m2"))  # one copy unlike the three others
    [odd] = checked(RateConsistencyDetector, boq_profile, rows)
    assert (odd.detector_id, odd.rule_id) == IDENTICAL_PRICES
    assert finding_band(odd) is None


def test_no_band_for_a_price_that_is_not_positive_or_for_any_other_rule() -> None:
    assert (
        finding_band(finding(IDENTICAL_PRICES, "Identical positions priced 0.00 and 4.10")) is None
    )
    other = finding(
        ("deterministic.line_total", "line_total_mismatch"), "Identical positions priced 1 and 100"
    )
    assert finding_band(other) is None


def test_the_band_joins_the_rule_in_the_hit_rate_key() -> None:
    key = "statistical.peer_price:peer_price_outlier"
    assert with_band(key, None) == key
    assert with_band(key, "tenfold") == "statistical.peer_price:peer_price_outlier#tenfold"


def test_the_reading_list_counts_and_looks_up_a_price_finding_under_its_band() -> None:
    title = "Unit price 8.00 far below comparable positions (median 81.00)"
    assert reading_list.rule_key(finding(PEER_PRICE, title)) == (
        "statistical.peer_price:peer_price_outlier#tenfold"
    )
