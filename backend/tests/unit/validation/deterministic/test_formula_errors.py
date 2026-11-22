"""deterministic.formula_errors: error values, missing formula results, external links."""

from __future__ import annotations

import time

import pytest

from app.core.errors import DetectorConfigError
from app.models import cell_rules
from app.models.dataset import FormulaInfo, RowKind
from app.models.issue import EvidenceClass, EvidenceKind, Severity
from app.models.run import DetectorExecutionStatus, RunStatus
from app.models.source import SourceKind, SourceLocation
from app.validation.contracts.conditions import Coverage
from app.validation.deterministic.formula_errors import (
    MAX_FORMULA_CHARS,
    FormulaErrorsDetector,
    links_other_workbook,
)
from app.validation.registry.registry import DetectorRegistry
from tests.support.builders import (
    DatasetBuilder,
    ambiguous_cell,
    error_cell,
    number_cell,
    unavailable_formula_cell,
)
from tests.unit.validation.deterministic.references_fixtures import (
    BOQ_COLUMNS,
    LARGE_ROWS,
    applicability,
    assert_unique_fingerprints,
    assert_well_formed,
    by_rule,
    large_boq_dataset,
    resolve,
    run,
    run_pipeline,
)

DETECTOR = FormulaErrorsDetector
ERROR_LITERALS = [
    "#REF!",
    "#DIV/0!",
    "#VALUE!",
    "#NAME?",
    "#N/A",
    "#NUM!",
    "#NULL!",
    "#SPILL!",
    "#CALC!",
    "#GETTING_DATA",
]
_SOURCE = SourceLocation(kind=SourceKind.SPREADSHEET, sheet_index=0, row_number=1, column_number=1)


def linked_number(value: str, formula: str):
    return number_cell(value, formula=formula)


def linked_text(text: str, formula: str):
    return cell_rules.text_cell(
        text, _SOURCE, formula=FormulaInfo(expression=formula, cached_result_available=True)
    )


def item(code: str, total, *, price="10.00", description="Aushub Baugrube", qty="2"):
    return [code, description, qty, "m3", price, total]


def dataset_with(profile, rows, *, columns=BOQ_COLUMNS, name="LV"):
    builder = DatasetBuilder(profile)
    table = builder.table(name, columns)
    for values, kind in rows:
        table.row(values, kind=kind)
    return builder.build()


class TestErrorValues:
    @pytest.mark.parametrize("code", ERROR_LITERALS)
    def test_every_error_literal_is_a_confirmed_violation(self, boq_profile, code) -> None:
        dataset = dataset_with(
            boq_profile,
            [(item("01.0010", error_cell(code, formula="=C2*E2")), RowKind.ITEM)],
        )
        result = run(DETECTOR, dataset, boq_profile)
        [issue] = result.issues
        assert issue.rule_id == "formula_error"
        assert issue.evidence_class is EvidenceClass.CONFIRMED_RULE_VIOLATION
        assert issue.severity is Severity.HIGH
        assert issue.title == f"Formula error {code} in Line total"
        assert issue.observed_value == code
        assert "'LV' row 2" in issue.explanation
        value = next(e for e in issue.evidence if e.kind is EvidenceKind.VALUE)
        assert value.data == {"error_code": code, "formula": "=C2*E2"}
        assert issue.affected_cells[0].source.a1 == "F2"
        assert result.coverage["error_cells"] == 1
        assert_well_formed(result.issues)

    def test_known_codes_are_explained(self, boq_profile) -> None:
        dataset = dataset_with(boq_profile, [(item("1", error_cell("#DIV/0!")), RowKind.ITEM)])
        [issue] = run(DETECTOR, dataset, boq_profile).issues
        assert "division by zero" in issue.explanation
        assert "division by zero" in issue.suggested_action

    def test_errors_in_every_column_and_row_kind(self, boq_profile) -> None:
        columns = [*BOQ_COLUMNS, ("Bemerkung", None), (None, None)]
        dataset = dataset_with(
            boq_profile,
            [
                ([*item("1", "20.00"), error_cell("#N/A"), error_cell("#REF!")], RowKind.ITEM),
                (
                    [None, "Summe Titel 1", None, None, None, error_cell("#VALUE!"), None, None],
                    RowKind.SUBTOTAL,
                ),
            ],
            columns=columns,
        )
        issues = run(DETECTOR, dataset, boq_profile).issues
        titles = sorted(i.title for i in issues)
        assert titles == [
            "Formula error #N/A in column 'Bemerkung'",
            "Formula error #REF! in column H",
            "Formula error #VALUE! in Line total",
        ]
        assert_unique_fingerprints(issues)

    def test_cells_of_one_column_and_code_are_grouped_beyond_the_cap(self, boq_profile) -> None:
        rows = [(item(f"{n}", error_cell("#REF!")), RowKind.ITEM) for n in range(1, 6)]
        rows.append((item("6", error_cell("#DIV/0!")), RowKind.ITEM))
        dataset = dataset_with(boq_profile, rows)
        issues = run(DETECTOR, dataset, boq_profile, {"max_cells_per_issue": 3}).issues
        grouped = [i for i in issues if len(i.affected_cells) > 1]
        [group] = grouped
        assert group.title == "5 cells in Line total show formula error #REF!"
        assert group.row_id is None and len(group.affected_cells) == 3
        assert group.evidence[0].data["cells"] == 5
        assert "'LV' rows 2, 3, 4, 5 and 6" in group.explanation
        singles = [i for i in issues if len(i.affected_cells) == 1]
        assert [i.observed_value for i in singles] == ["#DIV/0!"]
        assert_unique_fingerprints(issues)

    def test_up_to_the_cap_every_cell_is_its_own_finding(self, boq_profile) -> None:
        rows = [(item(f"{n}", error_cell("#REF!")), RowKind.ITEM) for n in range(1, 4)]
        dataset = dataset_with(boq_profile, rows)
        issues = run(DETECTOR, dataset, boq_profile).issues
        assert len(issues) == 3
        assert [i.row_id for i in issues] == [r.row_id for r in dataset.tables[0].rows]
        assert all(len(i.affected_cells) == 1 for i in issues)
        assert_unique_fingerprints(issues)


