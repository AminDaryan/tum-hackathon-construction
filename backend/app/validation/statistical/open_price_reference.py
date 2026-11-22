"""Unit prices below a published material value (``statistical.open_price_reference``).

Context from open data, not a price the position should have. No open, reusable source
publishes German installed-work unit prices (issue #23: OpenConstructionERP's catalogues,
Destatis and Eurostat indices, BKI and STLB-Bau, which are licensed). The one open source of
German *price levels* found is Eurostat PRODCOM (dataset DS-059367): the value and quantity of
sold production per 8-digit product code and year, whose ratio is the average factory-gate
value of that product. The values are in ``data/prodcom_sold_production.json``, written by
``tools/price_references/fetch_prodcom.py`` from the public API, with the reference period, the
dataset's update time and the retrieval date.

A priced item row is compared only when all of these hold, and counted under the reason
otherwise (never passed silently):

* its text names exactly one material of :data:`REFERENCES` (``rows_without_reference``,
  ``rows_ambiguous_reference``), and does not describe removal, disposal, a surcharge or
  material supplied by others (``rows_scope_excluded``);
* its unit is the source's quantity unit, or a tonne for a kilogram (``rows_unit_mismatch``):
  no density, thickness or other conversion is made;
* its currency is marked as EUR (``rows_currency_not_eur``);
* the source publishes a value: the German one, else the EU-27 one, which is shown as the EU-27
  average and not adjusted to Germany (``rows_reference_withheld`` when both are confidential).

A finding is reported only when the unit price per source unit is *below* the reference: the
position, supplied or installed, costs less than the average factory-gate value of its material
alone. That can be legitimate (a cheaper grade or size under the same code, a large contract, a
different date or region), so every finding is ``needs_external_context`` of low severity, with
no amount at stake, and says what the average covers. The reference period is a past year
(2025 for the shipped data); no index or inflation factor is applied.

**Model-suggested matches.** A priced row the keywords cannot match (none, or more than one)
is matched by the local language model's stored answer when there is one
(``ValidationContext.material_answers``, written only when a run asks for it, see
:mod:`app.services.material_matches`; no check calls a model). The answer is a suggestion
(:mod:`~app.validation.statistical.material_match`): it is parsed and verified again here, and
the row is compared only when the code is in the catalogue, the quotes and attributes are in the
text, the scope buys the material (supply only, or supply and install: the factory-gate value
of the material alone is a floor for either, as for keyword matches; removal, disposal, an
unknown scope and text naming material supplied by others are not compared), the reference has
a published value,
the unit converts by a rule of code (the exact units above, or a price per piece of an m²
product with a stated size) and the currency is EUR. Every outcome is counted under a
``model_*`` key, and every suggestion not compared or not below is listed in the notes, so a
suggestion is never dropped silently and a row the model did not process is never counted as
matched. Its finding (rule ``model_matched_below_published_material_value``) has the same
class and severity, says in its title and evidence that the match is the model's suggestion,
and is rejected by the reviewer like any finding.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any, ClassVar

from app.models.dataset import Row, Table
from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, Severity, ValidationIssue
from app.models.material_answers import MaterialAnswers
from app.models.values import DataType
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.deterministic._support import fmt
from app.validation.statistical import material_match as mm
from app.validation.support.items import ItemRecord, item_frame, unit_price_applicability

RULE_ID = "below_published_material_value"
MODEL_RULE_ID = "model_matched_below_published_material_value"
# The model's scopes that buy the material, so that its value is a floor (mm.scope_failure).
_SCOPE_WORDS = {"supply_only": "supply only", "supply_and_install": "supplied and installed"}
CATEGORY = "price_reference"
DATA_FILE = Path(__file__).resolve().parent / "data" / "prodcom_sold_production.json"

ROWS_COMPARED = "rows_compared"
ROWS_NOT_PRICED = "rows_not_priced"
ROWS_WITHOUT_REFERENCE = "rows_without_reference"
ROWS_AMBIGUOUS = "rows_ambiguous_reference"
ROWS_SCOPE_EXCLUDED = "rows_scope_excluded"
ROWS_UNIT_MISMATCH = "rows_unit_mismatch"
ROWS_CURRENCY = "rows_currency_not_eur"
ROWS_WITHHELD = "rows_reference_withheld"
# Rows the keywords could not match, by what the model's stored answer gave.
MODEL_NOT_PROCESSED = "model_rows_not_processed"  # no answer: no model, not sent, other text
MODEL_REQUEST_FAILED = "model_rows_request_failed"
MODEL_INVALID = "model_rows_invalid_output"
MODEL_ABSTAINED = "model_rows_abstained"
MODEL_SUGGESTED = "model_rows_suggested"  # a valid suggestion of a product code
MODEL_NOT_COMPARED = "model_rows_not_compared"  # suggested, but a check of code refused it
MODEL_COMPARED = "model_rows_compared"
MAX_NOTES = 100  # suggestions listed one by one in the notes

# The bill's unit per source quantity unit: how many source units one bill unit holds.
# Only exact definitions (1 t = 1000 kg); never a density or a thickness.
UNIT_FACTORS: dict[str, dict[str, Decimal]] = {
    "KG": {"kg": Decimal(1), "t": Decimal(1000)},
    "M2": {"m2": Decimal(1)},
    "M3": {"m3": Decimal(1)},
}
SOURCE_UNIT_LABELS = {"KG": "kg", "M2": "m²", "M3": "m³"}

# Removal, disposal, surcharges and material supplied by others: the price does not buy the
# material, so its value says nothing about the position.
_SCOPE_EXCLUDED = re.compile(
    r"ausbau|abbau|abbruch|abbrech|demontage|entsorg|rückbau|rueckbau|zulage|bauseits|"
    r"beigestellt|ohne material|nur montage|nur einbau|wiederverwend|"
    r"\bremov|demoli|dispos|supplied by others|labour only|labor only"
)
_LONG_TEXT_CHARS = 300


@dataclass(frozen=True, slots=True)
class Reference:
    """A PRODCOM product code and the texts that name it in a bill (casefolded, so ``ß`` is
    written ``ss``)."""

    code: str
    material: str
    pattern: re.Pattern[str]
    exclude: re.Pattern[str] | None = None


def _re(text: str) -> re.Pattern[str]:
    return re.compile(text)


REFERENCES: tuple[Reference, ...] = (
    Reference(
        "24106210",
        "hot-rolled concrete reinforcing bars",
        _re(
            r"betonstahl|bewehrungsstahl|stabstahl|\bb ?500 ?[ab]?\b|reinforc\w* bars?|\brebars?\b"
        ),
        _re(r"matte|\bmesh|\bfabric|korb|schraub|kupplung|anschluss|coupler"),
    ),
    Reference(
        "24107130",
        "hot-rolled H-sections (web ≥ 80 mm)",
        _re(r"\bhe ?[abm] ?\d{3}\b|\bipb ?\d{3}\b|\bhd ?\d{3}\b"),
    ),
    Reference(
        "24107120",
        "hot-rolled I-sections (web ≥ 80 mm)",
        _re(r"\bip[en] ?(8\d|9\d|\d{3})\b"),
    ),
    Reference(
        "24107110",
        "hot-rolled U-sections (web ≥ 80 mm)",
        _re(r"\bup[enn] ?(8\d|9\d|\d{3})\b"),
    ),
    Reference(
        "23122010",
        "multiple-walled insulating glass units",
        _re(
            r"isolierglas|mehrscheiben|isolierverglasung|\b[23]-?fach-?(isolier)?verglasung|"
            r"insulating glass|double[- ]glaz|triple[- ]glaz"
        ),
    ),
    Reference(
        "23121230",
        "toughened (tempered) safety glass",
        _re(r"\besg\b|einscheibensicherheitsglas|toughened|tempered glass"),
    ),
    Reference(
        "23121270",
        "laminated safety glass",
        _re(r"\bvsg\b|verbundsicherheitsglas|laminated (safety )?glass"),
    ),
    Reference(
        "23621050",
        "paper-faced plasterboard",
        _re(r"gipskarton|gips-?platte|gipsbauplatte|plasterboard|gypsum board"),
        _re(r"gipsfaser|fermacell|fibre|fiber"),
    ),
    Reference(
        "23321110",
        "clay building bricks",
        _re(r"mauerziegel|hochlochziegel|vollziegel|klinker|clay bricks?"),
    ),
    Reference(
        "23991255",
        "bitumen membranes in rolls",
        _re(
            r"bitumen[- ]?(schweiss|dach|dichtungs)?bahn|schweissbahn|bitumen membrane|roofing felt"
        ),
    ),
    Reference(
        "22241119",
        "PVC floor coverings in rolls or tiles",
        _re(
            r"pvc[- ]?(boden)?belag|pvc[- ]?(design)?boden|vinyl[- ]?(boden|belag)|"
            r"pvc floor|vinyl floor"
        ),
        _re(r"sockel|skirting|kleber|adhesive"),
    ),
)
BY_CODE = {r.code: r for r in REFERENCES}
CATALOGUE = tuple((r.code, r.material) for r in REFERENCES)  # what the model may choose from


def rule_matches(record: ItemRecord) -> tuple[str, list[Reference]]:
    """The text the keywords read (casefolded) and the references it names."""
    text = (
        f"{record.description or ''} {(record.long_description or '')[:_LONG_TEXT_CHARS]}"
    ).casefold()
    return text, [
        r
        for r in REFERENCES
        if r.pattern.search(text) and not (r.exclude and r.exclude.search(text))
    ]


def needs_model(record: ItemRecord) -> bool:
    """A priced row the keywords match to no reference or to several: the model's to suggest."""
    price = record.unit_price_per_base_unit
    if record.counts_toward_totals is False or price is None or price <= 0:
        return False
    return record.unit_id is not None and len(rule_matches(record)[1]) != 1


