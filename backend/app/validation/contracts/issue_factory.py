"""Single place where :class:`ValidationIssue` objects are created.

Centralizing creation keeps these policies identical across all detectors:

1. **Declared behaviour**: an issue's evidence class and category must be declared in the
   detector's spec (so a statistical detector can never emit a confirmed rule violation).
2. **Referential integrity**: every cell an issue mentions (highlighted cells, input cells,
   evidence cells, calculation operands) must exist in the dataset being validated; its source
   location is taken from the dataset, never from the caller.
3. **Evidence rule**: every finding carries at least one evidence item from its detector (what
   was observed, the rule, a calculation), and a ``confirmed_rule_violation`` points at the
   cells or the row where the rule failed (highlighted cells or ``row``; input cells alone do
   not place it). The pipeline checks the same rule again on every finding a detector returns
   (:func:`evidence_rule_problem`).
4. **Evidence policy**: a rule can only be *confirmed* on verified input data. A confirmed
   violation computed from any unverified cell (an OCR/PDF value below the confidence threshold
   or without a score) is downgraded to ``extraction_uncertainty`` with an explanatory note.
   Values read with inferred formatting, and tables whose extraction needs review, are
   annotated so reviewers can see the caveat. Signals (``suspected_anomaly``,
   ``needs_external_context``) follow the same policy: a value that stands out only because
   it was misread is an extraction problem, so a signal computed from an unverified cell is
   ``extraction_uncertainty`` with a downgrade note, and other signals carry the caveats.
5. **Fingerprints**: a stable hash of detector, category, rule, the table (sheet index and
   name), the row (source row number), the highlighted cells (source coordinates) and the
   ``subject``, so a review decision can be matched to the same finding in a later run even
   after re-normalization assigns new ids. ``evidence_digest`` hashes the observed and
   expected values, the subject, and the raw and normalized values of every highlighted and
   input cell, so a decision is carried forward only when the evidence is unchanged.
   Fingerprints are unique per run: a second finding with the same fingerprint raises
   :class:`IssuePolicyError` (two different findings must differ in place or ``subject``).
6. **Caps and tamper check**: at most ``max_issues_per_detector`` issues per detector and
   ``max_issues_total`` per run are created; the next ``create`` raises
   :class:`~app.validation.contracts.limits.IssueLimitReached`, so caps bound memory and time,
   not just storage. The caps are checked after the issue rules: a finding that breaks a rule
   is refused as such even when a cap is reached, so it never passes as "limit reached".
   :meth:`IssueFactory.owns` accepts only the exact, unmodified object the factory created
   (identity plus a digest of its content, so editing an issue's evidence list in place is
   detected too).
7. **Refusals are recorded**: every finding refused with :class:`IssuePolicyError` is counted
   per detector and reason (:meth:`IssueFactory.refusals`), so a detector that catches the
   error itself still fails its run.
"""

from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from decimal import Decimal
from typing import Literal

from app.core.clock import Clock
from app.core.errors import NotFoundError
from app.core.ids import IdFactory, IdPrefix
from app.models.dataset import Cell, CellRef, Dataset, Row, Table
from app.models.issue import (
    AnomalyScore,
    EvidenceClass,
    EvidenceItem,
    EvidenceKind,
    FinancialImpact,
    Severity,
    ValidationIssue,
)
from app.models.source import SourceKind, SourceLocation
from app.models.values import ParseStatus, value_to_display
from app.validation.contracts.detector import DetectorSpec
from app.validation.contracts.limits import IssueLimitReached

_SCORED_SOURCES = frozenset({SourceKind.PDF_TEXT, SourceKind.OCR})
# Evidence classes of findings that signal a possible error without confirming a rule; the
# evidence policy applies to them as to confirmed violations (IssueFactory._signal_policy).
SIGNAL_CLASSES = frozenset({EvidenceClass.SUSPECTED_ANOMALY, EvidenceClass.NEEDS_EXTERNAL_CONTEXT})


