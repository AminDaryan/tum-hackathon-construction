"""Bid against tender: each position of a priced bill compared with the tender it answers.

The tender is an unpriced bill of the same project whose positions match the bid
(``ValidationContext.tender``, found by :mod:`app.services.tenders`). Positions are paired by
item number (OZ, compared by its parts: 01.02.0030 is 1.2.30). A bid must not change the
tender documents (VOB/A § 13 (1) Nr. 5), so every difference is reported, as a confirmed rule
violation, on the bid's row:

* ``position_not_in_tender``: the bid has a position the tender does not; its line total is the
  money at stake. Medium.
* ``tender_position_missing`` [omission]: the tender has a position the bid lacks; reported on
  the bid's section the number belongs to when there is one. High.
* ``tender_quantity_changed``: the quantity differs; the money at stake is the difference times
  the unit price (after the item discount). High.
* ``tender_unit_changed``: the unit differs (m² and m2 are the same unit). Medium.
* ``tender_text_changed``: the short or long text differs in a word, a number or a sign,
  compared without regard to case and spacing. Medium.

Not reported: texts and units a bid does not carry (a GAEB X84 or D84 bid has neither); a short
text cut at GAEB 90's 70 characters; words the anonymisation of the sample bills replaced
(:mod:`app.validation.support.tokens`), and positions numbered by such a token; a blank of the
tender (dots or underscores) the bidder filled in; item numbers that repeat in either bill
(``deterministic.exact_duplicates`` and the numbering check report those). In a contract or a
later revision, a difference may be an agreed change order: the reviewer decides.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, replace
from decimal import Decimal
from difflib import SequenceMatcher
from typing import ClassVar

from app.models.dataset import Row, RowKind, Table
from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, Severity, ValidationIssue
from app.models.model_takeoff import code_key
from app.models.tender import Tender
from app.models.values import DataType
from app.validation.contracts.context import ValidationContext
from app.validation.contracts.decimal_math import RoundingSpec
from app.validation.contracts.detector import (
    Applicability,
    Detector,
    DetectorCategory,
    DetectorConfig,
    DetectorResult,
    DetectorSpec,
)
from app.validation.contracts.issue_factory import money_impact
from app.validation.deterministic._reference_support import clip, short_digest
from app.validation.deterministic._support import fmt, row_guard
from app.validation.support.items import item_frame
from app.validation.support.text_keys import description_key
from app.validation.support.tokens import TOKEN, is_token

RULE_ADDED = "position_not_in_tender"
RULE_MISSING = "tender_position_missing"
RULE_QUANTITY = "tender_quantity_changed"
RULE_UNIT = "tender_unit_changed"
RULE_TEXT = "tender_text_changed"
CATEGORY = "tender_comparison"

POSITIONS_COMPARED = "positions_compared_with_tender"
TEXTS_NOT_IN_BID = "positions_without_text_in_bid"
TEXTS_CUT_OFF = "texts_cut_off_not_compared"
REPEATED_NUMBERS = "item_numbers_repeated_not_compared"
ANONYMISED_NUMBERS = "item_numbers_anonymised_not_compared"

_RULE_TEXT = "A bid must not change the tender documents (VOB/A § 13 (1) Nr. 5)"
_MAYBE_AGREED = (
    "In a contract or a later revision of the bill, the difference may be an agreed change order."
)
# GAEB 90 holds a short text in 70 characters and cuts what is longer, so a cut text is 69 or 70
# characters long once a trailing space is gone; a shorter prefix is a real change.
_SHORT_TEXT_WIDTH = 70
_CUT_SLACK = 2
_ANONYMISED = "\x00"  # stands for one anonymisation token in a compared text
_WORDS = re.compile(r"\x00|\w+|[^\w\s]")
_LEAD_IN = re.compile(r"^\s*wie\s+(?:pos(?:ition)?|oz)\.?\s*\d[\d.\s]*,?\s*jedoch\b", re.IGNORECASE)
_COMPLEMENT = re.compile(r"\[T[AB]\d{2}\b")
_BRACKETS = frozenset("[]")
_BLANK = re.compile(r"[._…\-]+")  # a blank of the tender for the bidder to fill in
_CHANGES_SHOWN = 3
_QUOTE = 80

Key = tuple[object, ...]


class TenderComparisonConfig(DetectorConfig):
    pass


@dataclass(frozen=True, slots=True)
class _Position:
    table: Table
    row: Row
    code: str
    short_text: str
    long_text: str


@dataclass(frozen=True, slots=True)
class _Positions:
    by_key: dict[Key, _Position]
    repeated: set[Key]
    anonymised: int


@dataclass(frozen=True, slots=True)
class _Change:
    tender: str
    bid: str


class TenderComparisonDetector(Detector[TenderComparisonConfig]):
    spec: ClassVar[DetectorSpec] = DetectorSpec(
        detector_id="domain.boq_tender_comparison",
        name="Bid against its tender",
        version="1.1.0",
        category=DetectorCategory.DOMAIN,
        description=(
            "Compares each position of a priced bill with the tender it answers (an unpriced "
            "bill of the same project whose positions match): positions added or missing, and "
            "quantities, units and texts that differ. Finds a changed quantity whose line total "
            "and sums were recomputed to match, which no check of the bill alone can see."
        ),
        required_fields=("item_code",),
        optional_fields=(
            "description",
            "long_description",
            "quantity",
            "unit",
            "unit_price",
            "line_total",
            "discount_percent",
            "currency",
        ),
        supported_data_types=(DataType.TEXT, DataType.NUMBER),
        applicability=(
            "Priced bills whose project holds their tender: an unpriced bill where at least "
            "half of the bill's positions have the same item number with the same quantity or "
            "short text."
        ),
        evidence_classes=(EvidenceClass.CONFIRMED_RULE_VIOLATION,),
        issue_categories=(CATEGORY,),
        limitations=(
            "Positions are paired by item number only; a position that moved to another number "
            "shows as one added and one missing.",
            "Texts are compared word by word without regard to case and spacing; a change of "
            "punctuation alone is reported.",
            "A difference says the bid and the tender disagree; in a contract or a later "
            "revision it may be an agreed change order.",
            "Measured on the two tender-bid pairs of the hackathon files only; the practice "
            "benchmark cannot measure it, because its clean bill is the answer key.",
        ),
        references=(
            "VOB/A 2019 § 13 (1) Nr. 5 (no changes to the tender documents) and § 16 (1) Nr. 2 "
            "(such bids are excluded)",
        ),
        cost="low",
    )
    config_model = TenderComparisonConfig

    def applicability(
        self, context: ValidationContext, config: TenderComparisonConfig
    ) -> Applicability:
        if context.tender is None:
            return Applicability.no(
                "No tender for this bill in its project: a bill with prices is compared with "
                "an unpriced bill whose positions match it."
            )
        if not any(context.has_fields(t, "item_code") for t in context.tables()):
            return Applicability.no("No table maps the item number.")
        return Applicability.yes(f"Compared with the tender {context.tender.filename}.")

    def validate(
        self, context: ValidationContext, config: TenderComparisonConfig
    ) -> DetectorResult:
        tender = context.tender
        assert tender is not None  # applicability
        result = DetectorResult()
        bid = _positions(context)
        tendered = _positions(replace(context, dataset=tender.dataset, memo={}))
        skipped = bid.repeated | tendered.repeated
        result.count(REPEATED_NUMBERS, len(skipped))
        result.count(ANONYMISED_NUMBERS, bid.anonymised + tendered.anonymised)
        for key, item in bid.by_key.items():
            if key in skipped:
                continue
            match = tendered.by_key.get(key)
            with row_guard(result, item.table, item.row):
                if match is None:
                    result.add(self._added(context, tender, item))
                    continue
                result.count(POSITIONS_COMPARED)
                for issue in self._compare(context, tender, item, match, result):
                    result.add(issue)
        sections = _sections(context)
        for key, match in tendered.by_key.items():
            context.checkpoint()
            if key not in bid.by_key and key not in skipped:
                result.add(self._missing(context, tender, match, _section_for(key, sections)))
        in_both = result.coverage.get(POSITIONS_COMPARED, 0)
        result.notes.append(
            f"Compared with the tender {tender.filename}: {in_both} positions are in both."
        )
        return result

    # ------------------------------------------------------------------ comparison
    def _compare(
        self,
        context: ValidationContext,
        tender: Tender,
        item: _Position,
        match: _Position,
        result: DetectorResult,
    ) -> list[ValidationIssue]:
        issues = []
        quantity = context.number(item.table, item.row, "quantity")
        asked = context.number(match.table, match.row, "quantity")
        if quantity is not None and asked is not None and quantity != asked:
            issues.append(self._quantity(context, tender, item, quantity, asked))
        unit = self._unit_change(context, item, match)
        if unit is not None:
            issues.append(self._unit(context, tender, item, *unit))
        if not item.short_text and not item.long_text:
            result.count(TEXTS_NOT_IN_BID)
            return issues
        changed: list[tuple[str, list[_Change]]] = []
        short_ours = _without_quantity_unit(item.short_text, quantity, _units(context, item))
        short_theirs = _without_quantity_unit(match.short_text, asked, _units(context, match))
        for field_id, ours, theirs in (
            ("description", short_ours, short_theirs),
            ("long_description", item.long_text, match.long_text),
        ):
            if not ours:
                continue
            if _cut_off(theirs, ours):
                result.count(TEXTS_CUT_OFF)
                continue
            changes = _changes(theirs, ours)
            if changes:
                changed.append((field_id, changes))
        if changed:
            issues.append(self._text(context, tender, item, changed))
        return issues

    def _unit_change(
        self, context: ValidationContext, item: _Position, match: _Position
    ) -> tuple[str, str] | None:
        field = context.unit_field_id()
        if field is None:
            return None
        ours = context.text(item.table, item.row, field)
        theirs = context.text(match.table, match.row, field)
        if not ours or not theirs:
            return None
        known, asked = context.unit(item.table, item.row), context.unit(match.table, match.row)
        if known is not None and asked is not None:
            same = (known.unit.unit_id, known.multiplier) == (asked.unit.unit_id, asked.multiplier)
        else:
            same = description_key(ours) == description_key(theirs)
        return None if same else (ours, theirs)

    # ------------------------------------------------------------------ findings
    def _quantity(
        self,
        context: ValidationContext,
        tender: Tender,
        item: _Position,
        quantity: Decimal,
        asked: Decimal,
    ) -> ValidationIssue:
        unit = _unit_text(context, item)
        difference = quantity - asked
        record = item_frame(context).record(item.table.table_id, item.row.row_id)
        currency = context.currency_evidence(item.table, item.row, ["unit_price", "line_total"])
        impact = None
        if (
            record is not None
            and record.unit_price is not None
            and record.discount_factor is not None
            and currency
        ):
            impact = money_impact(
                RoundingSpec().apply(difference * record.unit_price * record.discount_factor),
                currency,
                "(bid quantity − tender quantity) × unit price",
                reported=quantity,
                recomputed=asked,
            )
        cell = context.cell_ref(item.table, item.row, "quantity")
        direction = "more" if difference > 0 else "less"
        return context.issues.create(
            self.spec,
            rule_id=RULE_QUANTITY,
            category=CATEGORY,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(
                f"Bid prices {fmt(quantity)} {unit} of {item.code}, the tender asks for "
                f"{fmt(asked)} {unit}",
                200,
            ),
            explanation=(
                f"The tender {tender.filename} asks for {fmt(asked)} {unit} of position "
                f"{item.code}; the bid prices {fmt(quantity)} {unit}, {fmt(abs(difference))} "
                f"{unit} {direction}. {_RULE_TEXT}, and a changed quantity makes the bid's "
                "total incomparable with other bids. A quantity carried into its line total and "
                f"the sums leaves the bid consistent in itself; the tender shows it. "
                f"{_MAYBE_AGREED}"
            ),
            table=item.table,
            row=item.row,
            cells=[cell],
            observed_value=fmt(quantity),
            expected_value=fmt(asked),
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Bid against tender",
                    detail=(
                        f"Bid {fmt(quantity)} {unit}; tender {fmt(asked)} {unit}; difference "
                        f"{fmt(difference)} {unit}."
                    ),
                    cells=[cell],
                    data={
                        "bid": fmt(quantity),
                        "tender": fmt(asked),
                        "tender_file": tender.filename,
                    },
                ),
            ],
            suggested_action=(
                "Price the tender's quantity, or clear with the client why the bid differs."
            ),
            financial_impact=impact,
            subject=f"quantity:{short_digest(item.code)}",
        )

    def _unit(
        self, context: ValidationContext, tender: Tender, item: _Position, ours: str, theirs: str
    ) -> ValidationIssue:
        field = context.unit_field_id() or "unit"
        cell = context.cell_ref(item.table, item.row, field)
        return context.issues.create(
            self.spec,
            rule_id=RULE_UNIT,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Bid measures {item.code} in {ours}, the tender in {theirs}", 200),
            explanation=(
                f"The tender {tender.filename} measures position {item.code} in {theirs}; the "
                f"bid measures it in {ours}. {_RULE_TEXT}; with another unit the quantity and "
                f"the unit price no longer mean what the tender asked for. {_MAYBE_AGREED}"
            ),
            table=item.table,
            row=item.row,
            cells=[cell],
            observed_value=ours,
            expected_value=theirs,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Unit against tender",
                    detail=f"Bid: {ours}; tender: {theirs}.",
                    cells=[cell],
                ),
            ],
            suggested_action="Price the position in the tender's unit.",
            subject=f"unit:{short_digest(item.code)}",
        )

    def _text(
        self,
        context: ValidationContext,
        tender: Tender,
        item: _Position,
        changed: list[tuple[str, list[_Change]]],
    ) -> ValidationIssue:
        names = {"description": "short text", "long_description": "long text"}
        parts = []
        for field_id, changes in changed:
            shown = "; ".join(_describe(change) for change in changes[:_CHANGES_SHOWN])
            more = len(changes) - _CHANGES_SHOWN
            parts.append(f"{names[field_id]}: {shown}" + (f" and {more} more" if more > 0 else ""))
        cells = [context.cell_ref(item.table, item.row, field_id) for field_id, _ in changed]
        first = changed[0][1][0]
        which = " and ".join(names[field_id] for field_id, _ in changed)
        return context.issues.create(
            self.spec,
            rule_id=RULE_TEXT,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"The {which} of {item.code} differs from the tender", 200),
            explanation=(
                f"The bid's {which} of position {item.code} differs from the tender "
                f"{tender.filename}: {'. '.join(parts)}. {_RULE_TEXT}: the bidder prices other "
                f"work than the tender describes, or the text was changed by mistake. "
                f"{_MAYBE_AGREED}"
            ),
            table=item.table,
            row=item.row,
            cells=cells,
            observed_value=clip(first.bid or "(left out)", 200),
            expected_value=clip(first.tender or "(not in the tender)", 200),
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Text against tender",
                    detail=clip("; ".join(parts), 1000),
                    cells=cells,
                ),
            ],
            suggested_action="Restore the tender's text, or clear the change with the client.",
            subject=f"text:{short_digest(item.code)}",
        )

    def _added(
        self, context: ValidationContext, tender: Tender, item: _Position
    ) -> ValidationIssue:
        record = item_frame(context).record(item.table.table_id, item.row.row_id)
        currency = context.currency_evidence(item.table, item.row, ["line_total", "unit_price"])
        impact = None
        if (
            record is not None
            and record.line_total  # a position of quantity 0 adds nothing to the total
            and record.counts_toward_totals is not False
            and currency
        ):
            impact = money_impact(
                record.line_total, currency, "line total of the position the tender lacks"
            )
        cell = context.cell_ref(item.table, item.row, "item_code")
        text = f" ('{clip(item.short_text, 120)}')" if item.short_text else ""
        return context.issues.create(
            self.spec,
            rule_id=RULE_ADDED,
            category=CATEGORY,
            severity=Severity.MEDIUM,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Position {item.code} is not in the tender", 200),
            explanation=(
                f"The bid has a position {item.code}{text} that the tender {tender.filename} "
                f"does not have. {_RULE_TEXT}; an added position is priced work the client did "
                f"not ask for, and its price adds to the bid's total. {_MAYBE_AGREED}"
            ),
            table=item.table,
            row=item.row,
            cells=[cell],
            observed_value=item.code,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Item number against tender",
                    detail=f"{item.code} is in the bid; the tender has no such item number.",
                    cells=[cell],
                ),
            ],
            suggested_action=(
                "Remove the position, or clear with the client whether it is an agreed change."
            ),
            financial_impact=impact,
            subject=f"added:{short_digest(item.code)}",
        )

    def _missing(
        self,
        context: ValidationContext,
        tender: Tender,
        match: _Position,
        section: tuple[Table, Row, str] | None,
    ) -> ValidationIssue:
        text = f" ('{clip(match.short_text, 120)}')" if match.short_text else ""
        place = (
            f"Section {section[2]} of the bid has no position {match.code}."
            if section is not None
            else f"The bid has no position {match.code}."
        )
        return context.issues.create(
            self.spec,
            rule_id=RULE_MISSING,
            category=CATEGORY,
            severity=Severity.HIGH,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title=clip(f"Tender position {match.code} is missing from the bid", 200),
            explanation=(
                f"The tender {tender.filename} has a position {match.code}{text}. {place} A "
                "bid that leaves out a position offers less than the tender asks for, and its "
                f"total is not comparable with other bids. {_MAYBE_AGREED}"
            ),
            table=section[0] if section is not None else None,
            row=section[1] if section is not None else None,
            expected_value=match.code,
            evidence=[
                EvidenceItem(
                    kind=EvidenceKind.COMPARISON,
                    label="Item number against tender",
                    detail=f"{match.code} is in the tender; the bid has no such item number.",
                    data={"item_number": match.code, "tender_file": tender.filename},
                ),
            ],
            suggested_action="Price the position, or ask the bidder why it is left out.",
            subject=f"missing:{short_digest(match.code)}",
        )


# ---------------------------------------------------------------------------- reading
def _positions(view: ValidationContext) -> _Positions:
    """The item rows of the view's dataset by item number."""
    by_key: dict[Key, _Position] = {}
    repeated: set[Key] = set()
    anonymised = 0
    for table in view.tables():
        if not view.has_fields(table, "item_code"):
            continue
        for row in view.rows(table):
            code = view.text(table, row, "item_code")
            if not code:
                continue
            if is_token(code):
                anonymised += 1
                continue
            key = code_key(code)
            if key in by_key:
                repeated.add(key)
                continue
            by_key[key] = _Position(
                table=table,
                row=row,
                code=code.strip(),
                short_text=_text_of(view, table, row, "description"),
                long_text=_text_of(view, table, row, "long_description"),
            )
    return _Positions(by_key=by_key, repeated=repeated, anonymised=anonymised)


