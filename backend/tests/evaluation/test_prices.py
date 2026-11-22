"""The price model and catalogue of the boq benchmark variant."""

from __future__ import annotations

import random
from decimal import Decimal

import pytest

from app.evaluation.prices import (
    CATALOGUE,
    OTHER_DIMENSION,
    TRADES,
    UNITS,
    PriceModel,
    parse_catalogue,
    quantity,
    similar_quantity,
    split,
)

pytestmark = pytest.mark.evaluation

FAMILIES = [family for trade in TRADES for family in trade.families]


def test_the_catalogue_has_twelve_trades_of_distinct_families() -> None:
    assert len(TRADES) == 12
    assert len({trade.trade_id for trade in TRADES}) == 12
    assert len({family.family_id for family in FAMILIES}) == len(FAMILIES)
    keys = [family.key(combo) for family in FAMILIES for combo in family.combos()]
    assert len(keys) == len(set(keys)) == 288
    assert all(key.startswith("SYN-") for key in keys)  # synthetic, never STLB-Bau keys


def test_every_family_text_fills_its_options_in_both_languages() -> None:
    for family in FAMILIES:
        for combo in family.combos():
            for language in ("de", "en"):
                text = family.text(combo, language)
                assert text and "{" not in text and "}" not in text, (family.family_id, text)
        if family.thickness is not None:
            assert family.unit.unit_id == "m3"
            assert all(family.thickness_of(combo) for combo in family.combos())


def test_english_choices_use_decimal_points() -> None:
    [trade] = parse_catalogue(
        "trade | 900 | Test | Test\n"
        "1 | m2 | 10 | 5 | - | Platte {} cm | Board {} cm | 1,25 x2 @0.0125; 2,5\n"
    )
    [family] = trade.families
    assert family.text((0,), "de") == "Platte 1,25 cm"
    assert family.text((0,), "en") == "Board 1.25 cm"
    assert family.factor((0,)) == 2 and family.factor((1,)) == 1
    assert family.thickness_of((0,)) == Decimal("0.0125")
    assert family.key((1,)) == "SYN-900-001-2000"


@pytest.mark.parametrize(
    "text",
    [
        "1 | m2 | 10 | 5 | - | A {} | B {} | x\n",  # a family before its trade
        "trade | 900 | T | T\n1 | m2 | 10 | 5 | - | A {} {} | B {} {} | x\n",  # options missing
    ],
)
def test_a_malformed_catalogue_is_refused(text: str) -> None:
    with pytest.raises(ValueError, match="family"):
        parse_catalogue(text)


def test_the_catalogue_text_is_parsed_into_the_module_trades() -> None:
    assert parse_catalogue(CATALOGUE) == TRADES


def test_the_same_family_and_options_cost_the_same_within_a_bill() -> None:
    model = PriceModel(random.Random(5))
    family = FAMILIES[0]
    first = model.unit_price(family, family.combos()[0])
    assert model.unit_price(family, family.combos()[0]) == first
    assert first == first.quantize(Decimal("0.01")) and first >= Decimal("0.01")
    other = PriceModel(random.Random(6))
    assert other.bill_factor != model.bill_factor


def test_quantities_follow_the_unit() -> None:
    rng = random.Random(3)
    for family in FAMILIES:
        value = quantity(rng, family)
        assert value > 0
        if family.scale == "lump_sum":
            assert value == 1 and similar_quantity(rng, family, value) == 1
        elif family.scale in ("count", "time"):
            assert value == value.to_integral_value()
        else:
            close = similar_quantity(rng, family, value)
            assert Decimal("0.7") * value <= close <= Decimal("1.4") * value


def test_components_add_up_to_the_price_exactly() -> None:
    rng = random.Random(9)
    for cents in (4, 5, 99, 12345, 9999999):
        price = Decimal(cents) / 100
        for parts in (2, 3, 4):
            if cents < parts:
                continue
            shares = split(rng, price, parts)
            assert sum(shares) == price
            assert len(shares) == parts and min(shares) >= Decimal("0.01")
    with pytest.raises(ValueError, match="one cent"):
        split(rng, Decimal("0.02"), 3)


def test_every_measured_unit_has_another_dimension() -> None:
    for unit, other in OTHER_DIMENSION.items():
        assert UNITS[unit].dimension != UNITS[other].dimension
