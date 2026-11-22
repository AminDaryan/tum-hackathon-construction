"""Stored findings of the run's detectors, as risk candidates.

The detectors already weighed the evidence: a line total that does not equal quantity x unit
price is a confirmed rule violation, a price far from similar positions a suspected anomaly.
This adapter keeps their evidence class and explanation, maps each finding to a risk type of
the catalogue (``findings.yaml``) and adds what a reminder needs: the positions, the cell
values as quotes, the money and its basis, and the review record of the same check.

Money: a computed difference (``discrepancy``) is exact, for risk types whose category the
grading table lets carry exact money; a possible double count is an estimate from 0 to the
line total (it is lost only if both positions are the same work); a comparison with similar
positions never carries money (a difference from them is not a loss); everything else is
unknown. Findings a reviewer rejected or corrected are left out, but count in the track record;
:func:`rejected_findings` gives the rejected ones for the report to list as rejected.
A finding that compares no values asks the question ``findings.yaml`` gives for its rule, if
any, and names the documents the table says the run lacks.

Findings on one row without money that say the same thing (one detector rule, risk type, field,
evidence class, observed and expected value) share a group key: grading shows them as one
reminder that lists their rows, as it does for a text check. A finding with money, or one that
already names several rows, stays a reminder of its own.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from app.models.dataset import CellRef, Column, Dataset
from app.models.issue import EvidenceKind, IssueCategory, ReviewStatus, ValidationIssue
from app.models.run import DetectorExecutionStatus, ValidationRun
from app.models.source import SourceKind
from app.risk.bill import Bill, Position
from app.risk.checks.base import CheckResult, Outcome
from app.risk.explain import action
from app.risk.models import (
    CERTAINTY_OF,
    FINDING_GROUP,
    Candidate,
    Certainty,
    EvidenceLink,
    Method,
    Money,
    MoneyKind,
    PositionRef,
    Quote,
    ReferenceAmount,
    State,
    TrackRecord,
)
from app.risk.tables import OTHER, RiskTables
from app.risk.text import clip, fold
from app.validation.contracts.decimal_math import format_amount
from app.validation.deterministic.line_total import (
    PREVAILS_STATED_AMOUNT,
    PREVAILS_UNIT_PRICE,
    PREVAILS_UNLESS_LUMP_SUM,
)

MAX_LINKED_ROWS = 50  # rows shown per evidence link; positions_total counts them all
_LEFT_OUT = frozenset({ReviewStatus.FALSE_POSITIVE, ReviewStatus.DISMISSED, ReviewStatus.CORRECTED})
_REJECTED = frozenset({ReviewStatus.FALSE_POSITIVE, ReviewStatus.DISMISSED})
_RAN = frozenset({DetectorExecutionStatus.COMPLETED, DetectorExecutionStatus.STOPPED})
# Text fields hold many statements: a finding anchored to one says nothing about the others, so
# sharing such a cell is not sharing evidence (other fields hold one value each).
_TEXT_FIELDS = frozenset({"description", "long_description"})
# "Incorrect PDF table extraction": what the extraction check finds in a bill read from another
# format (a CSV's header, a spreadsheet's column mapping) is not a PDF problem.
_PDF_EXTRACTION = "R123"
_PDF_SOURCES = frozenset({SourceKind.PDF_TEXT, SourceKind.OCR})


def from_findings(
    run: ValidationRun,
    issues: list[ValidationIssue],
    dataset: Dataset,
    bill: Bill,
    tables: RiskTables,
) -> CheckResult:
    columns = {(t.table_id, c.column_id): c for t in dataset.tables for c in t.columns}
    positions = {(p.table_id, p.row_id): p for p in bill.positions}
    records = _track_records(issues)
    from_pdf = _from_pdf(dataset)
    result = CheckResult()
    found_types: Counter[tuple[str, str]] = Counter()  # (detector, risk type)
    for issue in issues:
        risk_type, method = _risk_type(issue, tables, columns, from_pdf)
        if issue.review_status in _LEFT_OUT:
            continue
        found_types[(issue.detector_id, risk_type)] += 1
        result.candidates.append(
            _candidate(issue, risk_type, method, dataset, columns, positions, bill, tables, records)
        )
    for report in run.detector_reports:
        mapping = tables.findings.detectors.get(report.detector_id)
        if mapping is None:
            continue
        # Counts that only skipped ("rows_skipped_missing_inputs") are no check: silence is
        # "covered" only where the detector says it checked or compared something (the two
        # evaluated suffixes of app.validation.contracts.conditions.Coverage and peer_price) or
        # one of its own counts that say it read something (``checked_counts``).
        checked = sum(
            v
            for k, v in report.coverage.items()
            if k.endswith(("_checked", "_compared")) or k in mapping.checked_counts
        )
        for risk_type in sorted(mapping.types()):
            if risk_type == _PDF_EXTRACTION and not from_pdf:
                continue
            found = found_types[(report.detector_id, risk_type)]
            if report.status not in _RAN:  # skipped or failed: its reason, never "passed"
                why = "; ".join(report.skipped_reasons) or report.error or "no reason given"
                state = State.NOT_CHECKABLE
                reason = f"detector {report.status.value}: {clip(why, 200)}"
            elif found:
                state, reason = State.RISK, f"{found} open findings"
            elif report.coverage and not checked:
                state, reason = State.NOT_CHECKABLE, "the detector ran but had nothing to check"
            elif report.status is DetectorExecutionStatus.STOPPED:
                state, reason = (
                    State.NOT_CHECKABLE,
                    ("the detector stopped at its time limit; nothing open in the part it checked"),
                )
            else:
                state, reason = State.COVERED, "the detector ran and found nothing open"
            if report.coverage:  # what it did not compare is shown, not passed
                counts = ", ".join(f"{k} {v}" for k, v in sorted(report.coverage.items()))
                reason = clip(f"{reason} ({counts})", 600)
            result.outcomes.append(
                Outcome(risk_type, report.detector_id, state, reason, scope=report.coverage)
            )
    ran = {report.detector_id for report in run.detector_reports}
    for detector_id, mapping in tables.findings.detectors.items():
        if detector_id not in ran:  # not run is not passed: the type keeps an explicit gap
            result.outcomes.extend(
                Outcome(t, detector_id, State.NOT_CHECKABLE, "detector not in this run's plan")
                for t in sorted(mapping.types())
                if t != _PDF_EXTRACTION or from_pdf
            )
    return result


def rejected_findings(
    issues: list[ValidationIssue], dataset: Dataset, bill: Bill, tables: RiskTables
) -> list[Candidate]:
    """The findings a reviewer rejected, as candidates, so the risk report can still list them
    as rejected (to be found and the decision undone). :func:`from_findings` leaves them out of
    the reminders, the coverage and everything built on them."""
    columns = {(t.table_id, c.column_id): c for t in dataset.tables for c in t.columns}
    positions = {(p.table_id, p.row_id): p for p in bill.positions}
    records = _track_records(issues)
    return [
        _candidate(
            issue,
            *_risk_type(issue, tables, columns, _from_pdf(dataset)),
            dataset,
            columns,
            positions,
            bill,
            tables,
            records,
        )
        for issue in issues
        if issue.review_status in _REJECTED
    ]


def _from_pdf(dataset: Dataset) -> bool:
    return any(table.source.kind in _PDF_SOURCES for table in dataset.tables)


def _risk_type(
    issue: ValidationIssue,
    tables: RiskTables,
    columns: dict[tuple[str, str], Column],
    from_pdf: bool,
) -> tuple[str, Method]:
    risk_type, method = _mapped_type(issue, tables, columns)
    return (OTHER if risk_type == _PDF_EXTRACTION and not from_pdf else risk_type), method


def _mapped_type(
    issue: ValidationIssue, tables: RiskTables, columns: dict[tuple[str, str], Column]
) -> tuple[str, Method]:
    findings = tables.findings
    mapping = findings.detectors.get(issue.detector_id)
    if mapping is None:
        method = (
            Method.PEER_COMPARISON
            if issue.issue_category in findings.peer_comparison_categories
            else Method.INVARIANT
        )
        return findings.categories.get(issue.issue_category, OTHER), method
    method = mapping.method or Method.INVARIANT
    if issue.rule_id in mapping.by_rule:
        return mapping.by_rule[issue.rule_id], method
    for cell in issue.affected_cells:
        field = _field(columns, cell)
        if field is not None and field in mapping.by_field:
            return mapping.by_field[field], method
    return mapping.risk_type, method


def _field(columns: dict[tuple[str, str], Column], cell: CellRef) -> str | None:
    column = columns.get((cell.table_id, cell.column_id))
    return column.mapping.field_id if column is not None and column.mapping else None


_MONEY_CATEGORIES = frozenset(
    {IssueCategory.ARITHMETIC, IssueCategory.SUBTOTAL, IssueCategory.GRAND_TOTAL}
)


def _shown(issue: ValidationIssue, value: str) -> str:
    """An observed or expected value for the question: an amount of a money check with two
    decimals ("2000.0" -> "2000.00"), anything else as the check wrote it."""
    if issue.issue_category not in _MONEY_CATEGORIES:
        return value
    try:
        number = Decimal(value)
    except InvalidOperation:
        return value  # not a plain number, e.g. ">= 13.90"
    return format_amount(number) if number.is_finite() else value


def _track_records(issues: list[ValidationIssue]) -> dict[tuple[str, str], TrackRecord]:
    confirmed: Counter[tuple[str, str]] = Counter()
    rejected: Counter[tuple[str, str]] = Counter()
    for issue in issues:
        key = (issue.detector_id, issue.rule_id)
        if issue.review_status is ReviewStatus.CONFIRMED_ERROR:
            confirmed[key] += 1
        elif issue.review_status in _REJECTED:
            rejected[key] += 1
    return {
        key: TrackRecord(
            reviewed=confirmed[key] + rejected[key],
            confirmed=confirmed[key],
            rejected=rejected[key],
        )
        for key in set(confirmed) | set(rejected)
    }


def _line_total_question(issue: ValidationIssue, category: str) -> str | None:
    if issue.detector_id != "deterministic.line_total" or issue.rule_id != "line_total_mismatch":
        return None
    rules = [
        item.data
        for item in issue.evidence
        if item.kind is EvidenceKind.RULE
        and ("prevails" in item.data or "corrected_line_total" in item.data)
    ]
    # Missing or conflicting rules cannot settle an interpretation.
    if len(rules) != 1:
        return None
    prevails = rules[0].get("prevails")
    corrected = rules[0].get("corrected_line_total")
    if prevails not in {PREVAILS_UNIT_PRICE, PREVAILS_STATED_AMOUNT, PREVAILS_UNLESS_LUMP_SUM}:
        return None
    if not isinstance(corrected, str) or len(corrected) > 120:
        return None
    try:
        number = Decimal(corrected)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    # Bound expanded display length without truncating amounts.
    exponent = number.as_tuple().exponent
    if not isinstance(exponent, int) or len(number.as_tuple().digits) + abs(exponent) > 120:
        return None
    # Pricing amounts are the bidder's own prices: the client question names the rule only.
    shown = "quantity × unit price" if category == "pricing" else format_amount(number)
    if prevails == PREVAILS_STATED_AMOUNT:
        rule = "a lump sum keeps its stated amount"
        reading = "this position's total as the stated amount" + (
            "" if category == "pricing" else f" {shown}"
        )
    else:
        rule, reading = "the unit price prevails", f"the line total as {shown}"
        if prevails == PREVAILS_UNLESS_LUMP_SUM:
            rule += " unless the position is a lump sum"
            reading += ", or as the stated amount if this position is a lump sum"
    return (
        f"{{positions}}: Under the rule used in this check, {rule}, so we read {reading}. "
        "Please confirm."
    )


def _candidate(
    issue: ValidationIssue,
    risk_type: str,
    method: Method,
    dataset: Dataset,
    columns: dict[tuple[str, str], Column],
    positions: dict[tuple[str, str], Position],
    bill: Bill,
    tables: RiskTables,
    records: dict[tuple[str, str], TrackRecord],
) -> Candidate:
    risk = tables.risk_type(risk_type)
    certainty = CERTAINTY_OF[issue.effective_evidence_class]
    rows = list(dict.fromkeys((c.table_id, c.row_id) for c in issue.affected_cells))
    if not rows and issue.table_id and issue.row_id:
        rows = [(issue.table_id, issue.row_id)]
    refs = [
        _ref(dataset, positions, table_id, row_id, issue.affected_cells)
        for table_id, row_id in rows
    ]
    quotes = [_cell_quote(dataset, columns, positions, cell) for cell in issue.affected_cells[:4]]
    found = [p for key in rows if (p := positions.get(key)) is not None]
    quotes += [
        Quote(position=p.label, source="short text", text=clip(p.short_text, 1000))
        for p in found[:2]
        if p.short_text
    ]
    mapping = tables.findings.detectors.get(issue.detector_id)
    question = mapping.questions.get(issue.rule_id) if mapping is not None else None
    # The values of a pricing finding are the bidder's own prices, which never go to the client.
    if issue.observed_value and issue.expected_value and risk.category != "pricing":
        observed, expected = (
            _shown(issue, issue.observed_value),
            _shown(issue, issue.expected_value),
        )
        question = (
            f"{{positions}}: the bill shows {clip(observed, 120)}, the check expects "
            f"{clip(expected, 120)}. Which value applies?"
        )
    question = _line_total_question(issue, risk.category) or question
    missing = tuple(mapping.missing.get(issue.rule_id, ())) if mapping is not None else ()
    cause = f"{issue.detector_id}:{issue.rule_id}" if risk_type == OTHER else risk_type
    keys = {
        f"cell:{c.table_id}/{c.row_id}/{c.column_id}"
        + (f"#{cause}" if _field(columns, c) in _TEXT_FIELDS else "")
        for c in issue.affected_cells
    }
    money = _money(issue, method, risk.category, found, bill, tables)
    # One check saying the same thing on many rows is one cause, shown as one reminder that
    # lists the rows (as the text checks do). Not with money: an amount belongs to its row. Not
    # a finding about several rows: the detector grouped those itself (one description each).
    fields = sorted({f for cell in issue.affected_cells if (f := _field(columns, cell))})
    group = (
        f"{FINDING_GROUP}{issue.detector_id}:{issue.rule_id}|{risk_type}|{','.join(fields)}|"
        f"{issue.effective_evidence_class.value}|{issue.observed_value}|{issue.expected_value}"
        if len(rows) == 1 and money.kind is MoneyKind.UNKNOWN and money.reference is None
        else ""
    )
    return Candidate(
        rule_id=f"{issue.detector_id}:{issue.rule_id}",
        risk_type=risk_type,
        method=method,
        state=State.CANNOT_TELL if certainty is Certainty.UNCLEAR else State.RISK,
        certainty=certainty,
        title=issue.title,
        positions=tuple(refs),
        quotes=tuple(q for q in quotes if q is not None),
        question=question,
        checked=(f"detector {issue.detector_id} (rule {issue.rule_id})",),
        missing_information=missing,
        money=money,
        harm=risk.harm,
        keywords_only=False,
        changes_totals=issue.issue_category in tables.findings.changes_totals_categories,
        position_texts=tuple(p.folded for p in found) or (fold(issue.title),),
        explanation=issue.explanation,
        action=issue.suggested_action or action(tables, risk.category, {}),
        source_issue_ids=(issue.issue_id,),
        evidence_links=_links(issue, dataset, positions, set(rows)),
        evidence_keys=frozenset(keys or {f"issue:{issue.issue_id}"}),
        stable_key=issue.fingerprint,
        track_record=records.get((issue.detector_id, issue.rule_id)),
        evidence_class=issue.effective_evidence_class,
        group=group,
    )


def _links(
    issue: ValidationIssue,
    dataset: Dataset,
    positions: dict[tuple[str, str], Position],
    shown: set[tuple[str, str]],
) -> tuple[EvidenceLink, ...]:
    """The rows of each evidence item's cells and the input rows no item names, other than the
    finding's own rows (a total's "Rows summed" and "Not counted"). An item that names rows
    only in its text gives no link: the text is not parsed."""
    links: list[EvidenceLink] = []
    named: set[tuple[str, str]] = set()
    for item in issue.evidence:
        cells = dict.fromkeys((c.table_id, c.row_id) for c in item.cells)
        rows = [r for r in cells if r not in shown]
        named.update(rows)
        if rows:
            links.append(_link(item.label, item.kind.value, rows, dataset, positions, item.cells))
    inputs = [
        r
        for r in dict.fromkeys((c.table_id, c.row_id) for c in issue.input_cells)
        if r not in shown and r not in named
    ]
    if inputs:
        links.append(_link("Inputs", "input", inputs, dataset, positions, issue.input_cells))
    return tuple(links)


def _link(
    label: str,
    kind: str,
    rows: list[tuple[str, str]],
    dataset: Dataset,
    positions: dict[tuple[str, str], Position],
    cells: list[CellRef],
) -> EvidenceLink:
    refs = [_ref(dataset, positions, t, r, cells) for t, r in rows[:MAX_LINKED_ROWS]]
    return EvidenceLink(
        label=label[:200], kind=kind[:40], positions=refs, positions_total=len(rows)
    )


def _ref(
    dataset: Dataset,
    positions: dict[tuple[str, str], Position],
    table_id: str,
    row_id: str,
    cells: list[CellRef],
) -> PositionRef:
    shown = [c for c in cells if c.table_id == table_id and c.row_id == row_id]
    position = positions.get((table_id, row_id))
    if position is not None:
        return PositionRef(
            label=position.label,
            item_code=position.item_code,
            table_id=table_id,
            row_id=row_id,
            cells=shown,
        )
    table = next((t for t in dataset.tables if t.table_id == table_id), None)
    label = row_id
    if table is not None and table.has_row(row_id):
        label = f"row {table.row(row_id).source_row_number} of {table.name}"
    return PositionRef(label=label[:200], table_id=table_id, row_id=row_id, cells=shown)


def _cell_quote(
    dataset: Dataset,
    columns: dict[tuple[str, str], Column],
    positions: dict[tuple[str, str], Position],
    cell: CellRef,
) -> Quote | None:
    table = next((t for t in dataset.tables if t.table_id == cell.table_id), None)
    if table is None or not table.has_row(cell.row_id):
        return None
    found = table.row(cell.row_id).cells.get(cell.column_id)
    raw = found.raw_value if found is not None else None
    if raw is None or not raw.strip():
        return None
    column = columns.get((cell.table_id, cell.column_id))
    header = (column.original_header or column.normalized_name) if column is not None else "cell"
    position = positions.get((cell.table_id, cell.row_id))
    return Quote(
        position=position.label if position else None,
        source=f"cell '{clip(str(header), 80)}'",
        text=clip(raw, 1000),
    )


def _money(
    issue: ValidationIssue,
    method: Method,
    category: str,
    found: list[Position],
    bill: Bill,
    tables: RiskTables,
) -> Money:
    impact = issue.estimated_financial_impact
    if method is Method.PEER_COMPARISON:
        reference = None
        if impact is not None:  # an impact always has its currency (FinancialImpact)
            reference = ReferenceAmount(
                amount=impact.amount,
                currency=impact.currency,
                basis=clip(impact.basis, 600),
                kind=impact.kind,
                reported=impact.reported,
                recomputed=impact.recomputed,
                source_issue_id=issue.issue_id,
                detector_id=issue.detector_id,
            )
        return Money(
            kind=MoneyKind.UNKNOWN,
            basis="A difference from similar positions is not a loss: the price may be right."
            + (" The detector's comparison amount is kept as a reference." if reference else ""),
            reference=reference,
        )
    if impact is None:
        return Money(kind=MoneyKind.UNKNOWN, basis="The check computed no amount for this finding.")
    if impact.kind == "potential_double_count":
        position = found[0] if found else None
        if (
            position is not None
            and position.quantity is not None
            and position.unit_price is not None
        ):
            high = abs(impact.amount)
            return Money(
                kind=MoneyKind.ESTIMATE,
                currency=impact.currency,
                low=Decimal(0),
                high=high,
                quantity=position.quantity,
                reference_price=position.unit_price,
                comparable=f"the position itself ({position.label}) and the one it repeats",
                basis="Counted twice only if both positions are the same work: "
                + clip(impact.basis, 400),
                share_of_total=_share(high, impact.currency, bill),
            )
        return Money(
            kind=MoneyKind.UNKNOWN,
            basis="A possible double count; the amount depends on whether both positions are the "
            "same work.",
        )
    if category not in tables.grading.money_sources.get("exact", []):
        return Money(
            kind=MoneyKind.UNKNOWN,
            basis=f"A computed difference exists ({clip(impact.basis, 300)}), but this risk "
            "type does not turn it into money at stake.",
        )
    amount = abs(impact.amount)
    return Money(
        kind=MoneyKind.EXACT,
        amount=amount,
        currency=impact.currency,
        basis=clip(impact.basis, 600),
        share_of_total=_share(amount, impact.currency, bill),
    )


def _share(amount: Decimal, currency: str, bill: Bill) -> Decimal | None:
    if not bill.counted_total or bill.currency != currency:
        return None
    return amount / abs(bill.counted_total)