def _text_of(view: ValidationContext, table: Table, row: Row, field_id: str) -> str:
    if not view.has_fields(table, field_id):
        return ""
    return (view.text(table, row, field_id) or "").strip()


def _unit_text(context: ValidationContext, item: _Position) -> str:
    return context.text(item.table, item.row, context.unit_field_id() or "unit") or ""


def _sections(context: ValidationContext) -> list[tuple[Table, Row, str]]:
    found = []
    for table in context.tables():
        if not context.has_fields(table, "item_code"):
            continue
        for row in context.rows(table, kinds={RowKind.SECTION}):
            code = context.text(table, row, "item_code")
            if code:
                found.append((table, row, code.strip()))
    return found


def _section_for(key: Key, sections: list[tuple[Table, Row, str]]) -> tuple[Table, Row, str] | None:
    """The deepest section whose number is a prefix of ``key``."""
    best, best_length = None, 0
    for section in sections:
        prefix = code_key(section[2])
        if (
            0 < len(prefix) < len(key)
            and key[: len(prefix)] == prefix
            and len(prefix) > best_length
        ):
            best, best_length = section, len(prefix)
    return best


# ---------------------------------------------------------------------------- texts
def _words(text: str) -> list[tuple[str, int, int]]:
    """The words and signs of ``text`` as (comparison form, start, end), after what only the
    file format writes is set aside: a repeat position's lead-in ("Wie Position 3. 2. 7.,
    jedoch"), which GAEB 90 writes into the short text, and the marks around a text complement
    ("[TA11 label [ value ] ]"), which a GAEB 90 reading keeps and a DA XML reading does not. An
    anonymisation token becomes one mark, so tokens padded to different widths compare equal."""
    masked = TOKEN.sub(lambda m: _ANONYMISED + " " * (len(m.group()) - 1), text)
    masked = _blank_out(_LEAD_IN, _blank_out(_COMPLEMENT, masked))
    return [
        (unicodedata.normalize("NFKC", m.group()).casefold(), m.start(), m.end())
        for m in _WORDS.finditer(masked)
        if m.group() not in _BRACKETS
    ]


