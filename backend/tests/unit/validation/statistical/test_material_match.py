"""Model-suggested matches of statistical.open_price_reference: the answer contract, the unit
rules and the check's model path. Every answer here is written by the test (a stand-in for
the local model); the bill texts are synthetic."""

from __future__ import annotations

import json
from dataclasses import replace
from decimal import Decimal
from typing import Any

import pytest

from app.models.issue import EvidenceClass, EvidenceKind, Severity
from app.models.material_answers import MaterialAnswer, MaterialAnswers
from app.validation.statistical import material_match as mm
from app.validation.statistical import open_price_reference as opr
from app.validation.statistical.open_price_reference import (
    MODEL_ABSTAINED,
    MODEL_COMPARED,
    MODEL_INVALID,
    MODEL_NOT_COMPARED,
    MODEL_NOT_PROCESSED,
    MODEL_REQUEST_FAILED,
    MODEL_RULE_ID,
    MODEL_SUGGESTED,
    ROWS_COMPARED,
    RULE_ID,
    OpenPriceReferenceDetector,
    model_prompt,
)
from app.validation.support.items import item_frame
from tests.support.builders import make_context
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    assert_well_formed,
    boq_dataset,
    run,
)

COLUMNS = [*BOQ_COLUMNS, ("Währung", "currency")]
MODEL = "stand-in-model"
CODES = frozenset(opr.BY_CODE)
REBAR = "Rippenstahl BSt 500 S, nur Lieferung frei Baustelle"
GLASS = "Dreischeiben-Wärmedämmglas, Format 1200 x 1500 mm, nur Lieferung"


def answer(
    code: str | None = "24106210",
    scope: str = "supply_only",
    quotes: tuple[str, ...] = ("Rippenstahl BSt 500 S",),
    attributes: tuple[tuple[str, str], ...] = (),
    reason: str = "The text names ribbed reinforcing steel bars, delivered only.",
    abstain: str | None = None,
    **extra: Any,
) -> str:
    return json.dumps(
        {
            "product_code": code,
            "abstain_reason": abstain,
            "scope": scope,
            "material_attributes": [{"name": n, "text": t} for n, t in attributes],
            "reason": reason,
            "evidence_quotes": list(quotes),
            **extra,
        }
    )


def item(code: str, text: str, qty: str, unit: str, price: str) -> list[str]:
    total = (Decimal(qty) * Decimal(price)).quantize(Decimal("0.01"))
    return [code, text, qty, unit, price, str(total), "EUR"]


def detect(boq_profile, rows, raws: dict[str, str], stored: bool = True):  # type: ignore[no-untyped-def]
    """Run the check with the stand-in's answers by item code ("request_failed" and "not_sent"
    are statuses, anything else is the raw answer)."""
    dataset = boq_dataset(boq_profile, rows, columns=COLUMNS)
    context = make_context(dataset, boq_profile)
    answers = {}
    for record in item_frame(context).records:
        if record.item_code not in raws:
            continue
        raw = raws[record.item_code]
        status = raw if raw in ("request_failed", "not_sent") else "answered"
        answers[mm.answer_key(MODEL, model_prompt(record))] = MaterialAnswer(
            table_id=record.table_id,
            row_id=record.row_id,
            item_code=record.item_code,
            status=status,
            raw=raw if status == "answered" else None,
        )
    material = MaterialAnswers(
        dataset_id=dataset.dataset_id,
        model=MODEL,
        prompt_version=mm.PROMPT_VERSION,
        status="completed",
        detail="stand-in answers",
        answers=answers,
    )
    context = replace(context, material_answers=material if stored else None)
    return run(OpenPriceReferenceDetector, dataset, boq_profile, context=context)