class TestUnavailableResults:
    def test_per_cell_extraction_uncertainty(self, boq_profile) -> None:
        dataset = dataset_with(
            boq_profile, [(item("1", unavailable_formula_cell("=C2*E2")), RowKind.ITEM)]
        )
        result = run(DETECTOR, dataset, boq_profile)
        [issue] = result.issues
        assert issue.rule_id == "formula_result_unavailable"
        assert issue.evidence_class is EvidenceClass.EXTRACTION_UNCERTAINTY
        assert issue.severity is Severity.MEDIUM
        assert issue.title == "Formula result not stored in the file: Line total"
        assert "=C2*E2" in issue.explanation
        assert issue.evidence[0].data == {"formula": "=C2*E2"}
        assert "save it so the formula results are stored" in issue.suggested_action
        assert result.coverage["unavailable_cells"] == 1

    def test_grouped_per_column_beyond_the_cap(self, boq_profile) -> None:
        rows = [
            (item(f"{n}", unavailable_formula_cell(f"=C{n}*E{n}")), RowKind.ITEM)
            for n in range(1, 5)
        ]
        issues = run(
            DETECTOR, dataset_with(boq_profile, rows), boq_profile, {"max_cells_per_issue": 2}
        ).issues
        [issue] = issues
        assert issue.title == "Formula results not stored in the file: 4 cells in Line total"
        assert len(issue.affected_cells) == 2 and issue.evidence[0].data["cells"] == 4