def model_prompt(record: ItemRecord) -> str:
    return mm.prompt(CATALOGUE, record.description, record.long_description, record.unit_id)


@dataclass(frozen=True, slots=True)
class SourceValue:
    """The published value of one product code: ``area`` is ``DE`` or ``EU27_2020``."""

    code: str
    label: str
    area: str
    value: Decimal  # thousands are not involved: PRODVAL is in euro
    quantity: Decimal
    unit: str  # PRODCOM quantity unit (KG, M2, M3)
    flags: str  # the value and quantity flags as published, "" when none

    @property
    def unit_value(self) -> Decimal:
        return self.value / self.quantity


@dataclass(frozen=True, slots=True)
class SourceData:
    meta: dict[str, str]
    values: dict[str, SourceValue]  # code -> the value shown (German, else EU-27)


@cache
def source_data(path: Path = DATA_FILE) -> SourceData:
    raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    values: dict[str, SourceValue] = {}
    for code, entry in raw["products"].items():
        for area in ("DE", "EU27_2020"):
            cell = entry.get(area) or {}
            value, quantity = cell.get("PRODVAL"), cell.get("PRODQNT")
            if not isinstance(value, int | float) or not isinstance(quantity, int | float):
                continue
            if value <= 0 or quantity <= 0:
                continue
            flags = " ".join(f for f in (cell.get("PVALFLAG"), cell.get("PQNTFLAG")) if f)
            values[code] = SourceValue(
                code,
                entry["label"],
                area,
                Decimal(value),
                Decimal(quantity),
                cell["QNTUNIT"],
                flags,
            )
            break
    meta = {k: str(v) for k, v in raw.items() if k != "products"}
    return SourceData(meta, values)