# ------------------------------------------------------------------------- answer contract
def test_a_valid_suggestion_and_an_explicit_abstention_are_read() -> None:
    proposal = mm.parse(answer(attributes=(("grade", "BSt 500 S"),)), REBAR, CODES)
    assert proposal.product_code == "24106210" and proposal.scope == "supply_only"
    assert proposal.attributes == (mm.Attribute("grade", "BSt 500 S"),)
    none = mm.parse(answer(code=None, abstain="no_catalogue_product", quotes=()), REBAR, CODES)
    assert none.product_code is None and none.abstain_reason == "no_catalogue_product"


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        ("{not json", "invalid_json"),
        ("[1, 2]", "invalid_json"),
        (answer(scope="installed"), "unknown_enum"),
        (answer(code=None, abstain="no idea", quotes=()), "unknown_enum"),
        (answer(reason="x" * 401), "field_length"),
        (answer(quotes=("y" * 201,)), "field_length"),
        (answer(code="99999999"), "unknown_product_code"),
        (answer(code=24106210), "unknown_product_code"),  # a number, not a catalogue code
        (answer(quotes=("Betonstahl B500B",)), "quote_not_in_text"),  # not in the text sent
        (answer(quotes=()), "quote_missing"),
        (answer(attributes=(("grade", "B500B"),)), "attribute_not_in_text"),
        (answer(attributes=(("colour", "S"),)), "unknown_enum"),
        (answer(unit_price="0.45"), "price_or_factor_in_output"),
        (answer(conversion_factor=1000), "price_or_factor_in_output"),
        (answer(inflation_index=1.1), "price_or_factor_in_output"),
        (answer(confidence=0.9), "unexpected_field"),
        (
            answer(reason="Reinforcing steel; it should cost about 450 EUR per tonne."),
            "price_or_factor_in_output",
        ),
        (
            answer(reason="Reinforcing steel bars, but the price looks too low."),
            "price_or_factor_in_output",
        ),
        (json.dumps({"product_code": None}), "missing_field"),
    ],
)
def test_an_answer_outside_the_contract_is_refused_with_its_reason(raw: str, code: str) -> None:
    with pytest.raises(mm.InvalidAnswer) as refused:
        mm.parse(raw, REBAR, CODES)
    assert refused.value.code == code


def test_factor_words_of_the_position_itself_may_be_quoted_in_the_reason() -> None:
    text = "Isolierglas 3-fach, nur Lieferung"
    proposal = mm.parse(
        answer(
            code="23122010", quotes=("Isolierglas 3-fach",), reason="Names 'Isolierglas 3-fach'."
        ),
        text,
        CODES,
    )
    assert proposal.product_code == "23122010"


# ------------------------------------------------------------------------------ unit rules
KG = opr.UNIT_FACTORS["KG"]
M2 = opr.UNIT_FACTORS["M2"]


def test_exact_unit_definitions_and_the_area_of_a_stated_size_convert() -> None:
    tonne = mm.conversion("KG", "t", KG, (), "kg")
    assert isinstance(tonne, mm.Conversion) and tonne.rule == "tonne_to_kilogram"
    assert tonne.factor == 1000
    for size in ("1200 x 1500 mm", "1,20 x 1,50 m", "120 cm x 150 cm"):
        piece = mm.conversion("M2", "pcs", M2, (mm.Attribute("size", size),), "m²")
        assert isinstance(piece, mm.Conversion) and piece.rule == "piece_area", size
        assert piece.factor == Decimal("1.8") and piece.inputs == size


def test_a_conversion_without_its_attribute_or_rule_is_refused() -> None:
    thickness = (mm.Attribute("thickness", "d = 24 mm"),)
    assert mm.conversion("M2", "pcs", M2, thickness, "m²") == "required_attribute_missing"
    three = (mm.Attribute("size", "1200 x 1500 x 24 mm"),)  # not an area
    assert mm.conversion("M2", "pcs", M2, three, "m²") == "attribute_unreadable"
    no_unit = (mm.Attribute("size", "1200 x 1500"),)
    assert mm.conversion("M2", "pcs", M2, no_unit, "m²") == "attribute_unreadable"
    # Wall area x thickness is the masonry volume, not the volume of the bricks: no rule.
    m3 = opr.UNIT_FACTORS["M3"]
    assert mm.conversion("M3", "m2", m3, thickness, "m³") == "unit_not_convertible"
    assert mm.conversion("KG", "m", KG, (), "kg") == "unit_not_convertible"


