"""Unclear or incomplete item descriptions, read as a tender estimator prices them.

VOB/A § 7 (1) asks for a description of the work that is clear and complete, so that every
bidder understands it alike and can price it without extensive preliminary work, and that
puts no unusual risk on the bidder. On item rows (short and long text):

* ``placeholder_text``: text left to be filled in by the client (``???``, ``XXX``, ``TBD``,
  ``noch festzulegen``, ``Text folgt``) -> semantic warning, medium.
* ``relative_without_base``: an item that only refers back (``wie vor``, ``dto.``, ``jedoch``)
  but is the first item of its section, so there is nothing before it -> medium.
* ``open_scope``: scope or quantity left open (``nach Bedarf``, ``nach Erfordernis``, ``bei
  Bedarf``, ``nach Aufwand``) in an item that counts toward the total: the bidder must price a
  risk -> low.
* ``open_decision``: the specification is decided later by the client (``nach Wahl des AG``,
  ``nach Angabe der Bauleitung``, ``nach Absprache``) -> low.
* ``short_text_only``: in a bill whose items carry long texts, an item with only a short text
  of a few words -> low. Items measured in time (daywork, plant hire: ``Vorarbeiter``,
  ``Bagger 0,5 m³`` per hour) are short by nature and skipped.

Per table, as one finding each (they are common and not errors on their own):

* ``catch_all_wording``: open-ended or catch-all wording (``einschl. aller``, ``komplett``,
  ``o.ä.``, ``etc.``) that leaves the extent of the work to the bidder -> info.
* ``bidder_input_required``: items that ask the bidder to state a product, type or value
  (``angebotenes Fabrikat``, ``vom Bieter einzutragen``) -> info, needs external context:
  a bid must fill them in.

The wording lists are profile-tunable plain phrases (German and English by default).

Wording that ``domain.boq_clauses`` (step B2) reports is left to it, so that one condition gives
one finding (ADR 0007): ``nach Bedarf`` and ``nach Erfordernis`` (its ``vague_wording``),
``nach Aufwand`` in a lump sum (its ``open_lump_sum``), and ``einschl. aller erforderlichen ...``
(its ``vague_wording``, which leaves small material such as ``Befestigungsmaterial`` out on
purpose). Those wordings are read with that check's default patterns.
"""

from __future__ import annotations

import re
from typing import Any, ClassVar

from pydantic import Field

from app.models.dataset import Row, RowKind, Table
from app.models.issue import (
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    Severity,
    ValidationIssue,
)
from app.models.values import DataType
from app.profiles.units import unit_key
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
    plannable,
)
from app.validation.deterministic._support import FieldId
from app.validation.domain.boq._bill_text import description_applicability
from app.validation.domain.boq._clause_support import unit_keys
from app.validation.domain.boq._tender import (
    anchor,
    listing,
    matches,
    phrase_pattern,
    quote,
    texts,
)
from app.validation.domain.boq.clauses import (
    INCLUSION_PATTERN,
    LUMP_SUM_ITEM_TYPE_PATTERN,
    LUMP_SUM_UNITS,
    OPEN_DETAIL_PATTERN,
    OPEN_LUMP_SUM_PATTERN,
)

RULE_PLACEHOLDER = "placeholder_text"
RULE_RELATIVE = "relative_without_base"
RULE_OPEN_SCOPE = "open_scope"
RULE_OPEN_DECISION = "open_decision"
RULE_SHORT_ONLY = "short_text_only"
RULE_CATCH_ALL = "catch_all_wording"
RULE_BIDDER_INPUT = "bidder_input_required"
CATEGORY_UNCLEAR = "unclear_description"
CATEGORY_BIDDER = "bidder_input"
ITEMS_READ = "items_read"

# Wording domain.boq_clauses reports (see the module text): left out here.
_CLAUSES_OPEN = re.compile(OPEN_DETAIL_PATTERN, re.IGNORECASE)
_CLAUSES_OPEN_IN_LUMP_SUM = re.compile(
    f"{OPEN_DETAIL_PATTERN}|{OPEN_LUMP_SUM_PATTERN}", re.IGNORECASE
)
_CLAUSES_INCLUSION = re.compile(INCLUSION_PATTERN, re.IGNORECASE)
_LUMP_SUM_ITEM_TYPE = re.compile(LUMP_SUM_ITEM_TYPE_PATTERN, re.IGNORECASE)
_LUMP_SUM_UNITS = unit_keys(LUMP_SUM_UNITS)