class OpenPriceReferenceConfig(DetectorConfig):
    pass


class OpenPriceReferenceDetector(Detector[OpenPriceReferenceConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="statistical.open_price_reference",
        name="Unit price below a published material value",
        version="1.1.0",
        category=DetectorCategory.STATISTICAL,
        description=(
            "Compares positions that name one material (reinforcing bars, steel sections, "
            "glass, plasterboard, clay bricks, bitumen membranes, PVC flooring) in that "
            "material's own unit with its average factory-gate value in Eurostat PRODCOM "
            "(German, else EU-27, 2025), and reports positions priced below the material "
            "alone, as context for review."
        ),
        required_fields=("unit_price", "unit"),
        optional_fields=("description", "long_description", "currency"),
        supported_data_types=(DataType.NUMBER, DataType.TEXT),
        applicability="Tables that map a unit price and a unit (priced bills of quantities).",
        evidence_classes=(EvidenceClass.NEEDS_EXTERNAL_CONTEXT,),
        issue_categories=(CATEGORY,),
        limitations=(
            "Not what a position should cost: no open source publishes German installed-work "
            "prices. The reference is the material's factory-gate value only (no delivery, "
            "processing, labour, plant, overheads or profit).",
            "An annual national average over every grade, size and customer of the product "
            "code; a lower price can be legitimate.",
            "The reference year is past (2025) and is not indexed to the bill's date.",
            "Where German figures are confidential the EU-27 average is shown, not adjusted "
            "to Germany; Eurostat rounds those totals.",
            "Matches a short list of materials by keywords, only in the source's unit; every "
            "other row is counted as not compared.",
            "Rows the keywords cannot match use the local model's stored suggestion when a run "
            "asked for one: a suggestion checked by code for structure and source, not for "
            "being right; it is compared only when its scope buys the material (as a floor) "
            "and a unit rule of code applies.",
        ),
        references=(
            "Eurostat, Sold production, exports and imports by PRODCOM List (CPA 2.2), DS-059367",
            "Destatis, Qualitätsbericht Produktionserhebungen 2026 (Produktionswert: "
            "Verkaufspreis ab Werk ohne Umsatzsteuer, Fracht und Rabatte)",
        ),
        cost="low",
    )
    config_model = OpenPriceReferenceConfig

    def applicability(
        self, context: ValidationContext, config: OpenPriceReferenceConfig
    ) -> Applicability:
        return unit_price_applicability(context)

    def validate(
        self, context: ValidationContext, config: OpenPriceReferenceConfig
    ) -> DetectorResult:
        result = DetectorResult()
        data = source_data()
        tables = {t.table_id: t for t in context.tables()}
        tally: dict[str, Counter[str]] = {"invalid": Counter(), "abstained": Counter()}
        listed: list[str] = []
        for record in item_frame(context).records:
            context.checkpoint()
            if record.counts_toward_totals is False:
                continue
            price = record.unit_price_per_base_unit
            if price is None or price <= 0 or record.unit_id is None:
                result.count(ROWS_NOT_PRICED)
                continue
            text, matches = rule_matches(record)
            if len(matches) != 1:
                result.count(ROWS_AMBIGUOUS if matches else ROWS_WITHOUT_REFERENCE)
                self._suggested(context, data, tables, record, price, result, tally, listed)
                continue
            [reference] = matches
            if _SCOPE_EXCLUDED.search(text):
                result.count(ROWS_SCOPE_EXCLUDED)
                continue
            source = data.values.get(reference.code)
            if source is None:
                result.count(ROWS_WITHHELD)
                continue
            factor = UNIT_FACTORS.get(source.unit, {}).get(record.unit_id)
            if factor is None:
                result.count(ROWS_UNIT_MISMATCH)
                continue
            table = tables[record.table_id]
            row = next(r for r in context.rows(table) if r.row_id == record.row_id)
            if context.currency_evidence(table, row, ["unit_price", "line_total"]) != "EUR":
                result.count(ROWS_CURRENCY)
                continue
            result.count(ROWS_COMPARED)
            per_source_unit = price / factor
            if per_source_unit < source.unit_value:
                result.add(
                    self._issue(
                        context, data, table, row, record, reference, source, per_source_unit
                    )
                )
        result.notes.extend(_model_notes(context.material_answers, result, tally, listed))
        return result

    def _suggested(
        self,
        context: ValidationContext,
        data: SourceData,
        tables: dict[str, Table],
        record: ItemRecord,
        price: Decimal,
        result: DetectorResult,
        tally: dict[str, Counter[str]],
        listed: list[str],
    ) -> None:
        """The model path of a row the keywords could not match (see the module docstring)."""
        answers = context.material_answers
        answer = None
        if answers is not None and answers.model is not None:
            answer = answers.answers.get(mm.answer_key(answers.model, model_prompt(record)))
        if answer is None or answer.status == "not_sent":
            result.count(MODEL_NOT_PROCESSED)
            return
        if answer.status == "request_failed":
            result.count(MODEL_REQUEST_FAILED)
            return
        text = mm.sent_text(record.description, record.long_description)
        try:
            proposal = mm.parse(answer.raw or "", text, frozenset(BY_CODE))
        except mm.InvalidAnswer as invalid:
            result.count(MODEL_INVALID)
            tally["invalid"][invalid.code] += 1
            return
        if proposal.product_code is None:
            result.count(MODEL_ABSTAINED)
            tally["abstained"][proposal.abstain_reason or ""] += 1
            return
        result.count(MODEL_SUGGESTED)
        reference = BY_CODE[proposal.product_code]
        where = record.item_code or f"row {record.row_id}"

        def refuse(reason: str) -> None:
            result.count(MODEL_NOT_COMPARED)
            tally.setdefault("not_compared", Counter())[reason] += 1
            listed.append(
                f"{where}: the model suggested {reference.code} ({reference.material}), scope "
                f"{proposal.scope}; not compared: {reason.replace('_', ' ')}."
            )

        if failure := mm.scope_failure(proposal, text, _SCOPE_EXCLUDED):
            return refuse(failure)
        source = data.values.get(reference.code)
        if source is None:
            return refuse("no_published_value")
        rule = mm.conversion(
            source.unit,
            record.unit_id or "",
            UNIT_FACTORS.get(source.unit, {}),
            proposal.attributes,
            SOURCE_UNIT_LABELS[source.unit],
        )
        if isinstance(rule, str):
            return refuse(rule)
        table = tables[record.table_id]
        row = next(r for r in context.rows(table) if r.row_id == record.row_id)
        if context.currency_evidence(table, row, ["unit_price", "line_total"]) != "EUR":
            return refuse("currency_not_eur")
        result.count(MODEL_COMPARED)
        per_source_unit = price / rule.factor
        if per_source_unit >= source.unit_value:
            listed.append(
                f"{where}: the model suggested {reference.code} ({reference.material}); "
                "compared: not below the published value, no finding."
            )
            return
        result.add(
            self._issue(
                context,
                data,
                table,
                row,
                record,
                reference,
                source,
                per_source_unit,
                suggestion=(proposal, rule, context.material_answers),
            )
        )

    def _issue(
        self,
        context: ValidationContext,
        data: SourceData,
        table: Table,
        row: Row,
        record: ItemRecord,
        reference: Reference,
        source: SourceValue,
        per_source_unit: Decimal,
        suggestion: tuple[mm.Proposal, mm.Conversion, MaterialAnswers | None] | None = None,
    ) -> ValidationIssue:
        unit = SOURCE_UNIT_LABELS[source.unit]
        period = data.meta["reference_period"]
        german = source.area == "DE"
        area = "German" if german else "EU-27"
        shown = source.unit_value.quantize(Decimal("0.001"))
        own = per_source_unit.quantize(Decimal("0.001"))
        caveat = (
            f"That is a {period} annual average over every grade, size and customer under the "
            "code, valued ex works without VAT, separately invoiced freight and discounts, for "
            "supply only. It is context, not what this position should cost: a lower price "
            "can be legitimate (grade, contract, volume, date, region)."
        )
        if not german:
            caveat += (
                " German figures for this code are confidential, so the EU-27 average is "
                "shown; it is not adjusted to Germany"
                + (" and Eurostat publishes it rounded." if "R" in source.flags else ".")
            )
        cell = record.cell("unit_price")
        title = (
            f"Unit price {fmt(own)} EUR/{unit} below the {period} {area} average "
            f"factory-gate value of {reference.material} ({fmt(shown)} EUR/{unit})"
        )
        named = f"{record.item_code or 'This position'} names {reference.material} and is"
        comparison = EvidenceItem(
            kind=EvidenceKind.COMPARISON,
            label=f"PRODCOM {source.code}, {area} {period}: {fmt(shown)} EUR/{unit}",
            detail=(
                f"{fmt(source.value)} EUR sold production ÷ {fmt(source.quantity)} "
                f"{unit} = {fmt(shown)} EUR/{unit}; this position {fmt(own)} EUR/{unit}."
            ),
            cells=[cell] if cell is not None else [],
            data={
                "prodcom_code": source.code,
                "area": source.area,
                "reference_period": period,
                "reference_value": fmt(shown),
                "position_value": fmt(own),
                "unit": source.unit,
                "source_flags": source.flags or None,
            },
        )
        evidence = [comparison]
        action = (
            "Check that the price is not a slip and that the position's material, grade "
            "and scope match the code; otherwise record why it is priced this way."
        )
        if suggestion is not None:
            proposal, rule, answers = suggestion
            title = f"Model-suggested match: {title[0].lower()}{title[1:]}"
            named = (
                f"The local model suggested that {record.item_code or 'this position'} is "
                f"{reference.material}, {_SCOPE_WORDS[proposal.scope]} (a suggestion, checked by "
                f"code but not by a person). It is"
            )
            evidence = _suggestion_evidence(record, reference, proposal, rule, answers, comparison)
            action = (
                f"First check the model's match: if the position does not supply "
                f"{reference.material} (alone or installed), reject this finding. Otherwise "
                "check the price as for any published reference value."
            )
        return context.issues.create(
            self.spec,
            rule_id=RULE_ID if suggestion is None else MODEL_RULE_ID,
            category=CATEGORY,
            severity=Severity.LOW,
            evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
            title=title[:200],
            explanation=(
                f"{named} priced at {fmt(record.unit_price)} EUR per {record.unit_id}, "
                f"{fmt(own)} EUR per {unit}. Eurostat PRODCOM reports "
                f"{fmt(shown)} EUR per {unit} for code {source.code} ({source.label}), the "
                f"{area} value of sold production divided by its quantity. {caveat}"
            ),
            table=table,
            row=row,
            cells=[cell] if cell is not None else [],
            inputs=list(record.cells.values()),
            observed_value=fmt(own),
            expected_value=None if suggestion is None else fmt(shown),
            evidence=[
                *evidence,
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label=f"Source: {data.meta['publisher']} {data.meta['dataset']}",
                    detail=(
                        f"{data.meta['title']}, {data.meta['source_url']}; dataset updated "
                        f"{data.meta['dataset_updated']}, retrieved {data.meta['retrieved']}. "
                        f"{data.meta['licence']}. Values divided by this application."
                    ),
                ),
            ],
            suggested_action=action,
            subject=source.code,
        )