# ----------------------------------------------------------------------- the check's path
def test_a_supply_only_suggestion_below_the_reference_is_context_marked_as_the_models(
    boq_profile,
) -> None:
    found = detect(
        boq_profile,
        [item("1.1", REBAR, "12", "t", "300.00"), item("1.2", REBAR, "12", "t", "600.00")],
        {"1.1": answer(), "1.2": answer()},
    )
    [issue] = found.issues  # 0.300 EUR/kg is below 0.474; 0.600 is not
    assert issue.rule_id == MODEL_RULE_ID and issue.title.startswith("Model-suggested match:")
    assert issue.severity == Severity.LOW
    assert issue.evidence_class == EvidenceClass.NEEDS_EXTERNAL_CONTEXT
    assert issue.estimated_financial_impact is None
    suggestion, checks, comparison, source = issue.evidence
    assert suggestion.kind == EvidenceKind.NOTE and suggestion.data["origin"] == "model_suggestion"
    assert (
        suggestion.data["product_code"] == "24106210" and suggestion.data["scope"] == "supply_only"
    )
    assert suggestion.data["model"] == MODEL and suggestion.data["person_checked"] is False
    assert "Rippenstahl BSt 500 S" in suggestion.detail and suggestion.cells
    assert checks.kind == EvidenceKind.RULE and "not whether the match is right" in checks.label
    assert comparison.data["conversion_rule"] == "tonne_to_kilogram"
    assert comparison.data["reference_value"] == "0.474"
    assert comparison.data["position_value"] == "0.300"
    assert source.kind == EvidenceKind.REFERENCE and "Eurostat" in source.label
    assert "reject this finding" in (issue.suggested_action or "")
    assert found.coverage[MODEL_SUGGESTED] == 2 and found.coverage[MODEL_COMPARED] == 2
    assert any("not below the published value" in note for note in found.notes)
    assert ROWS_COMPARED not in found.coverage  # the keyword path compared nothing
    assert_well_formed(found.issues)


def test_a_price_per_piece_is_compared_per_m2_through_the_stated_size(boq_profile) -> None:
    # 90 EUR per 1.2 m x 1.5 m pane = 50.000 EUR/m², below the German 69.574 EUR/m².
    found = detect(
        boq_profile,
        [item("2.1", GLASS, "10", "pcs", "90.00")],
        {
            "2.1": answer(
                code="23122010",
                quotes=("Dreischeiben-Wärmedämmglas",),
                attributes=(("size", "1200 x 1500 mm"),),
                reason="Triple-pane insulating glass units, delivered only.",
            )
        },
    )
    [issue] = found.issues
    comparison = issue.evidence[2]
    assert comparison.data["conversion_rule"] == "piece_area"
    assert comparison.data["conversion_input"] == "1200 x 1500 mm"
    assert comparison.data["position_value"] == "50.000"
    assert "1.8 m²" in comparison.detail


def test_an_installed_suggestion_is_compared_with_the_material_value_as_a_floor(
    boq_profile,
) -> None:
    # Supplied and laid at 0.300 EUR/kg: less than the steel alone (0.474), so it is reported.
    laid = "Rippenstahl BSt 500 S liefern und verlegen"
    found = detect(
        boq_profile,
        [item("4.1", laid, "12", "t", "300.00")],
        {"4.1": answer(scope="supply_and_install")},
    )
    [issue] = found.issues
    suggestion, checks = issue.evidence[:2]
    assert issue.rule_id == MODEL_RULE_ID and suggestion.data["scope"] == "supply_and_install"
    assert "supplied and installed" in issue.explanation
    assert "is a floor" in checks.detail
    assert "nor installation" not in checks.detail
    assert found.coverage[MODEL_COMPARED] == 1