# Reasons shown in a detector's run report when the factory refuses a finding. They are fixed
# text, never values from the document or from the caller, so the pipeline can show them.
NO_EVIDENCE = "a finding without evidence (every finding needs at least one evidence item)"
CONFIRMED_WITHOUT_PLACE = "a confirmed rule violation that points at no cell and no row"
_UNDECLARED_CLASS = "a finding with an evidence class the check does not declare"
_UNDECLARED_CATEGORY = "a finding with an issue category the check does not declare"
_UNCITED_CALIBRATION = "a calibrated score without a calibration reference the check declares"
_NO_SUBJECT = "a finding without cells, row or subject"
_DUPLICATE = "a second finding of one rule at the same place without a distinguishing subject"
_FOREIGN_CELLS = "a finding whose highlighted cells or row lie outside its table"
_GENERIC_REASON = "a finding the issue policy does not allow"


def is_verified(cell: Cell, threshold: float) -> bool:
    """Whether a cell's value may confirm a rule: verbatim digital cells (no engine score) are
    verified; cells from scored sources (PDF text, OCR) need a score of at least
    ``threshold`` (``ValidationLimits.low_confidence_threshold``)."""
    if cell.extraction_confidence is not None:
        return cell.extraction_confidence >= threshold
    return cell.source.kind not in _SCORED_SOURCES


class IssuePolicyError(RuntimeError):
    """A detector tried to create an issue its spec does not allow (a programming error,
    deliberately not a ValueError so per-row guards never swallow it).

    ``reason`` names the broken rule in fixed words (no document or caller values), so the
    pipeline shows it in the detector's report; the message, with the rule id, is logged."""

    def __init__(self, message: str, *, reason: str = _GENERIC_REASON) -> None:
        super().__init__(message)
        self.reason = reason