def _suggestion_evidence(
    record: ItemRecord,
    reference: Reference,
    proposal: mm.Proposal,
    rule: mm.Conversion,
    answers: MaterialAnswers | None,
    comparison: EvidenceItem,
) -> list[EvidenceItem]:
    """The model's suggestion, the checks of code and the comparison, as separate items."""
    texts = [c for c in (record.cell("description"), record.cell("long_description")) if c]
    model = answers.model if answers else None
    quoted = "; ".join(f"\u201c{q}\u201d" for q in proposal.quotes)
    attributes = "; ".join(f"{a.name}: {a.text}" for a in proposal.attributes) or None
    checks = [
        f"Product code {reference.code} is in the local reference catalogue "
        f"({reference.material}).",
        "Every quote and attribute occurs in the position's text; the answer has no price, "
        "factor or field outside the contract.",
        f"Scope is {_SCOPE_WORDS[proposal.scope]}: the position buys the material, so its value "
        "is a floor; the text names no removal, surcharge or material supplied by others"
        + (", nor installation." if proposal.scope == "supply_only" else "."),
        f"Unit rule {rule.rule}: {rule.detail}"
        + (f" (read by code from \u201c{rule.inputs}\u201d)." if rule.inputs else "."),
        "Currency is EUR and the source publishes a value for the code.",
    ]
    return [
        EvidenceItem(
            kind=EvidenceKind.NOTE,
            label=f"Model-suggested match: {reference.code} {reference.material}",
            detail=f"{proposal.reason}\nQuoted from the position: {quoted}",
            cells=texts,
            data={
                "origin": "model_suggestion",
                "model": model,
                "model_licence": answers.model_licence if answers else None,
                "prompt_version": mm.PROMPT_VERSION,
                "product_code": reference.code,
                "scope": proposal.scope,
                "attributes": attributes,
                "person_checked": False,
            },
        ),
        EvidenceItem(
            kind=EvidenceKind.RULE,
            label="Checked by code (structure and source, not whether the match is right)",
            detail="\n".join(checks),
            data={"checks_passed": len(checks), "conversion_rule": rule.rule},
        ),
        EvidenceItem(
            kind=comparison.kind,
            label=comparison.label,
            detail=f"{comparison.detail} Unit rule: {rule.detail}.",
            cells=comparison.cells,
            data={
                **comparison.data,
                "bill_unit": record.unit_id,
                "conversion_rule": rule.rule,
                "conversion_input": rule.inputs,
            },
        ),
    ]