PLACEHOLDERS = (
    "???",
    "xxx",
    "xxxx",
    "tbd",
    "tba",
    "tbc",
    "n.n.",
    "noch festzulegen",
    "noch offen",
    "noch zu klären",
    "noch zu bestimmen",
    "wird nachgereicht",
    "text folgt",
    "angaben folgen",
    "beschreibung folgt",
    "to be confirmed",
    "to be determined",
    "to be advised",
)
RELATIVE = (
    "wie vor",
    "wie vorher",
    "wie vorbeschrieben",
    "wie vorstehend",
    "dto.",
    "dito",
    "desgl.",
    "jedoch",
    "as before",
    "ditto",
    "as above",
)
OPEN_SCOPE = (
    "nach Bedarf",
    "bei Bedarf",
    "nach Erfordernis",
    "nach Erfordernissen",
    "nach Notwendigkeit",
    "je nach Bedarf",
    "je nach Erfordernis",
    "nach Aufwand",
    "je nach Aufwand",
    "as required",
    "if required",
    "where required",
    "as necessary",
    "if necessary",
)
OPEN_DECISION = (
    "nach Wahl des AG",
    "nach Wahl des Auftraggebers",
    "nach Wahl der Bauleitung",
    "nach Wahl des Architekten",
    "nach Angabe des AG",
    "nach Angabe des Auftraggebers",
    "nach Angabe der Bauleitung",
    "nach Angabe des Architekten",
    "nach Angabe der BL",
    "nach Anweisung des AG",
    "nach Anweisung der Bauleitung",
    "nach Anordnung des AG",
    "nach Anordnung der Bauleitung",
    "nach Vorgabe des AG",
    "nach Vorgabe der Bauleitung",
    "nach Absprache",
    "nach Abstimmung",
    "in Absprache mit",
    "nach Rücksprache",
    "as directed",
    "as instructed",
    "to the engineer's approval",
    "to be agreed",
)
CATCH_ALL = (
    "einschl. aller",
    "einschließlich aller",
    "inkl. aller",
    "inklusive aller",
    "einschl. sämtlicher",
    "inkl. sämtlicher",
    "komplett",
    "betriebsfertig",
    "schlüsselfertig",
    "o.ä.",
    "o. ä.",
    "oder ähnlich",
    "u.ä.",
    "u. ä.",
    "etc.",
    "usw.",
    "u. dgl.",
    "u.dgl.",
    "und dergleichen",
    "or similar",
    "and the like",
    "complete with all",
)
BIDDER_INPUT = (
    "angebotenes Fabrikat",
    "angebotener Typ",
    "angebotenes Produkt",
    "angebotenes System",
    "angebotener Hersteller",
    "vom Bieter einzutragen",
    "vom Bieter anzugeben",
    "vom Bieter einzusetzen",
    "Bieterangabe",
    "Angaben des Bieters",
    "bidder to state",
    "tenderer to state",
)


def _phrases(description: str, default: tuple[str, ...]) -> Any:
    return Field(default=list(default), max_length=200, description=description)