class TestExternalReferences:
    LINKED = [
        "=[1]Sheet1!A1",
        "='C:\\path\\[Book.xlsx]Sheet'!A1",
        "=[Book.xlsx]Sheet!A1",
        "='https://host/[Book.xlsx]Sheet'!A1",
        "=ROUND([1]Preise!C4*D7,2)",
        "=SUM('[2]Los 2'!F2:F40)+F3",
    ]
    NOT_LINKED = [
        '="[x]"',
        '="[1]Sheet1!A1"',
        "=SUM(Table1[Amount])+Sheet2!A1",
        "=[@Qty]*[@Price]",
        "='Sheet 1'!A1*2",
        "=R[1]C[2]",
        "=C2*E2",
    ]

    @pytest.mark.parametrize("formula", LINKED)
    def test_links_are_recognised(self, formula) -> None:
        assert links_other_workbook(formula)

    @pytest.mark.parametrize("formula", NOT_LINKED)
    def test_lookalikes_are_not_links(self, formula) -> None:
        assert not links_other_workbook(formula)

    def test_grouped_per_column_as_needing_external_context(self, boq_profile) -> None:
        rows = [
            (item(f"{n}", linked_number("20.00", formula)), RowKind.ITEM)
            for n, formula in enumerate(self.LINKED, start=1)
        ]
        rows += [
            (item("90", linked_number("20.00", formula)), RowKind.ITEM)
            for formula in self.NOT_LINKED
        ]
        linked_description = item("99", "20.00")
        linked_description[1] = linked_text("Aushub", "=[1]S!A1")
        rows.append((linked_description, RowKind.ITEM))
        result = run(DETECTOR, dataset_with(boq_profile, rows), boq_profile)
        issues = by_rule(result.issues, "external_reference")
        assert sorted(i.title for i in issues) == [
            "1 value in Description is computed from another workbook",
            f"{len(self.LINKED)} values in Line total are computed from another workbook",
        ]
        line_total = next(i for i in issues if "Line total" in i.title)
        assert line_total.evidence_class is EvidenceClass.NEEDS_EXTERNAL_CONTEXT
        assert line_total.severity is Severity.LOW
        assert len(line_total.affected_cells) == len(self.LINKED)
        assert "cannot be verified" in line_total.explanation
        assert result.coverage["external_reference_cells"] == len(self.LINKED) + 1
        assert len(result.issues) == 2
        assert_unique_fingerprints(result.issues)

    def test_switched_off_by_the_profile(self, boq_profile) -> None:
        rows = [(item("1", linked_number("20.00", "=[1]Sheet1!A1")), RowKind.ITEM)]
        result = run(
            DETECTOR,
            dataset_with(boq_profile, rows),
            boq_profile,
            {"flag_external_references": False},
        )
        assert result.issues == []

    def test_error_and_unavailable_cells_are_reported_once(self, boq_profile) -> None:
        rows = [
            (item("1", error_cell("#REF!", formula="=[1]Sheet1!A1")), RowKind.ITEM),
            (item("2", unavailable_formula_cell("=[1]Sheet1!A2")), RowKind.ITEM),
        ]
        issues = run(DETECTOR, dataset_with(boq_profile, rows), boq_profile).issues
        assert sorted(i.rule_id for i in issues) == ["formula_error", "formula_result_unavailable"]
        for issue in issues:
            assert any(e.label == "Formula refers to another workbook" for e in issue.evidence)

    def test_cells_owned_by_data_type_conformance_are_left_to_it(self, boq_profile) -> None:
        ambiguous = cell_rules.ambiguous_cell(
            "1.234",
            _SOURCE,
            "Decimal separator is ambiguous.",
            formula=FormulaInfo(expression="=[1]S!A1", cached_result_available=True),
        )
        rows = [
            (item("1", ambiguous), RowKind.ITEM),
            (item("2", ambiguous_cell("2.345")), RowKind.ITEM),
        ]
        assert run(DETECTOR, dataset_with(boq_profile, rows), boq_profile).issues == []

    def test_overlong_formulas_are_counted_not_scanned(self, boq_profile) -> None:
        formula = "=[1]S!A1+" + "1+" * MAX_FORMULA_CHARS
        rows = [(item("1", linked_number("20.00", formula)), RowKind.ITEM)]
        result = run(DETECTOR, dataset_with(boq_profile, rows), boq_profile)
        assert result.issues == []
        assert result.coverage["formulas_not_scanned_too_long"] == 1
        assert any("not scanned" in note for note in result.notes)

    def test_hostile_formula_text_is_fast(self) -> None:
        hostile = ["=" + "[" * 100_000, "=" + "'" * 100_001 + "!", "=" + '"' * 99_999 + "[1]S!A1"]
        hostile.append("=" + "Table1[[#This Row],[Qty]]*" * 4000 + "S!A1")
        started = time.perf_counter()
        for formula in hostile:
            links_other_workbook(formula)
        assert time.perf_counter() - started < 1.0


