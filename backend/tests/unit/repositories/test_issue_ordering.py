"""Issue ordering, paging and iteration on both adapters.

Order: spelling and text-style findings after every other finding, then severity (critical
first), then the first affected cell's source position: sheet index
(issues without a location last), row number (a table-level location without a row leads its
sheet), column number (no column leads its row); findings at the same place by detector id,
rule id and fingerprint (stored content, the same in every run of the same data), copies of one
finding from several runs by insertion order, and only then by the (random) issue id.
"""

from __future__ import annotations

import pytest

from app.core.errors import InvalidInputError
from app.models.dataset import CellRef, Dataset, RowKind
from app.models.issue import EvidenceClass, EvidenceItem, EvidenceKind, IssueCategory, Severity
from app.models.profile import DomainProfile
from app.repositories.base import IssueQuery, UnitOfWorkFactory
from app.repositories.errors import UnitOfWorkError
from app.repositories.sql import issues as sql_issues
from tests.support.builders import make_context
from tests.unit.repositories.samples import PROBE_SPEC, cell_at, make_issue, make_run

HIGH = Severity.HIGH

# Stored in this (shuffled) order; EXPECTED_ORDER is the order query() must return.
POSITIONED = [
    make_issue("iss_k", severity=Severity.LOW, cells=[cell_at(0, 2, 1)]),
    make_issue("iss_e", severity=HIGH, cells=[cell_at(1, 1, 1)]),  # second sheet
    make_issue("iss_b", severity=HIGH, cells=[cell_at(0, 3, 4)]),
    # Four findings on one cell (as when two detectors report the same defect's cell): the
    # detector, then the rule, then the fingerprint decide, never the issue id.
    make_issue("iss_c", severity=HIGH, cells=[cell_at(0, 3, 1)], fingerprint="fp_2"),
    make_issue("iss_h", severity=HIGH, cells=[cell_at(0, 3, 1)], fingerprint="fp_1"),
    make_issue(
        "iss_j", severity=HIGH, cells=[cell_at(0, 3, 1)], rule_id="a_rule", fingerprint="fp_3"
    ),
    make_issue(
        "iss_l",
        severity=HIGH,
        cells=[cell_at(0, 3, 1)],
        detector_id="test.aardvark",
        fingerprint="fp_4",
    ),
    make_issue("iss_i", severity=HIGH, cells=[cell_at(0, 3, None)]),  # whole row 3
    make_issue("iss_d", severity=HIGH, cells=[cell_at(0, None, None)]),  # table-level location
    make_issue(
        "iss_g",
        severity=HIGH,
        cells=[CellRef(table_id="tbl_000001", row_id="row_000001", column_id="col_000001")],
        fingerprint="fp_5",
    ),  # a cell without a source location
    make_issue("iss_f", severity=HIGH, cells=[], fingerprint="fp_6"),  # no location at all
    make_issue("iss_a", severity=Severity.CRITICAL, cells=[cell_at(2, 9, 9)]),
]
EXPECTED_ORDER = [
    "iss_a",  # critical first, wherever it is
    "iss_d",  # table-level: leads sheet 0
    "iss_i",  # row 3 without a column leads row 3
    "iss_l",  # row 3, column 1: detector test.aardvark before test.alpha ...
    "iss_j",  # ... then rule a_rule before default ...
    "iss_h",  # ... then fingerprint fp_1 before fp_2, although iss_c has the smaller id
    "iss_c",
    "iss_b",  # row 3, column 4
    "iss_e",  # sheet 1 after sheet 0
    "iss_g",  # no location: after the located issues of the same severity, by fingerprint
    "iss_f",
    "iss_k",  # low last
]


def _store(factory: UnitOfWorkFactory, issues) -> None:
    with factory() as uow:
        uow.runs.add(make_run())
        uow.issues.add_many(issues)