class DescriptionClarityConfig(DetectorConfig):
    code_field: FieldId = plannable("item_code", description="Field holding the item number.")
    description_field: FieldId = plannable("description", description="Short text field.")
    long_description_field: FieldId = plannable(
        "long_description", description="Long text field (used when mapped)."
    )
    item_type_field: FieldId = plannable(
        "item_type", description="Item type field (GAEB Positionsart; used when mapped)."
    )
    placeholder_phrases: list[str] = _phrases("Text left to be filled in.", PLACEHOLDERS)
    relative_phrases: list[str] = _phrases("Wording that only refers to the item before.", RELATIVE)
    open_scope_phrases: list[str] = _phrases("Wording that leaves scope open.", OPEN_SCOPE)
    open_decision_phrases: list[str] = _phrases(
        "Wording that leaves the decision to the client later.", OPEN_DECISION
    )
    catch_all_phrases: list[str] = _phrases("Open-ended or catch-all wording.", CATCH_ALL)
    bidder_input_phrases: list[str] = _phrases(
        "Wording that asks the bidder to state something.", BIDDER_INPUT
    )
    short_text_max_chars: int = Field(
        default=30, ge=5, le=200, description="A short text up to this length is 'a few words'."
    )
    full_text_median_chars: int = Field(
        default=150,
        ge=20,
        le=5000,
        description="Median text length from which a bill counts as written in long texts.",
    )
    max_listed: int = Field(default=12, ge=1, le=100, description="Items named in a summary.")