class TestCleanDataAndCoverage:
    def test_clean_data_has_no_findings(self, boq_profile) -> None:
        rows = [
            (item("01.0010", number_cell("20.00", formula="=C2*E2")), RowKind.ITEM),
            (["01", "Erdarbeiten", None, None, None, None], RowKind.SECTION),
            (item("01.0020", "30.00", qty="3"), RowKind.ITEM),
            ([None, None, None, None, None, None], RowKind.BLANK),
        ]
        result = run(DETECTOR, dataset_with(boq_profile, rows), boq_profile)
        assert result.issues == []
        assert result.coverage[Coverage.ROWS_CHECKED] == 4
        assert result.coverage[Coverage.CELLS_CHECKED] == 24
        assert result.coverage["formula_cells"] == 1
        assert "error_cells" not in result.coverage

    def test_excluded_rows_are_not_inspected(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        table = builder.table("LV", BOQ_COLUMNS)
        table.row(item("1", error_cell("#REF!")), excluded=True)
        table.row(item("2", "20.00"))
        result = run(DETECTOR, builder.build(), boq_profile)
        assert result.issues == []
        assert result.coverage[Coverage.ROWS_CHECKED] == 1

    def test_empty_table(self, boq_profile) -> None:
        builder = DatasetBuilder(boq_profile)
        builder.table("LV", BOQ_COLUMNS)
        result = run(DETECTOR, builder.build(), boq_profile)
        assert result.issues == [] and result.coverage == {}

    def test_generic_profile_and_unmapped_columns(self, generic_profile) -> None:
        builder = DatasetBuilder(generic_profile)
        table = builder.table("Data", [("A", None), ("B", None)])
        table.row(["1", error_cell("#NAME?", formula="=FOO(A2)")])
        dataset = builder.build()
        assert applicability(DETECTOR, dataset, generic_profile).applicable
        [issue] = run(DETECTOR, dataset, generic_profile).issues
        assert issue.title == "Formula error #NAME? in column 'B'"


class TestConfig:
    def test_defaults_and_boq_profile(self, boq_profile) -> None:
        registry = DetectorRegistry([DETECTOR])
        config = registry.resolve_config(
            DETECTOR.spec.detector_id,
            [boq_profile.detector_defaults.get(DETECTOR.spec.detector_id, {})],
        )
        assert config.flag_external_references is True
        assert config.severity is Severity.HIGH and config.max_cells_per_issue == 50
        assert registry.describe(DETECTOR.spec.detector_id).plannable_parameters == [
            "max_cells_per_issue",
            "severity",
        ]

    @pytest.mark.parametrize(
        "overrides",
        [
            {"unknown": 1},
            {"max_cells_per_issue": 0},
            {"severity": "fatal"},
            {"max_cells_per_issue": "x"},
        ],
    )
    def test_invalid_parameters_are_rejected(self, boq_profile, overrides) -> None:
        with pytest.raises(DetectorConfigError):
            resolve(DETECTOR, boq_profile, overrides)


class TestIdentityAndIntegration:
    def _dataset(self, profile, offset: int = 0):
        builder = DatasetBuilder(profile)
        for _ in range(offset):  # shift every generated id, as a re-normalization would
            builder.ids.new("row"), builder.ids.new("col"), builder.ids.new("tbl")
        table = builder.table("LV", BOQ_COLUMNS)
        for n in range(1, 5):
            table.row(item(str(n), error_cell("#REF!")))
        table.row(item("5", unavailable_formula_cell()))
        table.row(item("6", linked_number("20.00", "=[1]S!A1")))
        return builder.build()

    def test_fingerprints_are_stable_and_distinct(self, boq_profile) -> None:
        overrides = {"max_cells_per_issue": 2}
        first = run(DETECTOR, self._dataset(boq_profile), boq_profile, overrides).issues
        again = run(DETECTOR, self._dataset(boq_profile), boq_profile, overrides).issues
        shifted = run(DETECTOR, self._dataset(boq_profile, 7), boq_profile, overrides).issues
        assert len(first) == 3  # grouped errors, one unavailable result, one link group
        assert [i.fingerprint for i in first] == [i.fingerprint for i in again]
        assert [i.fingerprint for i in first] == [i.fingerprint for i in shifted]
        assert_unique_fingerprints(first)

    def test_discovered_in_the_deterministic_package(self) -> None:
        registry = DetectorRegistry.from_packages(["app.validation.deterministic"])
        assert DETECTOR.spec.detector_id in registry.ids()

    def test_baseline_pipeline_run(self, boq_profile) -> None:
        outcome = run_pipeline(DETECTOR, self._dataset(boq_profile), boq_profile)
        [report] = outcome.reports
        assert report.status is DetectorExecutionStatus.COMPLETED
        assert outcome.status is RunStatus.COMPLETED
        assert report.issues_found == len(outcome.issues) == 6
        assert report.coverage["error_cells"] == 4

    @pytest.mark.performance
    def test_twenty_thousand_rows_are_fast(self, boq_profile) -> None:
        dataset = large_boq_dataset(boq_profile)
        started = time.perf_counter()
        result = run(DETECTOR, dataset, boq_profile)
        assert time.perf_counter() - started < 5.0
        assert len(result.issues) == 20  # 20 cells with #REF! stay below the cap of 50
        assert result.coverage["formula_cells"] == LARGE_ROWS
        assert result.coverage[Coverage.ROWS_CHECKED] == LARGE_ROWS