class IssueFactory:
    def __init__(
        self,
        *,
        dataset: Dataset,
        document_id: str,
        run_id: str,
        ids: IdFactory,
        clock: Clock,
        low_confidence_threshold: float,
        review_tables: Mapping[str | None, Sequence[str]] | None = None,
        max_issues_per_detector: int | None = None,
        max_issues_total: int | None = None,
    ) -> None:
        """``review_tables`` maps table ids (``None`` = whole dataset) to the codes of
        extraction warnings that need review; confirmed findings there get a caveat note."""
        self._dataset = dataset
        self._document_id = document_id
        self._run_id = run_id
        self._ids = ids
        self._clock = clock
        self._threshold = low_confidence_threshold
        self._review_tables = {
            key: sorted(set(codes)) for key, codes in (review_tables or {}).items()
        }
        self._created: dict[str, ValidationIssue] = {}
        self._content: dict[str, str] = {}  # issue id -> digest of the issue as created
        self._fingerprints: set[str] = set()  # every fingerprint of the run (kept on release)
        self._by_detector: dict[str, list[str]] = {}
        self._refused: dict[str, Counter[str]] = {}  # detector id -> refusal reason -> count
        self._max_per_detector = max_issues_per_detector
        self._max_total = max_issues_total
        self._total = 0

    # ------------------------------------------------------------------ references
    def cell_ref(self, table: Table, row: Row, column_id: str) -> CellRef:
        """Reference to a cell including a copy of its source location."""
        cell = row.cells.get(column_id)
        if cell is None:
            raise NotFoundError(f"Row {row.row_id!r} has no cell for column {column_id!r}")
        return CellRef(
            table_id=table.table_id, row_id=row.row_id, column_id=column_id, source=cell.source
        )

    def owns(self, issue: ValidationIssue) -> bool:
        """True only for the exact object this factory created, unmodified (not a copy, and
        not edited in place)."""
        return self._created.get(issue.issue_id) is issue and self._content.get(
            issue.issue_id
        ) == _content_digest(issue)

    def created_by(self, detector_id: str) -> list[ValidationIssue]:
        """Issues created for ``detector_id`` so far, in creation order (the pipeline uses this
        to keep a detector's findings when a run limit stopped it)."""
        return [self._created[i] for i in self._by_detector.get(detector_id, [])]

    def refusals(self, detector_id: str) -> dict[str, int]:
        """How many findings this factory refused for ``detector_id`` since its last
        :meth:`release`, by the fixed reason (``IssuePolicyError.reason``) of the rule each
        broke. The pipeline fails a detector with refusals even when it caught the error."""
        return dict(self._refused.get(detector_id, {}))

    def release(self, detector_id: str) -> None:
        """Forget a detector's issues and refusals once the pipeline has checked them (bounds
        memory)."""
        for issue_id in self._by_detector.pop(detector_id, []):
            self._created.pop(issue_id, None)
            self._content.pop(issue_id, None)
        self._refused.pop(detector_id, None)

    # ------------------------------------------------------------------ creation
    @property
    def low_confidence_threshold(self) -> float:
        """Extraction confidence below which a scored cell is not verified
        (``ValidationLimits.low_confidence_threshold``): the one threshold every detector uses."""
        return self._threshold

    def create(
        self,
        spec: DetectorSpec,
        *,
        rule_id: str,
        category: str,
        severity: Severity,
        evidence_class: EvidenceClass,
        title: str,
        explanation: str,
        table: Table | None = None,
        row: Row | None = None,
        cells: Sequence[CellRef] = (),
        inputs: Sequence[CellRef] = (),
        observed_value: str | None = None,
        expected_value: str | None = None,
        evidence: Sequence[EvidenceItem] = (),
        suggested_action: str | None = None,
        financial_impact: FinancialImpact | None = None,
        anomaly_score: AnomalyScore | None = None,
        subject: str | None = None,
    ) -> ValidationIssue:
        """Create an issue. ``cells`` are highlighted (the anchor of the finding); ``inputs``
        are the cells the finding was computed from (e.g. quantity and unit price of a line
        total, the summands of a subtotal) and are checked by the evidence policy too.

        ``subject`` names *what* the finding is about when the place alone does not: the field
        id of a table-level finding ("required column not mapped"), the constraint of one of
        several checks on the same cell (``"quantity:minimum"``), the key of a grouped finding
        (an unknown unit, a duplicate code). It is part of the fingerprint and the evidence
        digest, and required for findings without highlighted cells and without a row.

        ``evidence`` must hold at least one item, and a ``confirmed_rule_violation`` needs
        highlighted ``cells`` or a ``row`` (the evidence rule); notes the factory adds itself
        (downgrades, caveats) do not count as evidence.

        Raises :class:`IssuePolicyError` for undeclared classes or categories, a finding that
        breaks the evidence rule, a missing ``subject`` and a fingerprint this run already
        produced (each refusal is recorded, :meth:`refusals`), and then, for a finding that
        breaks none of these rules,
        :class:`~app.validation.contracts.limits.IssueLimitReached` once the detector or the
        run reached its cap (the pipeline handles it)."""
        # Read one-shot iterables once: an empty generator is truthy and would pass the
        # evidence rule and the subject rule unread.
        cells, evidence = tuple(cells), tuple(evidence)
        try:
            self._check_declared(spec, evidence_class, category, anomaly_score)
            _check_evidence_rule(spec, rule_id, evidence_class, evidence, cells, row)
            if not cells and row is None and not subject:
                raise IssuePolicyError(
                    f"{spec.detector_id}: findings without highlighted cells and without a row "
                    "need a subject (for example the field id they are about)",
                    reason=_NO_SUBJECT,
                )
            anchor = [self._resolve(ref) for ref in cells]
            input_refs = [self._resolve(ref) for ref in inputs]
            evidence_items = [self._resolve_evidence(item) for item in evidence]
            table_id, row_id = self._anchor(table, row, anchor)
            fingerprint = self._fingerprint(
                spec.detector_id, category, rule_id, table_id, row_id, anchor, subject
            )
            if fingerprint in self._fingerprints:
                raise IssuePolicyError(
                    f"{spec.detector_id}: a second finding of rule {rule_id!r} at the same "
                    "place; pass a distinguishing subject",
                    reason=_DUPLICATE,
                )
        except IssuePolicyError as refused:
            self._refused.setdefault(spec.detector_id, Counter())[refused.reason] += 1
            raise
        # After the rules: a rule-breaking finding must fail its check, not pass as a cap.
        self._check_limits(spec.detector_id)

        involved = self._involved_cells(anchor, input_refs, evidence_items)
        confidences = [
            c.extraction_confidence for c in involved if c.extraction_confidence is not None
        ]
        confidence = min(confidences) if confidences else None
        final_class = evidence_class
        if evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION:
            unverified = [c for c in involved if not self._verified(c)]
            if unverified:
                final_class = EvidenceClass.EXTRACTION_UNCERTAINTY
                evidence_items.append(self._downgrade_note(unverified, confidence))
            else:
                evidence_items.extend(self._caveats(involved, table_id))
        if evidence_class in SIGNAL_CLASSES:
            final_class = self._signal_policy(
                final_class, involved, confidence, table_id, evidence_items
            )

        issue = ValidationIssue(
            issue_id=self._ids.new(IdPrefix.ISSUE),
            fingerprint=fingerprint,
            evidence_digest=self._digest(
                observed_value, expected_value, anchor, input_refs, subject
            ),
            validation_run_id=self._run_id,
            document_id=self._document_id,
            dataset_id=self._dataset.dataset_id,
            dataset_revision=self._dataset.revision,
            table_id=table_id,
            row_id=row_id,
            affected_cells=anchor,
            input_cells=input_refs,
            detector_id=spec.detector_id,
            detector_version=spec.version,
            rule_id=rule_id,
            issue_category=category,
            severity=severity,
            evidence_class=final_class,
            title=title,
            explanation=explanation,
            observed_value=observed_value,
            expected_value=expected_value,
            evidence=evidence_items,
            suggested_action=suggested_action,
            estimated_financial_impact=financial_impact,
            extraction_confidence=confidence,
            anomaly_score=anomaly_score,
            created_at=self._clock.now(),
        )
        self._created[issue.issue_id] = issue
        self._content[issue.issue_id] = _content_digest(issue)
        self._fingerprints.add(fingerprint)
        self._by_detector.setdefault(spec.detector_id, []).append(issue.issue_id)
        self._total += 1
        return issue

    def _check_limits(self, detector_id: str) -> None:
        made = len(self._by_detector.get(detector_id, ()))
        if self._max_per_detector is not None and made >= self._max_per_detector:
            raise IssueLimitReached(
                f"Stopped at the limit of {self._max_per_detector:,} findings for this check."
            )
        if self._max_total is not None and self._total >= self._max_total:
            raise IssueLimitReached(
                f"Stopped at the limit of {self._max_total:,} findings for the whole run."
            )

    # ------------------------------------------------------------------ policy
    @staticmethod
    def _check_declared(
        spec: DetectorSpec,
        evidence_class: EvidenceClass,
        category: str,
        anomaly_score: AnomalyScore | None,
    ) -> None:
        if evidence_class not in spec.evidence_classes:
            raise IssuePolicyError(
                f"{spec.detector_id} does not declare evidence class {evidence_class.value!r}",
                reason=_UNDECLARED_CLASS,
            )
        if category not in spec.issue_categories:
            raise IssuePolicyError(
                f"{spec.detector_id} does not declare category {category!r}",
                reason=_UNDECLARED_CATEGORY,
            )
        if (
            anomaly_score is not None
            and anomaly_score.calibrated
            and anomaly_score.calibration_reference not in spec.calibration_references
        ):
            raise IssuePolicyError(
                f"{spec.detector_id}: calibrated scores must cite a calibration reference "
                "declared in the detector spec",
                reason=_UNCITED_CALIBRATION,
            )

    def _verified(self, cell: Cell) -> bool:
        return is_verified(cell, self._threshold)

    def _downgrade_note(self, unverified: list[Cell], confidence: float | None) -> EvidenceItem:
        places = ", ".join(c.source.describe() for c in unverified[:3])
        more = f" and {len(unverified) - 3} more" if len(unverified) > 3 else ""
        return EvidenceItem(
            kind=EvidenceKind.NOTE,
            label="Evidence downgraded",
            detail=(
                "The rule failed, but some input values were not extracted reliably "
                f"({places}{more}). Verify them in the source document before treating this "
                "as a confirmed error."
            ),
            data={
                "unverified_cells": len(unverified),
                "min_extraction_confidence": confidence,
                "threshold": self._threshold,
            },
        )

    def _signal_policy(
        self,
        evidence_class: EvidenceClass,
        involved: list[Cell],
        confidence: float | None,
        table_id: str | None,
        evidence_items: list[EvidenceItem],
    ) -> EvidenceClass:
        """The evidence policy for a signal: computed from any unverified cell, it becomes
        ``extraction_uncertainty`` with a downgrade note (the value may stand out only because
        it was misread); otherwise it keeps its class and gets the caveats. Appends the notes to
        ``evidence_items`` and returns the class the issue gets."""
        unverified = [c for c in involved if not self._verified(c)]
        if not unverified:
            evidence_items.extend(self._caveats(involved, table_id))
            return evidence_class
        places = ", ".join(c.source.describe() for c in unverified[:3])
        more = f" and {len(unverified) - 3} more" if len(unverified) > 3 else ""
        evidence_items.append(
            EvidenceItem(
                kind=EvidenceKind.NOTE,
                label="Evidence downgraded",
                detail=(
                    "The check found an unusual value, but some of the values it used were not "
                    f"extracted reliably ({places}{more}). Verify them in the source document "
                    "first: the difference may come from the extraction."
                ),
                data={
                    "unverified_cells": len(unverified),
                    "min_extraction_confidence": confidence,
                    "threshold": self._threshold,
                },
            )
        )
        return EvidenceClass.EXTRACTION_UNCERTAINTY

    def _caveats(self, involved: list[Cell], table_id: str | None) -> list[EvidenceItem]:
        notes: list[EvidenceItem] = []
        inferred = [c for c in involved if c.parse_status is ParseStatus.INFERRED]
        if inferred:
            detail = inferred[0].parse_note or "Formatting was inferred from document evidence."
            notes.append(
                EvidenceItem(
                    kind=EvidenceKind.NOTE,
                    label="Number format inferred",
                    detail=(
                        f"{len(inferred)} input value(s) were read using inferred formatting: "
                        f"{detail}"
                    ),
                    data={"inferred_cells": len(inferred)},
                )
            )
        codes = sorted({*self._review_tables.get(table_id, []), *self._review_tables.get(None, [])})
        if codes:
            notes.append(
                EvidenceItem(
                    kind=EvidenceKind.NOTE,
                    label="Extraction needs review",
                    detail=(
                        "The extraction of this table reported problems that a reviewer should "
                        f"check first ({', '.join(codes)})."
                    ),
                )
            )
        return notes

    # ------------------------------------------------------------------ resolution
    def _resolve(self, ref: CellRef) -> CellRef:
        cell = self._cell(ref)
        if ref.source == cell.source:
            return ref
        return CellRef(
            table_id=ref.table_id, row_id=ref.row_id, column_id=ref.column_id, source=cell.source
        )

    def _cell(self, ref: CellRef) -> Cell:
        table = self._dataset.table(ref.table_id)
        table.column(ref.column_id)  # raises NotFoundError for unknown columns
        cell = table.row(ref.row_id).cells.get(ref.column_id)
        if cell is None:
            raise NotFoundError(
                f"Cell {ref.key!r} does not exist in dataset {self._dataset.dataset_id!r}"
            )
        return cell

    def _resolve_evidence(self, item: EvidenceItem) -> EvidenceItem:
        cells = [self._resolve(ref) for ref in item.cells]
        calculation = item.calculation
        if calculation is not None and any(op.cell for op in calculation.operands):
            operands = [
                op.evolve(cell=self._resolve(op.cell)) if op.cell is not None else op
                for op in calculation.operands
            ]
            calculation = calculation.evolve(operands=operands)
        if cells == item.cells and calculation is item.calculation:
            return item
        return item.evolve(cells=cells, calculation=calculation)

    def _involved_cells(
        self, anchor: list[CellRef], inputs: list[CellRef], evidence: list[EvidenceItem]
    ) -> list[Cell]:
        refs: dict[tuple[str, str, str], CellRef] = {}
        for ref in _all_refs(anchor, inputs, evidence):
            refs.setdefault(ref.key, ref)
        return [self._cell(ref) for ref in refs.values()]

    def _anchor(
        self, table: Table | None, row: Row | None, anchor: list[CellRef]
    ) -> tuple[str | None, str | None]:
        table_id = table.table_id if table else (anchor[0].table_id if anchor else None)
        if anchor and any(ref.table_id != table_id for ref in anchor):
            raise IssuePolicyError(
                "All highlighted cells must belong to the issue's table", reason=_FOREIGN_CELLS
            )
        if row is not None:
            if table is not None and not table.has_row(row.row_id):
                raise IssuePolicyError(
                    "The issue's row does not belong to its table", reason=_FOREIGN_CELLS
                )
            return table_id, row.row_id
        row_ids = {ref.row_id for ref in anchor}
        return table_id, (row_ids.pop() if len(row_ids) == 1 else None)

    # ------------------------------------------------------------------ hashing
    def _fingerprint(
        self,
        detector_id: str,
        category: str,
        rule_id: str,
        table_id: str | None,
        row_id: str | None,
        anchor: Sequence[CellRef],
        key: str | None,
    ) -> str:
        location: list[str] = []
        if table_id is not None:
            table = self._dataset.table(table_id)
            location.append(f"table={table.source.sheet_index}:{table.name}")
            if row_id is not None:
                location.append(f"row={table.row(row_id).source_row_number}")
        location.extend(sorted(_coordinate(ref.source) for ref in anchor))
        material = "|".join([detector_id, category, rule_id, *location, key or ""])
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:32]

    def _digest(
        self,
        observed: str | None,
        expected: str | None,
        anchor: Sequence[CellRef],
        inputs: Sequence[CellRef],
        subject: str | None,
    ) -> str:
        parts = [observed or "", expected or "", subject or ""]
        for ref in sorted({*anchor, *inputs}, key=lambda r: _coordinate(r.source)):
            cell = self._cell(ref)
            parts.append(
                f"{_coordinate(ref.source)}={cell.raw_value!r}/"
                f"{value_to_display(cell.normalized_value)!r}"
            )
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:32]