def _query_ids(factory: UnitOfWorkFactory, **paging) -> list[str]:
    with factory() as uow:
        return [
            i.issue_id for i in uow.issues.query(IssueQuery(run_id="run_000001"), **paging).items
        ]


def test_query_orders_by_severity_then_source_position(uow_factory: UnitOfWorkFactory) -> None:
    _store(uow_factory, POSITIONED)
    assert _query_ids(uow_factory) == EXPECTED_ORDER


def test_spelling_and_text_style_findings_come_after_every_other_finding(
    uow_factory: UnitOfWorkFactory,
) -> None:
    info = make_issue("iss_k", severity=Severity.INFO, cells=[cell_at(0, 9, 1)])
    findings = [
        make_issue(
            "iss_m", severity=HIGH, cells=[cell_at(0, 1, 1)], detector_id="domain.boq_typos"
        ),
        make_issue(
            "iss_n",
            severity=Severity.MEDIUM,
            cells=[cell_at(0, 1, 1)],
            detector_id="domain.boq_description_clarity",
            rule_id="short_text_only",
        ),
        make_issue(
            "iss_o",
            severity=Severity.LOW,
            cells=[cell_at(0, 1, 1)],
            detector_id="domain.boq_description_clarity",
            rule_id="open_scope",
        ),
    ]
    _store(uow_factory, [*findings, info])
    # Another rule of the check that has short_text_only keeps its severity's place.
    assert _query_ids(uow_factory) == ["iss_o", "iss_k", "iss_m", "iss_n"]


def test_factory_issues_follow_sheet_row_and_column_of_their_first_cell(
    uow_factory: UnitOfWorkFactory, boq_profile: DomainProfile, dataset: Dataset
) -> None:
    context = make_context(dataset, boq_profile)
    bill, preliminaries = dataset.tables
    first, second = [row for row in bill.rows if row.kind is RowKind.ITEM]
    extra = preliminaries.rows[0]

    def finding(table, row, field: str, severity: Severity):
        return context.issues.create(
            PROBE_SPEC,
            rule_id="probe",
            category=IssueCategory.ARITHMETIC,
            severity=severity,
            evidence_class=EvidenceClass.CONFIRMED_RULE_VIOLATION,
            title="Probe finding",
            explanation="Created by the ordering test.",
            table=table,
            evidence=[EvidenceItem(kind=EvidenceKind.NOTE, label="Probe", detail="Probe.")],
            row=row,
            cells=[context.cell_ref(table, row, field)],
        )

    later_row = finding(bill, second, "line_total", HIGH)  # sheet 0, row 4, column 6
    first_row = finding(bill, first, "line_total", HIGH)  # sheet 0, row 3, column 6
    left_column = finding(bill, first, "quantity", HIGH)  # sheet 0, row 3, column 3
    second_sheet = finding(preliminaries, extra, "line_total", HIGH)  # sheet 1
    critical = finding(preliminaries, extra, "item_code", Severity.CRITICAL)
    table_level = context.issues.create(  # a table-level finding without highlighted cells
        PROBE_SPEC,
        rule_id="probe",
        category=IssueCategory.MISSING_VALUE,
        severity=HIGH,
        evidence_class=EvidenceClass.NEEDS_EXTERNAL_CONTEXT,
        title="Required column missing",
        explanation="Created by the ordering test.",
        table=bill,
        evidence=[EvidenceItem(kind=EvidenceKind.NOTE, label="Probe", detail="Probe.")],
        subject="unit_price",
    )
    _store(uow_factory, [later_row, table_level, second_sheet, critical, first_row, left_column])
    expected = [critical, left_column, first_row, later_row, second_sheet, table_level]
    assert _query_ids(uow_factory) == [issue.issue_id for issue in expected]


