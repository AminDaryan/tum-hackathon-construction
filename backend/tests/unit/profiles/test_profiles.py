"""Domain profiles load, validate, and drive unit/currency lookups."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from app.core.errors import NotFoundError, ProfileError
from app.normalization.numbers import NumberReading, parse_number
from app.normalization.text import header_key
from app.profiles.currency import (
    VOCABULARY_FILE,
    CurrencyResolver,
    CurrencyVocabulary,
    default_vocabulary,
    load_vocabulary,
)
from app.profiles.loader import ProfileCatalog, load_profile
from app.profiles.units import UnitCatalog


def test_builtin_profiles_load(profile_catalog: ProfileCatalog) -> None:
    assert [p.profile_id for p in profile_catalog.list()] == ["boq", "generic"]


def test_unknown_profile(profile_catalog: ProfileCatalog) -> None:
    with pytest.raises(NotFoundError):
        profile_catalog.get("nope")


def test_boq_required_fields(boq_profile) -> None:
    assert [f.field_id for f in boq_profile.required_fields()] == [
        "item_code",
        "description",
        "quantity",
        "unit",
        "unit_price",
        "line_total",
    ]


@pytest.mark.parametrize(
    ("text", "unit_id"),
    [
        ("m²", "m2"),
        ("qm", "m2"),
        ("M3", "m3"),
        ("Stk", "pcs"),
        ("St.", "pcs"),
        ("No.", "pcs"),
        ("psch", "ls"),
        ("l.s.", "ls"),
        ("lfd. m", "m"),
        ("%", "pct"),
        ("Std", "h"),
    ],
)
def test_unit_aliases(boq_profile, text: str, unit_id: str) -> None:
    assert UnitCatalog.from_profile(boq_profile).resolve(text).unit_id == unit_id


@pytest.mark.parametrize("text", ["xyz", "p.a.", "", None])
def test_unknown_units_are_not_guessed(boq_profile, text) -> None:
    assert UnitCatalog.from_profile(boq_profile).resolve(text) is None


def test_currency_markers(boq_profile) -> None:
    resolver = CurrencyResolver.from_profile(boq_profile)
    assert resolver.find_in_text("EP [€]") == {"EUR"}
    assert resolver.find_in_text("Unit price (EUR)") == {"EUR"}
    assert resolver.find_in_text("Europe") == set()  # whole words only
    assert resolver.find_in_number_format("#,##0.00 [$€-407]") == "EUR"
    assert resolver.find_in_number_format("[$-407]dd.mm.yyyy") is None  # locale tag, not currency
    # "$" alone is ambiguous (USD, CAD, AUD, ...): only a locale tag decides it.
    assert resolver.find_in_number_format("$#,##0.00") is None
    assert resolver.find_in_number_format('"$"#,##0.00') is None
    assert resolver.find_in_number_format("[$$-409]#,##0.00") == "USD"
    assert resolver.find_in_number_format("[$$-C09]#,##0.00") == "AUD"
    assert resolver.find_in_number_format("[$¥-804]#,##0.00") == "CNY"
    assert resolver.find_in_number_format("[$¥-411]#,##0") == "JPY"
    assert resolver.find_in_number_format("0.00") is None


def test_invalid_profile_reports_file(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text("profile_id: bad\nname: Bad\nversion: 1\nfields: []\n", encoding="utf-8")
    with pytest.raises(ProfileError) as excinfo:
        load_profile(path)
    assert "bad.yaml" in excinfo.value.message


def test_conflicting_unit_alias_rejected(tmp_path: Path) -> None:
    from app.models.profile import UnitDefinition

    with pytest.raises(ProfileError):
        UnitCatalog(
            [
                UnitDefinition(unit_id="m", label="metre", dimension="length", aliases=["m"]),
                UnitDefinition(unit_id="min", label="minute", dimension="time", aliases=["M"]),
            ]
        )


# The table that was built into app/profiles/currency.py before it moved into data.
FORMER_BUILT_IN_ALIASES = {
    "€": "EUR",
    "eur": "EUR",
    "euro": "EUR",
    "euros": "EUR",
    "us$": "USD",
    "usd": "USD",
    "£": "GBP",
    "gbp": "GBP",
    "chf": "CHF",
    "fr.": "CHF",
    "jpy": "JPY",
    "cny": "CNY",
    "rmb": "CNY",
    "nzd": "NZD",
    "sgd": "SGD",
    "hkd": "HKD",
    "pln": "PLN",
    "zł": "PLN",
    "czk": "CZK",
    "kč": "CZK",
    "sek": "SEK",
    "nok": "NOK",
    "dkk": "DKK",
    "₺": "TRY",
    "cad": "CAD",
    "aud": "AUD",
}


class TestCurrencyVocabulary:
    def test_the_shipped_vocabulary_keeps_the_former_defaults(self) -> None:
        vocabulary = default_vocabulary()
        assert VOCABULARY_FILE.parent.name == "data"  # not a profile: never loaded as one
        assert vocabulary.aliases == FORMER_BUILT_IN_ALIASES
        assert vocabulary.symbols == ["us$", "€", "$", "£", "¥", "₺"]
        assert vocabulary.ambiguous_symbols == ["$", "¥", "r$"]
        assert len(vocabulary.locale_currencies) == 16
        assert vocabulary.number_format_symbols == ["€", "£", "₺"]

    def test_profile_aliases_add_and_override(self) -> None:
        resolver = CurrencyResolver({"Rs": "INR", "€": "XEU"})
        assert resolver.resolve_token("rs") == "INR"
        assert resolver.resolve_token("€") == "XEU"
        assert resolver.resolve_token("EUR") == "EUR"  # the rest of the default stays

    def test_recognition_follows_the_vocabulary_not_code(self) -> None:
        custom = CurrencyVocabulary(
            aliases={"₹": "INR", "inr": "INR"},
            symbols=["₹", "$"],
            ambiguous_symbols=["$"],
            locale_currencies={"409": "USD"},
            number_format_symbols=["₹"],
        )
        resolver = CurrencyResolver(vocabulary=custom)
        assert resolver.resolve_token("€") is None  # no built-in table behind the data
        assert resolver.find_in_text("EP [€]") == set()
        assert resolver.find_in_text("Rate [₹]") == {"INR"}
        assert resolver.find_in_number_format("₹ #,##0.00") == "INR"
        assert resolver.find_in_number_format("[$$-409]0.00") == "USD"
        assert parse_number("₹ 12.50", currencies=resolver) == NumberReading(
            Decimal("12.50"), "INR", False, "."
        )
        assert parse_number("$ 12.50", currencies=resolver).currency is None  # ambiguous
        assert parse_number("€ 12.50", currencies=resolver) is None  # not a marker here
        assert header_key("Preis [$]", resolver) == "preis"
        assert header_key("Preis [€]", resolver) == "preis"  # a bracketed unit, kept as text

    @pytest.mark.parametrize(
        ("text", "problem"),
        [
            ("aliases: {eur: Euro}", "Not ISO 4217 codes"),
            ("aliases: {eur: EUR, ' EUR ': EUR}", "distinct after normalization"),
            ("aliases: {eur: EUR}\nambiguous_symbols: [eur]", "must not be aliases"),
            ("aliases: {eur: EUR}\nnumber_format_symbols: [x]", "must be aliases"),
            ("aliases: {eur: EUR}\nsymbols: [x]", "aliases or ambiguous symbols"),
            ("aliases: {eur: EUR}\nlocale_currencies: {'0409': USD}", "without leading zeros"),
            ("aliases: {eur: EUR}\nsymbol: [x]", "Extra inputs"),
            ("- eur", "must contain a mapping"),
        ],
    )
    def test_invalid_vocabularies_are_rejected(
        self, tmp_path: Path, text: str, problem: str
    ) -> None:
        path = tmp_path / "currencies.yaml"
        path.write_text(text, encoding="utf-8")
        with pytest.raises(ProfileError) as excinfo:
            load_vocabulary(path)
        assert "currencies.yaml" in excinfo.value.message
        assert problem in f"{excinfo.value.message} {excinfo.value.details}"