class BoqDescriptionClarityDetector(Detector[DescriptionClarityConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_description_clarity",
        name="Unclear or incomplete descriptions",
        version="1.0.0",
        category=DetectorCategory.SEMANTIC,
        description=(
            "Reads item texts as a tender estimator prices them: text left to be filled in, "
            "items that only refer back with nothing before them, scope or decisions left "
            "open, bare short texts in a bill of long texts; and, per table, catch-all "
            "wording and items the bidder must complete."
        ),
        required_fields=("description",),
        optional_fields=("long_description",),
        supported_data_types=(DataType.TEXT,),
        applicability="Tables that map the item description of a bill of quantities.",
        evidence_classes=(EvidenceClass.SEMANTIC_WARNING, EvidenceClass.NEEDS_EXTERNAL_CONTEXT),
        issue_categories=(CATEGORY_UNCLEAR, CATEGORY_BIDDER),
        limitations=(
            "Wording is matched as phrases; it says where a description may be unclear, not "
            "that it is. A reviewer decides.",
            "German and English wording by default; other languages need profile phrases.",
        ),
        references=(
            "VOB/A § 7 (1) Nr. 1 and 3: the description of the work must be clear and "
            "complete and must not put an unusual risk on the bidder.",
        ),
        cost="low",
    )
    config_model = DescriptionClarityConfig

    def required_fields(self, config: DescriptionClarityConfig) -> tuple[str, ...]:
        return (config.description_field,)

    def applicability(
        self, context: ValidationContext, config: DescriptionClarityConfig
    ) -> Applicability:
        return description_applicability(context, config.description_field)

    def validate(
        self, context: ValidationContext, config: DescriptionClarityConfig
    ) -> DetectorResult:
        result = DetectorResult()
        patterns = _Patterns(config)
        for table in context.tables():
            if context.has_fields(table, config.description_field):
                self._table(context, config, patterns, table, result)
        return result

    def _table(
        self,
        context: ValidationContext,
        config: DescriptionClarityConfig,
        patterns: _Patterns,
        table: Table,
        result: DetectorResult,
    ) -> None:
        rows = list(context.rows(table, [RowKind.ITEM, RowKind.SECTION]))
        items = [r for r in rows if r.kind is RowKind.ITEM]
        lengths = sorted(
            sum(map(len, texts(context, table, r, *self._fields(config)))) for r in items
        )
        full_text = bool(lengths) and lengths[len(lengths) // 2] >= config.full_text_median_chars
        catch_all: list[tuple[Row, list[str]]] = []
        bidder: list[tuple[Row, list[str]]] = []
        first_in_section = True
        for row in rows:
            if row.kind is RowKind.SECTION:
                first_in_section = True
                continue
            context.checkpoint()
            result.count(ITEMS_READ)
            short, long = texts(context, table, row, *self._fields(config))
            whole = f"{short} {long}".strip()
            found = matches(patterns.placeholder, whole)
            if found:
                result.add(self._item_issue(context, config, table, row, RULE_PLACEHOLDER, found))
            if first_in_section and patterns.relative and patterns.relative.match(short.strip()):
                result.add(
                    self._item_issue(context, config, table, row, RULE_RELATIVE, [quote(short, 40)])
                )
            first_in_section = False
            if row.counts_toward_totals is not False:
                left = (
                    _CLAUSES_OPEN_IN_LUMP_SUM
                    if self._lump_sum(context, config, table, row)
                    else _CLAUSES_OPEN
                )
                found = matches(patterns.open_scope, whole, skip=left)
                if found:
                    result.add(
                        self._item_issue(context, config, table, row, RULE_OPEN_SCOPE, found)
                    )
            found = matches(patterns.open_decision, whole)
            if found:
                result.add(self._item_issue(context, config, table, row, RULE_OPEN_DECISION, found))
            unit = context.unit(table, row) if context.unit_field_id() else None
            if (
                full_text
                and short
                and not long
                and len(short) <= config.short_text_max_chars
                and not (patterns.relative and patterns.relative.match(short.strip()))
                and not (unit is not None and unit.unit.dimension == "time")
            ):
                result.add(self._item_issue(context, config, table, row, RULE_SHORT_ONLY, [short]))
            found = matches(patterns.catch_all, whole, skip=_CLAUSES_INCLUSION)
            if found:
                catch_all.append((row, found))
            found = matches(patterns.bidder_input, whole)
            if found:
                bidder.append((row, found))
        if catch_all:
            result.add(self._summary(context, config, table, RULE_CATCH_ALL, catch_all))
        if bidder:
            result.add(self._summary(context, config, table, RULE_BIDDER_INPUT, bidder))

    @staticmethod
    def _lump_sum(
        context: ValidationContext, config: DescriptionClarityConfig, table: Table, row: Row
    ) -> bool:
        """A lump sum as ``domain.boq_clauses`` reads one: a unit of the lump sum dimension, the
        unit text ``psch``, ``pauschal`` or ``pa``, or the item type ``Pauschalposition``."""
        field = context.unit_field_id()
        if field is not None and context.has_fields(table, field):
            unit = context.unit(table, row)
            if unit is not None and unit.unit.dimension == "lump_sum":
                return True
            text = context.text(table, row, field)
            if text and unit_key(text) in _LUMP_SUM_UNITS:
                return True
        if not context.has_fields(table, config.item_type_field):
            return False
        item_type = context.text(table, row, config.item_type_field)
        return bool(item_type and _LUMP_SUM_ITEM_TYPE.search(item_type))

    @staticmethod
    def _fields(config: DescriptionClarityConfig) -> tuple[str, str]:
        return config.description_field, config.long_description_field

    def _item_issue(
        self,
        context: ValidationContext,
        config: DescriptionClarityConfig,
        table: Table,
        row: Row,
        rule: str,
        found: list[str],
    ) -> ValidationIssue:
        code = context.text(table, row, config.code_field) or f"row {row.source_row_number}"
        short = context.text(table, row, config.description_field) or ""
        phrases = ", ".join(f"'{f}'" for f in found)
        title, explanation, action, severity = {
            RULE_PLACEHOLDER: (
                f"Item {code}: description not finished ({phrases})",
                f"The text of item {code} still holds {phrases}: part of the description was "
                "left to be filled in. The item cannot be priced reliably as it stands.",
                "Ask the client for the missing part of the description.",
                Severity.MEDIUM,
            ),
            RULE_RELATIVE: (
                f"Item {code} refers back, but nothing is before it",
                f"Item {code} begins {phrases}, which refers to the item before; but it is the "
                "first item of its section, so there is no item it can refer to. Its "
                "description is incomplete.",
                "Ask the client which item it refers to, or for the full description.",
                Severity.MEDIUM,
            ),
            RULE_OPEN_SCOPE: (
                f"Item {code}: scope left open ({phrases})",
                f"Item {code} counts toward the total but leaves its scope open ({phrases}). "
                "The bidder must price work whose extent is not fixed: a risk VOB/A § 7 keeps "
                "away from the bidder. Such work is normally a contingency item "
                "(Bedarfsposition) or has a fixed quantity.",
                "Ask the client to fix the scope, or to make the item a contingency item.",
                Severity.LOW,
            ),
            RULE_OPEN_DECISION: (
                f"Item {code}: decision left to later ({phrases})",
                f"The specification of item {code} is to be decided later by the client "
                f"({phrases}). What is decided can change the price.",
                "Ask the client for the decision before pricing, or price the most expensive "
                "reading and say so.",
                Severity.LOW,
            ),
            RULE_SHORT_ONLY: (
                f"Item {code} has only a short text: {quote(short, 60)}",
                f"Most items of this bill carry a long text, but item {code} only says "
                f"{quote(short, 80)!r}. Material, dimensions and quality are not described, "
                "so the item is hard to price.",
                "Ask the client for the full description of the item.",
                Severity.LOW,
            ),
        }[rule]
        cells = anchor(context, table, row, config.description_field)
        return context.issues.create(
            self.spec,
            rule_id=rule,
            category=CATEGORY_UNCLEAR,
            severity=severity,
            evidence_class=EvidenceClass.SEMANTIC_WARNING,
            title=title[:200],
            explanation=explanation,
            table=table,
            row=row,
            cells=cells,
            observed_value=", ".join(found)[:500],
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.VALUE,
                    label="Wording found",
                    detail=phrases,
                    cells=cells,
                )
            ],
            suggested_action=action,
        )

    def _summary(
        self,
        context: ValidationContext,
        config: DescriptionClarityConfig,
        table: Table,
        rule: str,
        found: list[tuple[Row, list[str]]],
    ) -> ValidationIssue:
        codes = [
            context.text(table, row, config.code_field) or f"row {row.source_row_number}"
            for row, _ in found
        ]
        counts: dict[str, int] = {}
        for _, phrases in found:
            for phrase in phrases:
                counts[phrase.lower()] = counts.get(phrase.lower(), 0) + 1
        common = ", ".join(
            f"'{p}' ({n})" for p, n in sorted(counts.items(), key=lambda i: -i[1])[:8]
        )
        cells = [
            ref
            for row, _ in found[: config.max_listed]
            for ref in anchor(context, table, row, config.description_field)
        ]
        if rule == RULE_CATCH_ALL:
            items = "1 item" if len(found) == 1 else f"{len(found)} items"
            title = f"{items} with open-ended wording"
            explanation = (
                f"{items} {'uses' if len(found) == 1 else 'use'} open-ended or catch-all "
                f"wording ({common}): "
                f"{listing(codes, config.max_listed)}. Such wording leaves the extent of the "
                "work to the bidder; a tender estimator prices it as a risk or asks."
            )
            action = "Read these items for what 'all' or 'similar' includes, and ask if unclear."
            severity, evidence_class, category = (
                Severity.INFO,
                EvidenceClass.SEMANTIC_WARNING,
                CATEGORY_UNCLEAR,
            )
        else:
            title = f"{len(found)} items ask the bidder to state a product or value"
            explanation = (
                f"{len(found)} items ask the bidder to fill something in ({common}): "
                f"{listing(codes, config.max_listed)}. A bid must state them; an empty one "
                "can make the bid incomplete."
            )
            action = "Fill in the product, type or value for each of these items in the bid."
            severity, evidence_class, category = (
                Severity.INFO,
                EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
                CATEGORY_BIDDER,
            )
        return context.issues.create(
            self.spec,
            rule_id=rule,
            category=category,
            severity=severity,
            evidence_class=evidence_class,
            title=title,
            explanation=explanation,
            table=table,
            cells=cells,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.REFERENCE,
                    label="Items",
                    detail=listing(codes, 50),
                    cells=cells,
                    data={"items": len(found)},
                )
            ],
            suggested_action=action,
            subject=rule,
        )


class _Patterns:
    def __init__(self, config: DescriptionClarityConfig) -> None:
        self.placeholder = phrase_pattern(config.placeholder_phrases)
        relative = phrase_pattern(config.relative_phrases)
        self.relative = re.compile(f"(?:{relative.pattern})", re.IGNORECASE) if relative else None
        self.open_scope = phrase_pattern(config.open_scope_phrases)
        self.open_decision = phrase_pattern(config.open_decision_phrases)
        self.catch_all = phrase_pattern(config.catch_all_phrases)
        self.bidder_input = phrase_pattern(config.bidder_input_phrases)