def test_text_is_ordered_by_code_point_on_every_backend(uow_factory: UnitOfWorkFactory) -> None:
    # By code point "q.min" < "q_min" < "qmin"; natural-language collations (PostgreSQL's
    # en_US, ICU) put "_" before "." or ignore punctuation, which the SQL adapter overrides.
    rules = ["qmin", "q_min", "q.min"]
    _store(
        uow_factory,
        [
            make_issue(f"iss_{n}", cells=[cell_at(0, 3, 1)], rule_id=rule, fingerprint=f"fp_{n}")
            for n, rule in enumerate(rules)
        ],
    )
    with uow_factory() as uow:
        found = [issue.rule_id for issue in uow.issues.query(IssueQuery()).items]
    assert found == sorted(rules) == ["q.min", "q_min", "qmin"]


def test_copies_of_one_finding_from_several_runs_follow_their_insertion_order(
    uow_factory: UnitOfWorkFactory,
) -> None:
    # The same finding (same place, detector, rule and fingerprint) in two runs of a dataset:
    # the copy stored first leads, whatever the issue ids say.
    for run_id, issue_id in (("run_000001", "iss_z"), ("run_000002", "iss_a")):
        with uow_factory() as uow:
            uow.runs.add(make_run(run_id))
            uow.issues.add_many(
                [make_issue(issue_id, run_id=run_id, cells=[cell_at(0, 3, 1)], fingerprint="fp")]
            )
    with uow_factory() as uow:
        found = uow.issues.query(IssueQuery(dataset_id="ds_000001")).items
    assert [issue.issue_id for issue in found] == ["iss_z", "iss_a"]


def test_pages_partition_the_ordered_matches(uow_factory: UnitOfWorkFactory) -> None:
    _store(uow_factory, POSITIONED)
    with uow_factory() as uow:
        pages = [uow.issues.query(IssueQuery(), offset=o, limit=5) for o in (0, 5, 10, 15)]
        counted_only = uow.issues.query(IssueQuery(), limit=0)
    assert [page.total for page in pages] == [12, 12, 12, 12]
    assert [len(page.items) for page in pages] == [5, 5, 2, 0]
    assert [i.issue_id for page in pages for i in page.items] == EXPECTED_ORDER
    assert (counted_only.items, counted_only.total) == ([], 12)


def test_iter_all_yields_every_match_in_query_order_across_batches(
    uow_factory: UnitOfWorkFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sql_issues, "ITER_BATCH_SIZE", 3)  # several SQL batches
    _store(uow_factory, POSITIONED)
    with uow_factory() as uow:
        everything = list(uow.issues.iter_all(IssueQuery()))
        high = [i.issue_id for i in uow.issues.iter_all(IssueQuery(severities=frozenset({HIGH})))]
    assert [issue.issue_id for issue in everything] == EXPECTED_ORDER
    assert everything == sorted(POSITIONED, key=lambda i: EXPECTED_ORDER.index(i.issue_id))
    assert high == EXPECTED_ORDER[1:-1]


def test_iter_all_must_be_consumed_inside_the_unit_of_work(
    uow_factory: UnitOfWorkFactory,
) -> None:
    _store(uow_factory, POSITIONED)
    with uow_factory() as uow:
        iterator = uow.issues.iter_all(IssueQuery())
    with pytest.raises(UnitOfWorkError):
        next(iterator)


def test_iter_all_cannot_be_continued_after_the_unit_of_work(
    uow_factory: UnitOfWorkFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sql_issues, "ITER_BATCH_SIZE", 3)
    _store(uow_factory, POSITIONED)
    with uow_factory() as uow:
        iterator = uow.issues.iter_all(IssueQuery())
        first = next(iterator)  # the rest of its SQL batch is already loaded
    assert first.issue_id == EXPECTED_ORDER[0]
    with pytest.raises(UnitOfWorkError):
        next(iterator)


@pytest.mark.parametrize(("offset", "limit"), [(-1, 10), (0, -5)])
def test_negative_paging_is_refused(
    uow_factory: UnitOfWorkFactory, offset: int, limit: int
) -> None:
    with uow_factory() as uow, pytest.raises(InvalidInputError):
        uow.issues.query(IssueQuery(), offset=offset, limit=limit)