def _model_notes(
    answers: MaterialAnswers | None,
    result: DetectorResult,
    tally: dict[str, Counter[str]],
    listed: list[str],
) -> list[str]:
    """What the model path did, in words: never silent about rows it did not process."""
    counts = result.coverage
    rows = counts.get(ROWS_WITHOUT_REFERENCE, 0) + counts.get(ROWS_AMBIGUOUS, 0)
    if not rows:
        return []
    if answers is None:
        return [
            f"No answers of the local model are stored for this bill: the {rows} priced rows "
            "the keywords could not match were not processed by a model (keywords only)."
        ]
    notes = [
        f"Local model {answers.model or '(none)'} ({answers.status}): {answers.detail}",
        f"Of {rows} priced rows the keywords could not match: "
        f"{counts.get(MODEL_NOT_PROCESSED, 0)} not processed by the model, "
        f"{counts.get(MODEL_REQUEST_FAILED, 0)} request failed, "
        f"{counts.get(MODEL_INVALID, 0)} invalid answers, "
        f"{counts.get(MODEL_ABSTAINED, 0)} abstained, "
        f"{counts.get(MODEL_SUGGESTED, 0)} suggested a product "
        f"({counts.get(MODEL_COMPARED, 0)} compared, {counts.get(MODEL_NOT_COMPARED, 0)} not "
        "compared). Suggestions are not counted as matches until compared, and a comparison "
        "is context for a person, not a confirmed error.",
    ]
    for label, counter in tally.items():
        if counter:
            parts = ", ".join(
                f"{n} {reason.replace('_', ' ')}" for reason, n in counter.most_common()
            )
            notes.append(f"Model rows {label.replace('_', ' ')}: {parts}.")
    notes.extend(listed[:MAX_NOTES])
    if len(listed) > MAX_NOTES:
        notes.append(f"And {len(listed) - MAX_NOTES} more suggestions, not listed one by one.")
    return notes
