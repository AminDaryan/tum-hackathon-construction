"""Golden tables for the BoQ profile's wording rules (English and German).

These pin down what the profile's patterns mean, label by label, so a pattern edit that turns
"Übertrag" into a subtotal or "Gesamtsumme inkl. MwSt." into a net total fails loudly. Row
kinds here are the label match only: normalization still requires the value pattern of the
decision table (a row with a quantity is an item whatever its text).
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core import patterns
from app.models.dataset import RowKind
from app.models.profile import DomainProfile, FieldRole, TotalsTextSource
from app.models.values import ValueMarker
from app.profiles.units import UnitCatalog

S, G, GT, T, A, CF, SEC = (
    RowKind.SUBTOTAL,
    RowKind.GROSS_TOTAL,
    RowKind.GRAND_TOTAL,
    RowKind.TAX,
    RowKind.ADJUSTMENT,
    RowKind.CARRY_FORWARD,
    RowKind.SECTION,
)


@pytest.mark.parametrize(
    ("label", "kind", "code"),
    [
        # Subtotals, with the code of the section they close when the wording names one.
        ("Summe Titel 01", S, "01"),
        ("Summe 01.02", S, "01.02"),
        ("Titelsumme 02", S, "02"),
        ("Summe Los 1", S, "1"),
        ("Zwischensumme", S, None),
        ("Subtotal", S, None),
        ("Sub-total Section 3", S, "3"),
        ("Total Bill No. 2", S, "2"),
        ("Total", S, None),
        # Running totals carried between pages are never scope totals.
        ("Total carried to summary", CF, None),
        ("Carried forward", CF, None),
        ("Brought forward", CF, None),
        ("Übertrag", CF, None),
        ("Übertrag von Seite 3", CF, None),
        ("Seitensumme", CF, None),
        # Net grand totals.
        ("Gesamtsumme", GT, None),
        ("Gesamtsumme netto", GT, None),
        ("Angebotssumme", GT, None),
        ("Nettosumme", GT, None),
        ("Nettosumme (ohne MwSt.)", GT, None),
        ("Grand Total", GT, None),
        ("Gesamt", GT, None),
        ("Gesamt:", GT, None),
        ("Total (excl. VAT)", GT, None),
        ("Total excluding VAT", GT, None),
        # Gross wording wins over grand-total wording.
        ("Gesamtsumme inkl. MwSt.", G, None),
        ("Bruttosumme", G, None),
        ("Total incl. VAT", G, None),
        ("Gesamtbetrag brutto", G, None),
        # Tax and adjustments.
        ("MwSt. 19 %", T, None),
        ("zzgl. 19% MwSt.", T, None),
        ("VAT 20%", T, None),
        ("Umsatzsteuer 19 %", T, None),
        ("Nachlass 3 %", A, None),
        ("Discount 5%", A, None),
        ("Skonto 2 %", A, None),
        ("Rabatt", A, None),
    ],
)
def test_total_wording(boq_profile, label: str, kind: RowKind, code: str | None) -> None:
    match = boq_profile.row_classification.match_label(label)
    assert match is not None, label
    assert (match.kind, match.code) == (kind, code)


@pytest.mark.parametrize(
    ("label", "code", "level"),
    [
        ("Los 2 Rohbau", "2", 1),
        ("Bill No. 3 Substructure", "3", 1),
        ("Titel 01 Erdarbeiten", "01", 2),
        ("Section 2: Concrete", "2", 2),
        ("Gewerk Maurerarbeiten", None, 2),
        ("Abschnitt 3", "3", 2),
    ],
)
def test_section_wording(boq_profile, label: str, code: str | None, level: int) -> None:
    match = boq_profile.row_classification.match_label(label)
    assert match is not None and match.kind is SEC
    assert (match.code, match.level) == (code, level)


@pytest.mark.parametrize("label", ["Collection", "Summary", "Zusammenstellung"])
def test_summary_block_headings(boq_profile, label: str) -> None:
    match = boq_profile.row_classification.match_label(label)
    assert match is not None and match.kind is None and match.starts_summary_block


@pytest.mark.parametrize(
    "label",
    [
        # Item descriptions that merely contain total-like words.
        "Concrete in foundations",
        "Total station survey",
        "Total area to be painted",
        "Total height 3m scaffold",
        "Bodenplatte, Summe der Bewehrung nach Statik",
        "Gesamtes Gebäude reinigen",
        "Contingency 10%",
        # A bare code and title: a section only by the code-prefix rule, not by wording.
        "01 Erdarbeiten",
        "",
        "   ",
    ],
)
def test_descriptions_are_not_totals(boq_profile, label: str) -> None:
    assert boq_profile.row_classification.match_label(label) is None


@pytest.mark.parametrize(
    ("texts", "rule_id", "counts"),
    [
        ({"label": ["Bedarfsposition mit GB"]}, "contingency_with_total", True),
        ({"label": ["Bedarfsposition mGB: Wasserhaltung"]}, "contingency_with_total", True),
        ({"category": ["Bedarfsposition mit GB"]}, "contingency_with_total", True),
        ({"label": ["Bedarfsposition ohne GB"]}, "contingency_without_total", False),
        ({"label": ["Eventualposition o. GB"]}, "contingency_without_total", False),
        ({"category": ["Bedarfsposition ohne GB"]}, "contingency_without_total", False),
        ({"label": ["Eventualposition: Wasserhaltung"]}, "contingency_unspecified", None),
        (
            {"continuation_text": ["Position wird nur auf Anordnung ausgeführt"]},
            "contingency_unspecified",
            None,
        ),
        ({"label": ["Alternativposition: Holzfenster"]}, "alternative_item", False),
        ({"label": ["Wahlposition"]}, "alternative_item", False),
        ({"label": ["Alternativ zu Pos. 01.02.0030"]}, "alternative_item", False),
        ({"label": ["Alternative: timber windows instead of PVC"]}, "alternative_item", False),
        ({"label": ["nur Einheitspreis"]}, "rate_only", False),
        ({"label": ["Rate only"]}, "rate_only", False),
        ({"label": ["Provisional sum (not included in total)"]}, "excluded_from_total", False),
        ({"label": ["Excluded from total"]}, "excluded_from_total", False),
        ({"label": ["Optional item: extra coat"]}, "optional_item", False),
        ({"category": ["Grundposition"]}, "type_base", True),
        ({"category": ["G"]}, "type_base", True),
        ({"category": ["BmGB"]}, "type_contingency_with_total", True),
        ({"category": ["BoGB"]}, "type_contingency_without_total", False),
        ({"category": ["Bedarfsposition"]}, "contingency_unspecified", None),
        ({"category": ["E"]}, "type_contingency", None),
        ({"category": ["Alternativposition"]}, "alternative_item", False),
        ({"category": ["A"]}, "type_alternative", False),
    ],
)
def test_totals_rules(boq_profile, texts, rule_id: str, counts: bool | None) -> None:
    rule = boq_profile.row_classification.match_totals(texts)
    assert rule is not None, texts
    assert (rule.rule_id, rule.counts_toward_totals) == (rule_id, counts)


@pytest.mark.parametrize(
    "texts",
    [
        {"label": ["Concrete C30/37 in foundations"]},
        {"label": ["Alternative fuel supply"]},
        {"label": ["Contingency 10%"]},  # counts by default
        {"label": ["Normalposition"]},  # the GAEB kinds are read in the item type column only
        {"category": ["Freie Menge"]},  # a GAEB kind that says nothing about the total
        {"category": ["Schwerpunktposition"]},
        {"amount_text": ["(1.234,00)"]},
    ],
)
def test_ordinary_items_match_no_totals_rule(boq_profile, texts) -> None:
    assert boq_profile.row_classification.match_totals(texts) is None


# The item kinds the GAEB import writes (app.ingestion.gaeb.flatten.item_type), alone and
# joined by ", " in its order (contingency, alternative, then the other flags), as a Positionsart
# column of a spreadsheet export carries them.
@pytest.mark.parametrize(
    ("kinds", "rule_id", "counts"),
    [
        # Alone: these count ...
        ("Normalposition", "gaeb_counted", True),
        ("Grundposition", "type_base", True),
        ("Pauschalposition", "gaeb_counted", True),
        ("Bedarfsposition mit GB", "contingency_with_total", True),
        ("Zuschlagsposition", "gaeb_counted", True),
        # ... these do not ...
        ("Bedarfsposition ohne GB", "contingency_without_total", False),
        ("Wahlposition", "gaeb_not_counted", False),
        ("entfällt", "gaeb_not_counted", False),
        ("entfaellt", "gaeb_not_counted", False),
        # ... and these stay open: hourly work, and an item of an alternative group, which the
        # GAEB import counts toward its own group only.
        ("Stundenlohnarbeiten", "gaeb_hourly_work", None),
        ("Wahlposition (Wahlgruppe)", "gaeb_alternative_group", None),
        # Joined: a kind that takes the item out of the total wins ...
        ("Bedarfsposition ohne GB, Pauschalposition", "contingency_without_total", False),
        ("Bedarfsposition ohne GB, Grundposition", "contingency_without_total", False),
        ("Bedarfsposition ohne GB, Stundenlohnarbeiten", "contingency_without_total", False),
        ("Bedarfsposition mit GB, Wahlposition", "gaeb_not_counted", False),
        ("Bedarfsposition mit GB, entfällt", "gaeb_not_counted", False),
        ("Wahlposition, Pauschalposition", "gaeb_not_counted", False),
        ("Wahlposition, Stundenlohnarbeiten", "gaeb_not_counted", False),
        ("Grundposition, entfällt", "gaeb_not_counted", False),
        ("Pauschalposition, Stundenlohnarbeiten, entfällt", "gaeb_not_counted", False),
        # ... an alternative group stays open whatever else is said ...
        ("Bedarfsposition ohne GB, Wahlposition (Wahlgruppe)", "gaeb_alternative_group", None),
        # ... "mit GB" says the amount is in the total, also for hourly work ...
        ("Bedarfsposition mit GB, Grundposition", "contingency_with_total", True),
        ("Bedarfsposition mit GB, Pauschalposition", "contingency_with_total", True),
        ("Bedarfsposition mit GB, Stundenlohnarbeiten", "contingency_with_total", True),
        # ... otherwise hourly work stays open ...
        ("Grundposition, Stundenlohnarbeiten", "gaeb_hourly_work", None),
        ("Pauschalposition, Stundenlohnarbeiten", "gaeb_hourly_work", None),
        ("Stundenlohnarbeiten, Freie Menge", "gaeb_hourly_work", None),
        # ... and the kinds that count, count.
        ("Grundposition, Pauschalposition", "gaeb_counted", True),
        ("Grundposition, Freie Menge", "gaeb_counted", True),
        ("Pauschalposition, Schwerpunktposition", "gaeb_counted", True),
        ("Normalposition, Freie Menge", "gaeb_counted", True),
    ],
)
def test_gaeb_item_kinds(
    boq_profile: DomainProfile, kinds: str, rule_id: str, counts: bool | None
) -> None:
    rule = boq_profile.row_classification.match_totals({"category": [kinds]})
    assert rule is not None, kinds
    assert (rule.rule_id, rule.counts_toward_totals) == (rule_id, counts)


@pytest.mark.parametrize(
    ("texts", "rule_id", "counts"),
    [
        # The column's exclusion wins over the item text ...
        (
            {"label": ["Bedarfsposition mit GB: Wasserhaltung"], "category": ["entfällt"]},
            "gaeb_not_counted",
            False,
        ),
        # ... but a counting kind does not overrule wording that takes the item out or leaves
        # it open: the kind only says that the file did not exclude it.
        (
            {"label": ["Bodenaustausch, nur EP"], "category": ["Normalposition"]},
            "rate_only",
            False,
        ),
        (
            {
                "category": ["Normalposition"],
                "continuation_text": ["Ausführung nur auf Anordnung des AG"],
            },
            "contingency_unspecified",
            None,
        ),
    ],
)
def test_gaeb_item_kinds_next_to_wording(
    boq_profile: DomainProfile,
    texts: dict[TotalsTextSource, list[str]],
    rule_id: str,
    counts: bool | None,
) -> None:
    rule = boq_profile.row_classification.match_totals(texts)
    assert rule is not None, texts
    assert (rule.rule_id, rule.counts_toward_totals) == (rule_id, counts)


@pytest.mark.parametrize(
    ("token", "role", "marker"),
    [
        ("Incl.", FieldRole.MONETARY, ValueMarker.INCLUDED_ELSEWHERE),
        (" incl ", FieldRole.MONETARY, ValueMarker.INCLUDED_ELSEWHERE),
        ("enthalten", FieldRole.MONETARY, ValueMarker.INCLUDED_ELSEWHERE),
        ("Nil", FieldRole.MONETARY, ValueMarker.NIL),
        ("-", FieldRole.MONETARY, ValueMarker.NIL),
        ("-,--", FieldRole.MONETARY, ValueMarker.NIL),
        ("entfällt", FieldRole.MONETARY, ValueMarker.NOT_APPLICABLE),
        ("N/A", FieldRole.QUANTITY, ValueMarker.NOT_APPLICABLE),
        ("By others", FieldRole.MONETARY, ValueMarker.BY_OTHERS),
        ("bauseits", FieldRole.MONETARY, ValueMarker.BY_OTHERS),
        ("nur EP", FieldRole.MONETARY, ValueMarker.RATE_ONLY),
        ("psch", FieldRole.QUANTITY, ValueMarker.LUMP_SUM),
        ("LS", FieldRole.QUANTITY, ValueMarker.LUMP_SUM),
    ],
)
def test_value_markers(boq_profile, token: str, role: FieldRole, marker: ValueMarker) -> None:
    assert boq_profile.match_marker(token, role) is marker


@pytest.mark.parametrize(
    ("token", "role"),
    [
        ("Rate only", FieldRole.QUANTITY),  # rate-only applies to monetary fields
        ("psch", FieldRole.MONETARY),  # a lump-sum token is a quantity, not an amount
        ("0", FieldRole.MONETARY),
        ("12,50", FieldRole.MONETARY),
        ("Incl. in item 3", FieldRole.MONETARY),  # tokens match whole, never by substring
        ("x" * 41, FieldRole.MONETARY),
    ],
)
def test_non_markers(boq_profile, token: str, role: FieldRole) -> None:
    assert boq_profile.match_marker(token, role) is None


@pytest.mark.parametrize(
    ("text", "unit_id", "multiplier"),
    [
        ("100 St", "pcs", Decimal(100)),
        ("1000 kg", "kg", Decimal(1000)),
        ("10 m²", "m2", Decimal(10)),
        ("m² · Wo", "m2wk", None),
        ("m2 × Wo", "m2wk", None),
        ("Stk", "pcs", None),
    ],
)
def test_unit_lookup_with_multiplier(
    boq_profile, text: str, unit_id: str, multiplier: Decimal | None
) -> None:
    found = UnitCatalog.from_profile(boq_profile).lookup(text)
    assert found is not None, text
    assert (found.unit.unit_id, found.multiplier) == (unit_id, multiplier)


@pytest.mark.parametrize("text", ["0 St", "100", "100 xyz", "1,5,5 m", "St 100"])
def test_unit_lookup_refuses_guesses(boq_profile, text: str) -> None:
    found = UnitCatalog.from_profile(boq_profile).lookup(text)
    assert found is None or found.multiplier is None


# deterministic.line_total (B2.2): a lump-sum position keeps its stated amount when quantity ×
# unit price disagrees with it. The unit says so, or the item type as the GAEB import writes it
# (also joined with other types, as Positionsart columns of spreadsheet exports do).
LINE_TOTAL = "deterministic.line_total"


@pytest.mark.parametrize(
    ("item_type", "lump_sum"),
    [
        ("Pauschalposition", True),
        ("Grundposition, Pauschalposition", True),
        ("Pauschalposition, Bedarfsposition mit GB", True),
        ("PAUSCHALPOSITION", True),
        ("Normalposition", False),
        ("Grundposition", False),
        ("Pauschal", False),
        ("Pauschalpositionen", False),
    ],
)
def test_lump_sum_item_types(boq_profile, item_type: str, lump_sum: bool) -> None:
    rule = boq_profile.detector_defaults[LINE_TOTAL]["lump_sums"]
    assert rule["text_field"] == "item_type"
    assert (patterns.search(rule["text_pattern"], item_type) is not None) is lump_sum


@pytest.mark.parametrize(
    ("unit", "lump_sum"),
    [("psch", True), ("pauschal", True), ("LS", True), ("St", False), ("m3", False)],
)
def test_lump_sum_units(boq_profile, unit: str, lump_sum: bool) -> None:
    rule = boq_profile.detector_defaults[LINE_TOTAL]["lump_sums"]
    found = UnitCatalog.from_profile(boq_profile).lookup(unit)
    assert found is not None, unit
    assert (found.unit.dimension in rule["unit_dimensions"]) is lump_sum


def test_the_unit_price_prevails_in_the_boq_profile(boq_profile) -> None:
    settings = boq_profile.detector_defaults[LINE_TOTAL]
    assert settings["prevailing_value"] == "unit_price"
    assert settings["prevailing_rule"].startswith("VOB/A §16c (2) Nr. 1: ")
    # The GAEB import's warning for an X84 or D84 bid, which does not say which items are lump
    # sums.
    assert settings["lump_sums"]["undetermined_warnings"] == ["gaeb_bid_without_tender"]


def test_unit_price_components_are_mapped_by_a_reviewer_only(boq_profile) -> None:
    # deterministic.unit_price_components (B2.4) checks what a reviewer maps: no header maps a
    # component, and the components the GAEB import does not read yet (UPComp1..6 in GAEB XML,
    # record 30 in GAEB 90) are only named.
    for k in range(1, 7):
        field = boq_profile.field(f"unit_price_component_{k}")
        assert field is not None and field.match_headers is False
    settings = boq_profile.detector_defaults["deterministic.unit_price_components"]
    assert settings == {
        "not_imported_warning": "gaeb_elements_not_shown",
        "not_imported_elements": [
            *(f"UPComp{k}" for k in range(1, 7)),
            "Satzart 30 (Einheitspreisanteile)",
        ],
    }


# --------------------------------------------------------------------------- duplicates (B2.7)
DUPLICATES = "deterministic.exact_duplicates"


def test_duplicates_are_compared_within_a_titel_without_oz_and_gaeb_id(
    boq_profile: DomainProfile,
) -> None:
    settings = boq_profile.detector_defaults[DUPLICATES]
    assert settings["ignore_fields"] == ["item_code"]
    assert settings["ignore_columns"] == ["GAEB-ID"]  # the column the GAEB import writes
    assert settings["scope"] == "section"
    assert settings["required_fields"] == ["description"]  # a bid without texts
    assert settings["relative_wording_fields"] == ["description", "long_description"]


@pytest.mark.parametrize(
    "text",
    [
        "Wie vor, jedoch 30 cm",
        "wie vorher, aber verzinkt",
        "Mauerwerk wie vorstehend, jedoch d = 36,5 cm",
        "wie zuvor beschrieben",
        "Wie oben",
        "dto., jedoch DN 150",
        "dito",
        "desgl. 2. Lage",
        "Desgleichen, jedoch in Sichtbeton",
        "Zulage zu vorbeschriebener Position für Ecken",
        "Vorbeschriebene Leistung, jedoch beidseitig",
        "Zulage zur vorstehenden Position",
        "vorgenannte Ausführung, jedoch im Bestand",
        "Leistung wie oben beschrieben",
        "zuvor genannte Leistung",
        "Ausführung wie vorher beschriebenen",
        "As before but 300 mm thick",
        "as above",
        "as previous item, but in brickwork",
        "Ditto",
        "Described above, but painted",
        "as specified above",
    ],
)
def test_relative_wording(boq_profile: DomainProfile, text: str) -> None:
    pattern = boq_profile.detector_defaults[DUPLICATES]["relative_wording_pattern"]
    assert patterns.search(pattern, text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "Aushub Baugrube",
        "Wie Position 03.02.0014, jedoch 30 cm",  # names its position: compared as written
        "Anschluss wie vorhanden herstellen",
        "Oberfläche wie vorgefunden wiederherstellen",
        "Vorhaltung der Baustelleneinrichtung",
        "vorhandene Leitungen sichern",
        "Vorderkante Bordstein",
        "Vorsatzschale aus Klinker",
        "Vorbehandlung des Untergrunds",
        "Dorfstraße, Fahrbahn",
        "Wiederherstellen der Oberfläche",
        "Remove topsoil before backfilling",
        "above ground drainage",
        "previously excavated material",
    ],
)
def test_not_relative_wording(boq_profile: DomainProfile, text: str) -> None:
    pattern = boq_profile.detector_defaults[DUPLICATES]["relative_wording_pattern"]
    assert patterns.search(pattern, text) is None