_TRAILING_AMOUNT = re.compile(r"\s+([\d.,']+)\s+(\S+)\s*$")


def _units(context: ValidationContext, item: _Position) -> set[str]:
    """The row's unit as normalized and as written."""
    cell = context.cell(item.table, item.row, context.unit_field_id() or "unit")
    raw = cell.raw_value if cell is not None else None
    return {u.strip().casefold() for u in (_unit_text(context, item), raw or "") if u.strip()}


def _without_quantity_unit(text: str, quantity: Decimal | None, units: set[str]) -> str:
    """``text`` without a trailing quantity and unit that are the row's own ("... 1 psch"): a
    printed bill read from a PDF can run them into the short text, which are no text change."""
    found = _TRAILING_AMOUNT.search(text or "")
    if found is None or quantity is None or not units:
        return text
    number, written = found.groups()
    digits = re.sub(r"\D", "", number).strip("0")
    if written.casefold() not in units or not digits:
        return text
    if digits != re.sub(r"\D", "", format(quantity.normalize(), "f")).strip("0"):
        return text
    return text[: found.start()]


def _blank_out(pattern: re.Pattern[str], text: str) -> str:
    """``text`` with the matches of ``pattern`` replaced by spaces, so offsets stay valid."""
    return pattern.sub(lambda m: " " * len(m.group()), text)