@pytest.mark.parametrize(
    ("text", "unit", "raw", "reason"),
    [
        (  # the client supplies the steel: the price does not buy the material
            "Rippenstahl BSt 500 S, bauseits gestellt, verlegen",
            "t",
            answer(scope="supply_and_install"),
            "scope_excluded_by_text",
        ),
        (  # the model says supply only, the text says it is laid
            "Rippenstahl BSt 500 S liefern und verlegen",
            "t",
            answer(),
            "scope_contradicts_text",
        ),
        (
            "Rippenstahl BSt 500 S aufnehmen und entsorgen",
            "t",
            answer(scope="removal_disposal"),
            "scope_removal_disposal",
        ),
        (REBAR, "t", answer(scope="unknown"), "scope_unknown"),
        (  # a price per piece needs the pane's size to become a price per m²
            "Dreischeiben-Wärmedämmglas, nur Lieferung",
            "pcs",
            answer(code="23122010", quotes=("Dreischeiben-Wärmedämmglas",)),
            "required_attribute_missing",
        ),
        (REBAR, "m", answer(), "unit_not_convertible"),
    ],
)
def test_a_suggestion_a_check_of_code_refuses_is_not_compared_and_says_why(
    boq_profile, text: str, unit: str, raw: str, reason: str
) -> None:
    found = detect(boq_profile, [item("3.1", text, "2", unit, "1.00")], {"3.1": raw})
    assert not found.issues
    assert found.coverage[MODEL_SUGGESTED] == 1 and found.coverage[MODEL_NOT_COMPARED] == 1
    assert MODEL_COMPARED not in found.coverage
    assert any(f"not compared: {reason.replace('_', ' ')}" in note for note in found.notes)


def test_no_published_value_means_no_comparison(boq_profile, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    data = opr.source_data()
    values = {k: v for k, v in data.values.items() if k != "24106210"}
    monkeypatch.setattr(opr, "source_data", lambda: opr.SourceData(data.meta, values))
    found = detect(boq_profile, [item("3.2", REBAR, "2", "t", "1.00")], {"3.2": answer()})
    assert not found.issues and found.coverage[MODEL_NOT_COMPARED] == 1
    assert any("no published value" in note for note in found.notes)


def test_abstentions_invalid_answers_and_rows_not_processed_are_counted_never_matched(
    boq_profile,
) -> None:
    # One text per row: the same text and unit is the same prompt, so the same stored answer.
    rows = [item(f"4.{n}", f"{REBAR}, Los {n}", "2", "t", "1.00") for n in range(1, 8)]
    found = detect(
        boq_profile,
        rows,
        {
            "4.1": answer(code=None, abstain="text_insufficient", quotes=()),
            "4.2": answer(code="99999999"),  # not in the catalogue
            "4.3": answer(quotes=("Betonstahl B500B",)),  # invented quote
            "4.4": answer(unit_price="0.20"),  # a price from the model
            "4.5": "{not json",
            "4.6": "request_failed",  # e.g. a timeout
            # 4.7: no answer stored
        },
    )
    assert not found.issues
    c = found.coverage
    assert c[MODEL_ABSTAINED] == 1 and c[MODEL_INVALID] == 4
    assert c[MODEL_REQUEST_FAILED] == 1 and c[MODEL_NOT_PROCESSED] == 1
    assert MODEL_SUGGESTED not in c and MODEL_COMPARED not in c
    notes = " ".join(found.notes)
    assert "1 text insufficient" in notes
    assert "unknown product code" in notes and "price or factor in output" in notes


def test_without_stored_answers_the_keywords_run_alone_and_the_rest_is_not_processed(
    boq_profile,
) -> None:
    found = detect(
        boq_profile,
        [
            item("5.1", "Betonstahl B500B liefern und verlegen", "12", "t", "300.00"),
            item("5.2", REBAR, "12", "t", "300.00"),
        ],
        {},
        stored=False,
    )
    [issue] = found.issues  # the keyword path, unchanged
    assert issue.rule_id == RULE_ID and not issue.title.startswith("Model")
    assert found.coverage[MODEL_NOT_PROCESSED] == 1
    assert any("not processed by a model" in note for note in found.notes)
