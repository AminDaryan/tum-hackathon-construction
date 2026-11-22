"""Finding categories: every registered detector has an entry, a rule's entry wins over its
detector's, and the evidence class never changes the category."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

import pytest

from app.agents.bill_review import PASSES
from app.core.config import Settings
from app.models.finding_category import (
    CATEGORY_BY_DETECTOR,
    CATEGORY_BY_RULE,
    FINDING_CATEGORY_ORDER,
    FindingCategory,
    FindingCategoryKey,
    finding_category_of,
)
from app.models.issue import EvidenceClass
from app.services.bill_reviews import REVIEW_PASSES
from app.validation.contracts.detector import DetectorSpec
from app.validation.contracts.scopes import Outcome
from app.validation.deterministic._totals_support import _EVIDENCE, _RULE_SUFFIX
from app.validation.deterministic.data_type_conformance import (
    RULE_AMBIGUOUS,
    DataTypeConformanceDetector,
)
from app.validation.deterministic.formula_errors import RULE_UNAVAILABLE, FormulaErrorsDetector
from app.validation.deterministic.grand_total import (
    GRAND_TOTAL_PREFIX,
    GROSS_TOTAL_PREFIX,
    GrandTotalDetector,
)
from app.validation.deterministic.hierarchy import RULE_ITEM, RULE_ORDER, RULE_SECTION
from app.validation.deterministic.subtotal import SUBTOTAL_PREFIX, SubtotalDetector
from app.validation.deterministic.unit_compatibility import (
    RULE_SAME_DESCRIPTION,
    UnitCompatibilityDetector,
)
from app.validation.domain.boq import bid_prices, clauses, tender_comparison
from app.validation.domain.boq.description_clarity import (
    RULE_OPEN_DECISION,
    BoqDescriptionClarityDetector,
)
from app.validation.domain.boq.numbering import RULE_MISPLACED, BoqNumberingDetector
from app.validation.registry.discovery import discover
from app.validation.semantic.bill_review import BillReviewDetector, rule_id_of

UNIT_COMPATIBILITY = UnitCompatibilityDetector.spec.detector_id
FORMULA_ERRORS = FormulaErrorsDetector.spec.detector_id
DATA_TYPES = DataTypeConformanceDetector.spec.detector_id
SUBTOTAL = SubtotalDetector.spec.detector_id
GRAND_TOTAL = GrandTotalDetector.spec.detector_id
BID_PRICES = bid_prices.BoqBidPricesDetector.spec.detector_id
CLAUSES = clauses.BoqClausesDetector.spec.detector_id
TENDER_COMPARISON = tender_comparison.TenderComparisonDetector.spec.detector_id
CLARITY = BoqDescriptionClarityDetector.spec.detector_id
NUMBERING = BoqNumberingDetector.spec.detector_id
REVIEW = BillReviewDetector.spec.detector_id
ERROR = FindingCategory.ERROR
AMBIGUITY = FindingCategory.AMBIGUITY
# The rule prefixes the totals checks give TotalReporter (subtotal.py, grand_total.py).
TOTAL_RULE_PREFIXES = {
    SUBTOTAL: (SUBTOTAL_PREFIX,),
    GRAND_TOTAL: (GRAND_TOTAL_PREFIX, GROSS_TOTAL_PREFIX),
}
# The outcomes the totals checks report as extraction_uncertainty: rows that cannot be told
# apart, and a difference that only the rounding of displayed values explains.
READING_OUTCOMES = (Outcome.AMBIGUOUS_STRUCTURE, Outcome.DISPLAY_ROUNDING)
# The checks that report extraction_uncertainty themselves, as reviewed for the categories on
# 2026-11-21. Each one's reading rules map to None (or, for extraction quality, the whole check);
# reference integrity keeps Ambiguity, as its evidence class says the reference may be among the
# unreadable identifiers. A new check that claims the class must be reviewed and added here.
REVIEWED_READING_CHECKS = {
    "deterministic.extraction_quality",
    FORMULA_ERRORS,
    SUBTOTAL,
    GRAND_TOTAL,
    DATA_TYPES,
    "deterministic.reference_integrity",
}
DATA_MODEL = Path(__file__).resolve().parents[4] / "docs" / "architecture" / "data-model.md"


def registered_specs() -> list[DetectorSpec]:
    """The detectors the application registers: discovery over its configured packages."""
    found = discover(Settings().detector_packages)
    assert not found.unavailable, f"detector modules that did not load: {found.unavailable}"
    assert found.detectors
    return [detector.spec for detector in found.detectors]


def registered_detector_ids() -> set[str]:
    return {spec.detector_id for spec in registered_specs()}


def _reading_rules() -> set[tuple[str, str]]:
    """The rules the checks report as extraction_uncertainty, from their own constants."""
    totals = {
        (detector_id, f"{prefix}_{_RULE_SUFFIX[outcome]}")
        for detector_id, prefixes in TOTAL_RULE_PREFIXES.items()
        for prefix in prefixes
        for outcome in READING_OUTCOMES
    }
    return totals | {(FORMULA_ERRORS, RULE_UNAVAILABLE), (DATA_TYPES, RULE_AMBIGUOUS)}


def test_every_registered_detector_has_an_entry() -> None:
    missing = sorted(registered_detector_ids() - set(CATEGORY_BY_DETECTOR))
    assert not missing, f"detectors without an entry in CATEGORY_BY_DETECTOR: {missing}"


def test_every_entry_names_a_registered_detector() -> None:
    registered = registered_detector_ids()
    assert sorted(set(CATEGORY_BY_DETECTOR) - registered) == []
    assert sorted({detector for detector, _ in CATEGORY_BY_RULE} - registered) == []


def test_the_rule_entries_name_rules_the_detectors_emit() -> None:
    assert all(
        _EVIDENCE[outcome] is EvidenceClass.EXTRACTION_UNCERTAINTY for outcome in READING_OUTCOMES
    )
    # The Claude review's rules are the issue types its passes ask about.
    asked = {(REVIEW, rule_id_of(number)) for name in REVIEW_PASSES for number in PASSES[name]}
    review = {key for key in CATEGORY_BY_RULE if key[0] == REVIEW}
    assert review and review <= asked
    assert set(CATEGORY_BY_RULE) - review == (
        {(UNIT_COMPATIBILITY, RULE_SAME_DESCRIPTION)}
        | _reading_rules()
        | {
            (BID_PRICES, bid_prices.RULE_FLOOR),
            (CLAUSES, clauses.RULE_ASSUMED),
            (CLAUSES, clauses.RULE_DEFERRED),
            (CLAUSES, clauses.RULE_DOCUMENT),
            (CLAUSES, clauses.RULE_VAGUE),
            (CLARITY, RULE_OPEN_DECISION),
            (NUMBERING, RULE_MISPLACED),
            ("domain.model_quantities", "model_position_missing"),
            (TENDER_COMPARISON, tender_comparison.RULE_MISSING),
        }
    )


def test_every_check_that_reports_uncertain_reading_was_reviewed() -> None:
    """A finding's evidence class does not change its category, so each check that reports
    ``extraction_uncertainty`` itself needs its reading rules in the tables (mapped to None)."""
    claiming = {
        spec.detector_id
        for spec in registered_specs()
        if EvidenceClass.EXTRACTION_UNCERTAINTY in spec.evidence_classes
    }
    assert claiming == REVIEWED_READING_CHECKS
    assert CATEGORY_BY_DETECTOR["deterministic.extraction_quality"] is None
    assert CATEGORY_BY_DETECTOR["deterministic.reference_integrity"] is FindingCategory.AMBIGUITY
    for detector_id, rule_id in _reading_rules():
        assert detector_id in claiming
        assert finding_category_of(detector_id=detector_id, rule_id=rule_id) is None


def test_the_approved_mapping() -> None:
    """Plan section 5a as the owner approved it on 2026-11-20; a change is a product decision."""
    by_category: defaultdict[FindingCategory | None, set[str]] = defaultdict(set)
    for detector_id, category in CATEGORY_BY_DETECTOR.items():
        by_category[category].add(detector_id)
    assert dict(by_category) == {
        FindingCategory.ERROR: {
            "deterministic.line_total",
            "deterministic.subtotal",
            "deterministic.grand_total",
            "deterministic.required_values",
            "deterministic.numeric_validity",
            "deterministic.field_constraints",
            "deterministic.formula_errors",
            "deterministic.data_type_conformance",
            "deterministic.unit_compatibility",
            # Step B2 (plan section 5a): an OZ outside its Titel, a Titel under the wrong
            # parent and an OZ out of order are errors, as are wrong component sums, prices of
            # 0,00 or a token price, positions not offered, and misspellings.
            "deterministic.hierarchy",
            "deterministic.unit_price_components",
            "domain.boq_bid_prices",
            "domain.boq_typos",
        },
        FindingCategory.INCONSISTENCY: {
            "deterministic.exact_duplicates",
            "deterministic.currency_consistency",
            "domain.standard_text_keys",
            # Plan step B3 (ADR 0010): identical or nearly identical positions that differ.
            "statistical.rate_consistency",
            "statistical.quantity_factor",
            "semantic.unit_fit",
            "semantic.section_fit",
            "machine_learning.near_duplicates",
            "domain.model_quantities",
            # A bid against its tender (proposed 2026-11-22 for the owner's approval).
            TENDER_COMPARISON,
        },
        # The tender review (main, proposed for the owner's approval): numbering an Omission,
        # unclear descriptions and contradictions within an item an Ambiguity; with B2's merge
        # two of its rules take the category B2 gives the same kinds (the rule entries below).
        FindingCategory.OMISSION: {
            "domain.boq_companion_work",
            "domain.boq_separate_payment",
            "domain.boq_numbering",
        },
        FindingCategory.AMBIGUITY: {
            "deterministic.reference_integrity",
            "domain.boq_required_attributes",
            "domain.boq_description_clarity",
            "domain.boq_contradictions",
        },
        FindingCategory.RISK: {
            "domain.boq_clauses",
            "domain.boq_position_types",
            "statistical.peer_price",
            "statistical.open_price_reference",
            # The Claude review (proposed 2026-11-22): a price that stands out, unless the issue
            # type it names says otherwise (the rule entries below).
            REVIEW,
        },
        None: {"deterministic.extraction_quality", "deterministic.unit_vocabulary"},
    }
    assert CATEGORY_BY_RULE == {
        (UNIT_COMPATIBILITY, RULE_SAME_DESCRIPTION): FindingCategory.INCONSISTENCY,
        ("domain.model_quantities", "model_position_missing"): FindingCategory.OMISSION,
        (TENDER_COMPARISON, tender_comparison.RULE_MISSING): FindingCategory.OMISSION,
        (FORMULA_ERRORS, "formula_result_unavailable"): None,
        (SUBTOTAL, "subtotal_scope_ambiguous"): None,
        (SUBTOTAL, "subtotal_display_rounding"): None,
        (GRAND_TOTAL, "grand_total_scope_ambiguous"): None,
        (GRAND_TOTAL, "grand_total_display_rounding"): None,
        (GRAND_TOTAL, "gross_total_scope_ambiguous"): None,
        (GRAND_TOTAL, "gross_total_display_rounding"): None,
        (DATA_TYPES, "ambiguous_value"): None,
        (BID_PRICES, bid_prices.RULE_FLOOR): FindingCategory.RISK,
        (CLAUSES, clauses.RULE_ASSUMED): FindingCategory.CHANGE_ORDER_OPPORTUNITY,
        (CLAUSES, clauses.RULE_DEFERRED): FindingCategory.CHANGE_ORDER_OPPORTUNITY,
        (CLAUSES, clauses.RULE_DOCUMENT): FindingCategory.AMBIGUITY,
        (CLAUSES, clauses.RULE_VAGUE): FindingCategory.AMBIGUITY,
        (CLARITY, RULE_OPEN_DECISION): FindingCategory.CHANGE_ORDER_OPPORTUNITY,
        (NUMBERING, RULE_MISPLACED): FindingCategory.ERROR,
        (REVIEW, "r016"): ERROR,
        (REVIEW, "r018"): ERROR,
        (REVIEW, "r083"): ERROR,
        (REVIEW, "r112"): ERROR,
        (REVIEW, "r023"): FindingCategory.INCONSISTENCY,
        (REVIEW, "r051"): FindingCategory.INCONSISTENCY,
        (REVIEW, "r082"): FindingCategory.INCONSISTENCY,
        (REVIEW, "r084"): FindingCategory.INCONSISTENCY,
        (REVIEW, "r085"): FindingCategory.INCONSISTENCY,
        (REVIEW, "r031"): AMBIGUITY,
        (REVIEW, "r033"): AMBIGUITY,
        (REVIEW, "r038"): AMBIGUITY,
    }


@pytest.mark.parametrize(
    ("detector_id", "rule_id", "expected"),
    [
        # A rule entry wins over its detector's entry, also when it is None.
        (UNIT_COMPATIBILITY, RULE_SAME_DESCRIPTION, FindingCategory.INCONSISTENCY),
        (FORMULA_ERRORS, RULE_UNAVAILABLE, None),
        (SUBTOTAL, "subtotal_display_rounding", None),
        (GRAND_TOTAL, "gross_total_scope_ambiguous", None),
        (DATA_TYPES, RULE_AMBIGUOUS, None),
        # Without a rule entry, the detector's entry decides.
        (UNIT_COMPATIBILITY, "fractional_count", FindingCategory.ERROR),
        ("deterministic.line_total", "line_total_mismatch", FindingCategory.ERROR),
        (SUBTOTAL, "subtotal_mismatch", FindingCategory.ERROR),
        (SUBTOTAL, "subtotal_undecided", FindingCategory.ERROR),
        (DATA_TYPES, "invalid_value", FindingCategory.ERROR),
        (
            "deterministic.reference_integrity",
            "german_position_reference",
            FindingCategory.AMBIGUITY,
        ),
        ("deterministic.unit_vocabulary", "unknown_unit", None),
        # Step B2: every numbering rule is an error (plan section 5a, not an inconsistency).
        *(
            ("deterministic.hierarchy", rule, ERROR)
            for rule in (RULE_ITEM, RULE_SECTION, RULE_ORDER)
        ),
        # The bid price check: its rules are errors, except the price below the floor.
        (BID_PRICES, bid_prices.RULE_NOMINAL, ERROR),
        (BID_PRICES, bid_prices.RULE_NOT_OFFERED, ERROR),
        (BID_PRICES, bid_prices.RULE_FLOOR, FindingCategory.RISK),
        # The clause check: a risk, unless the rule leaves conditions open or the wording vague.
        (CLAUSES, clauses.RULE_RISK, FindingCategory.RISK),
        (CLAUSES, clauses.RULE_LUMP_SUM, FindingCategory.RISK),
        (CLAUSES, clauses.RULE_DEFERRED, FindingCategory.CHANGE_ORDER_OPPORTUNITY),
        (CLAUSES, clauses.RULE_DOCUMENT, AMBIGUITY),
        # The tender review: an open decision is a change order opportunity, a misplaced item
        # an error; the other rules take their detector's category.
        (CLARITY, RULE_OPEN_DECISION, FindingCategory.CHANGE_ORDER_OPPORTUNITY),
        (CLARITY, "open_scope", AMBIGUITY),
        (NUMBERING, RULE_MISPLACED, ERROR),
        (NUMBERING, "numbering_gap", FindingCategory.OMISSION),
        ("domain.boq_contradictions", "spec_conflict", AMBIGUITY),
        # A detector the tables do not know has no category.
        ("test.unknown_probe", "default", None),
        ("test.unknown_probe", RULE_SAME_DESCRIPTION, None),
    ],
)
def test_precedence(detector_id: str, rule_id: str, expected: FindingCategory | None) -> None:
    assert finding_category_of(detector_id=detector_id, rule_id=rule_id) is expected


def test_the_order_and_the_keys_cover_every_category_once() -> None:
    assert len(FINDING_CATEGORY_ORDER) == len(set(FINDING_CATEGORY_ORDER)) == len(FindingCategory)
    assert set(FINDING_CATEGORY_ORDER) == set(FindingCategory)
    assert FINDING_CATEGORY_ORDER[0] is FindingCategory.ERROR
    assert [key.value for key in FindingCategoryKey] == [c.value for c in FindingCategory] + [
        "none"
    ]


def _documented_tables() -> tuple[dict[str, str], dict[tuple[str, str], str]]:
    """The "Detector or rule | Finding category" table of the data model page, as category
    values ("none" for none) by detector id and by (detector id, rule id)."""
    page = DATA_MODEL.read_text(encoding="utf-8")
    header = "| Detector or rule | Finding category |\n| --- | --- |\n"
    table = page.split(header, 1)[1].split("\n\n", 1)[0]
    detectors: dict[str, str] = {}
    rules: dict[tuple[str, str], str] = {}
    for line in table.splitlines():
        names, category = (cell.strip() for cell in line.strip().strip("|").split("|"))
        ids = re.findall(r"`([^`]+)`", names)
        if names.startswith("rule "):
            rule_id, detector_id = ids
            rules[(detector_id, rule_id)] = category.strip("`")
        else:
            detectors.update(dict.fromkeys(ids, category.strip("`")))
    return detectors, rules


def test_the_data_model_page_shows_the_tables() -> None:
    def value(category: FindingCategory | None) -> str:
        return "none" if category is None else category.value

    detectors, rules = _documented_tables()
    assert detectors == {d: value(c) for d, c in CATEGORY_BY_DETECTOR.items()}
    assert rules == {key: value(c) for key, c in CATEGORY_BY_RULE.items()}