def _cut_off(tender: str, bid: str) -> bool:
    """Whether one text is the other cut at GAEB 90's short-text width."""
    ours, theirs = (" ".join(word for word, _, _ in _words(t)) for t in (bid, tender))
    if ours == theirs:
        return False
    if theirs.startswith(ours):
        cut, form = bid, ours
    elif ours.startswith(theirs):
        cut, form = tender, theirs
    else:
        return False
    length = len(_LEAD_IN.sub("", cut).strip())
    return bool(form) and _SHORT_TEXT_WIDTH - _CUT_SLACK <= length <= _SHORT_TEXT_WIDTH


def _changes(tender: str, bid: str) -> list[_Change]:
    """The word runs in which ``bid`` differs from ``tender``, as written in each. Left out are
    runs that hold an anonymisation token, words added or left out beside one (the anonymiser
    took one word or several into a token, differently in each file), a blank of the tender
    that the bidder filled in, and runs that differ only in spacing or hyphenation."""
    ours, theirs = _words(bid), _words(tender)
    matcher = SequenceMatcher(
        None, [w for w, _, _ in theirs], [w for w, _, _ in ours], autojunk=False
    )
    changes = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        left, right = theirs[i1:i2], ours[j1:j2]
        if not (left and right) and (_near_token(theirs, i1, i2) or _near_token(ours, j1, j2)):
            continue  # words beside a token that the anonymiser took into it on one side only
        if _touches_token(left) or _touches_token(right):
            continue  # a word the anonymiser replaced on one side only
        if left and all(_BLANK.fullmatch(w) for w, _, _ in left):
            continue
        if _joined(left) == _joined(right):  # "Lieferantund", "Hochleistungs- Luft...": spacing
            continue
        changes.append(_Change(tender=_span(tender, left), bid=_span(bid, right)))
    return changes


def _joined(words: list[tuple[str, int, int]]) -> str:
    """The words run together without hyphens: a line break that a reading joined with or
    without a space, or with its hyphen kept or dropped, is the same text."""
    return "".join(w for w, _, _ in words if w != "-")


def _touches_token(words: list[tuple[str, int, int]]) -> bool:
    return any(w == _ANONYMISED for w, _, _ in words)


def _near_token(words: list[tuple[str, int, int]], start: int, end: int) -> bool:
    """Whether ``words[start:end]``, or the word on either side of it, is a token."""
    return any(
        words[i][0] == _ANONYMISED for i in range(max(start - 1, 0), min(end + 1, len(words)))
    )


def _span(text: str, words: list[tuple[str, int, int]]) -> str:
    return " ".join(text[words[0][1] : words[-1][2]].split()) if words else ""


def _describe(change: _Change) -> str:
    if not change.bid:
        return f"'{clip(change.tender, _QUOTE)}' left out"
    if not change.tender:
        return f"'{clip(change.bid, _QUOTE)}' added"
    return f"'{clip(change.tender, _QUOTE)}' became '{clip(change.bid, _QUOTE)}'"