def _check_evidence_rule(
    spec: DetectorSpec,
    rule_id: str,
    evidence_class: EvidenceClass,
    evidence: Sequence[EvidenceItem],
    cells: Sequence[CellRef],
    row: Row | None,
) -> None:
    if not evidence:
        raise IssuePolicyError(
            f"{spec.detector_id}: a finding of rule {rule_id!r} has no evidence; every finding "
            "needs at least one evidence item",
            reason=NO_EVIDENCE,
        )
    if evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION and not cells and row is None:
        raise IssuePolicyError(
            f"{spec.detector_id}: a confirmed rule violation of rule {rule_id!r} points at no "
            "cell and no row; highlight the cells or pass the row where the rule failed",
            reason=CONFIRMED_WITHOUT_PLACE,
        )


def evidence_rule_problem(issue: ValidationIssue) -> str | None:
    """Why a finished issue breaks the evidence rule (:data:`NO_EVIDENCE`,
    :data:`CONFIRMED_WITHOUT_PLACE`), or ``None``. The factory enforces the rule when it
    creates an issue; the pipeline checks every returned finding again with this function."""
    if not issue.evidence:
        return NO_EVIDENCE
    if (
        issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
        and not issue.affected_cells
        and issue.row_id is None
    ):
        return CONFIRMED_WITHOUT_PLACE
    return None


def _coordinate(source: SourceLocation | None) -> str:
    if source is None:
        return "?"
    return (
        f"{source.kind.value}:{source.sheet_index}:{source.page_number}:"
        f"{source.row_number}:{source.column_number}"
    )


def _all_refs(
    anchor: Iterable[CellRef], inputs: Iterable[CellRef], evidence: Iterable[EvidenceItem]
) -> Iterable[CellRef]:
    yield from anchor
    yield from inputs
    for item in evidence:
        yield from item.cells
        if item.calculation is not None:
            yield from (op.cell for op in item.calculation.operands if op.cell is not None)


def money_impact(
    amount: Decimal,
    currency: str,
    basis: str,
    *,
    reported: Decimal | None = None,
    recomputed: Decimal | None = None,
    kind: Literal["discrepancy", "potential_double_count", "reference_deviation"] = "discrepancy",
) -> FinancialImpact:
    """Convenience constructor used by reconciliation detectors. ``currency`` must be an
    explicit currency (``ValidationContext.currency_evidence``); without one, leave the
    impact out: an amount in an unknown currency cannot be added to anything."""
    return FinancialImpact(
        amount=amount,
        currency=currency,
        basis=basis,
        reported=reported,
        recomputed=recomputed,
        kind=kind,
    )


def _content_digest(issue: ValidationIssue) -> str:
    return hashlib.sha256(issue.model_dump_json().encode("utf-8")).hexdigest()
