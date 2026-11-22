"""Finding categories: what a finding means for the Kontroller who checks a bill by hand.

Every finding carries one of six categories, or none when it is about reading the file
(plan section 5a; ADR 0010, amendment of 2026-11-20):

* ``error``: would be objectively wrong (a total that does not add up, a missing required
  value, a repeated OZ);
* ``omission``: work the bill needs, or says is paid separately, for which no position pays;
* ``inconsistency``: two or more positions contradict each other;
* ``ambiguity``: a description leaves open what to do or supply;
* ``risk``: clear, but may cost the bidder money or time, or lead to a dispute;
* ``change_order_opportunity``: the bill admits that conditions or decisions stay open until
  after award.

The category is never read from storage. ``ValidationIssue.finding_category`` computes it
with :func:`finding_category_of` from the detector and the rule; stored payloads carry the
computed value, but loading drops it. So a change to the tables below applies to stored
findings as well, without a column or a migration, and a review decision does not change it.
Every registered detector has an entry in :data:`CATEGORY_BY_DETECTOR` (a test enforces it);
:data:`CATEGORY_BY_RULE` holds the rules whose category differs from their detector's.

The evidence class does not decide the category. It says how far a finding can be trusted,
the category what the finding means if it holds. A finding computed from values the
extraction could not verify (a PDF's text layer, OCR below the threshold) is downgraded to
``extraction_uncertainty`` by the evidence policy and keeps its check's category: a wrong
line total on a PDF bill is an error to verify in the source. The findings about reading the
file are the checks and rules the tables map to None.

Pure data and one function: this module imports nothing from the application, because
``app.models.issue`` imports it.
"""

from __future__ import annotations

from enum import StrEnum


class FindingCategory(StrEnum):
    """What a finding means for the person checking the bill by hand (plan section 5a)."""

    ERROR = "error"
    OMISSION = "omission"
    INCONSISTENCY = "inconsistency"
    AMBIGUITY = "ambiguity"
    RISK = "risk"
    CHANGE_ORDER_OPPORTUNITY = "change_order_opportunity"


class FindingCategoryKey(StrEnum):
    """A finding category as filters and counts name it: one of the six, or ``none`` for the
    findings without a category (about reading the file)."""

    ERROR = "error"
    OMISSION = "omission"
    INCONSISTENCY = "inconsistency"
    AMBIGUITY = "ambiguity"
    RISK = "risk"
    CHANGE_ORDER_OPPORTUNITY = "change_order_opportunity"
    NONE = "none"


# The order of the risk report (plan section 5a); findings without a category come after them.
FINDING_CATEGORY_ORDER: tuple[FindingCategory, ...] = (
    FindingCategory.ERROR,
    FindingCategory.INCONSISTENCY,
    FindingCategory.OMISSION,
    FindingCategory.AMBIGUITY,
    FindingCategory.RISK,
    FindingCategory.CHANGE_ORDER_OPPORTUNITY,
)

CATEGORY_BY_DETECTOR: dict[str, FindingCategory | None] = {
    "deterministic.currency_consistency": FindingCategory.INCONSISTENCY,
    "deterministic.data_type_conformance": FindingCategory.ERROR,
    "deterministic.exact_duplicates": FindingCategory.INCONSISTENCY,
    "deterministic.extraction_quality": None,
    "deterministic.field_constraints": FindingCategory.ERROR,
    "deterministic.formula_errors": FindingCategory.ERROR,
    "deterministic.grand_total": FindingCategory.ERROR,
    "deterministic.hierarchy": FindingCategory.ERROR,
    "deterministic.line_total": FindingCategory.ERROR,
    "deterministic.numeric_validity": FindingCategory.ERROR,
    # Also when identifiers of the bill could not be read: the evidence class then says that
    # the reference may exist among them.
    "deterministic.reference_integrity": FindingCategory.AMBIGUITY,
    "deterministic.required_values": FindingCategory.ERROR,
    "deterministic.subtotal": FindingCategory.ERROR,
    "deterministic.unit_compatibility": FindingCategory.ERROR,
    "deterministic.unit_price_components": FindingCategory.ERROR,
    "deterministic.unit_vocabulary": None,
    "domain.boq_bid_prices": FindingCategory.ERROR,
    "domain.boq_clauses": FindingCategory.RISK,
    "domain.boq_companion_work": FindingCategory.OMISSION,
    "domain.boq_position_types": FindingCategory.RISK,
    "domain.boq_required_attributes": FindingCategory.AMBIGUITY,
    "domain.boq_separate_payment": FindingCategory.OMISSION,
    "domain.standard_text_keys": FindingCategory.INCONSISTENCY,
    # The bill against an attached model (IFC): two documents of the project disagree.
    "domain.model_quantities": FindingCategory.INCONSISTENCY,
    # The bid against its tender (proposed on 2026-11-22 for the owner's approval), like the
    # model: two documents of the project disagree.
    "domain.boq_tender_comparison": FindingCategory.INCONSISTENCY,
    # The tender review (ADR 0013-tender-review-checks), proposed on 2026-11-21 for the owner's
    # approval: numbers skipped and sections without items are work no position pays for; an
    # unclear description, and a short text that contradicts the long text of the same item,
    # leave open what to do or supply (a contradiction between positions would be an
    # inconsistency); a typing slip is objectively wrong text, of low severity.
    "domain.boq_numbering": FindingCategory.OMISSION,
    "domain.boq_description_clarity": FindingCategory.AMBIGUITY,
    "domain.boq_contradictions": FindingCategory.AMBIGUITY,
    "domain.boq_typos": FindingCategory.ERROR,
    # A unit price far from comparable positions: clear, but may cost the bidder money (plan 5a
    # puts unusual unit prices among similar positions under Risk).
    "statistical.peer_price": FindingCategory.RISK,
    # A unit price below the published average value of its material: context that may mean a
    # slip or a cheaper material than specified, never a proven error (issue #23).
    "statistical.open_price_reference": FindingCategory.RISK,
    # The comparison checks of plan step B3 (ADR 0010): identical or nearly identical positions
    # that differ in price, quantity, unit dimension or section contradict each other.
    "statistical.rate_consistency": FindingCategory.INCONSISTENCY,
    "statistical.quantity_factor": FindingCategory.INCONSISTENCY,
    "semantic.unit_fit": FindingCategory.INCONSISTENCY,
    "semantic.section_fit": FindingCategory.INCONSISTENCY,
    "machine_learning.near_duplicates": FindingCategory.INCONSISTENCY,
    # What Claude suspects when a reviewer sends it the bill: a price that stands out, unless
    # the issue type it names says otherwise (CATEGORY_BY_RULE; "r081" is issue type 081).
    "llm.bill_review": FindingCategory.RISK,
}

# (detector id, rule id) -> category, where a rule's category differs from its detector's.
CATEGORY_BY_RULE: dict[tuple[str, str], FindingCategory | None] = {
    # The same description measured in units of different dimensions: positions contradict
    # each other, while the unit rules of one position judge the position itself.
    ("deterministic.unit_compatibility", "same_description_dimension"): (
        FindingCategory.INCONSISTENCY
    ),
    # Questions of reading the file, which these checks report as extraction_uncertainty
    # themselves: a formula whose result the file does not store, a total whose rows cannot be
    # told apart or that differs only by the rounding of the displayed values, and a value
    # whose type cannot be decided.
    ("deterministic.formula_errors", "formula_result_unavailable"): None,
    ("deterministic.subtotal", "subtotal_scope_ambiguous"): None,
    ("deterministic.subtotal", "subtotal_display_rounding"): None,
    ("deterministic.grand_total", "grand_total_scope_ambiguous"): None,
    ("deterministic.grand_total", "grand_total_display_rounding"): None,
    ("deterministic.grand_total", "gross_total_scope_ambiguous"): None,
    ("deterministic.grand_total", "gross_total_display_rounding"): None,
    ("deterministic.data_type_conformance", "ambiguous_value"): None,
    # An hourly rate below the minimum wage is a price the bidder can defend or must explain:
    # a risk, while the bid price check's other rules (zero, token, not offered) are errors.
    ("domain.boq_bid_prices", "price_below_floor"): FindingCategory.RISK,
    # Conditions or decisions the bill leaves open until after award (plan section 5a).
    ("domain.boq_clauses", "assumed_condition"): FindingCategory.CHANGE_ORDER_OPPORTUNITY,
    ("domain.boq_clauses", "deferred_decision"): FindingCategory.CHANGE_ORDER_OPPORTUNITY,
    # A description that leaves open what to do or supply: vague wording, or the work stated
    # in another document.
    ("domain.boq_clauses", "document_reference"): FindingCategory.AMBIGUITY,
    ("domain.boq_clauses", "vague_wording"): FindingCategory.AMBIGUITY,
    # The tender review, as step B2 categorises the same kinds (proposed with B2's merge, for
    # the owner's approval): a specification the client decides later, like the clause check's
    # deferred decisions.
    ("domain.boq_description_clarity", "open_decision"): (FindingCategory.CHANGE_ORDER_OPPORTUNITY),
    # An item outside its section's number, like deterministic.hierarchy's item_outside_section.
    ("domain.boq_numbering", "misplaced_item"): FindingCategory.ERROR,
    # Work the model contains that no position of the bill prices.
    ("domain.model_quantities", "model_position_missing"): FindingCategory.OMISSION,
    # A tender position the bid does not price.
    ("domain.boq_tender_comparison", "tender_position_missing"): FindingCategory.OMISSION,
    # The issue types of the Claude review that are no price risk, proposed on 2026-11-22 for
    # the owner's approval, as the checks of the same kinds are categorised: a wrong quantity,
    # tax or item structure is an error; quantities, currencies, cost groups, price bases or
    # material requirements that disagree between positions are an inconsistency; a
    # description that leaves the material, a dimension or a grade open is an ambiguity.
    ("llm.bill_review", "r016"): FindingCategory.ERROR,
    ("llm.bill_review", "r018"): FindingCategory.ERROR,
    ("llm.bill_review", "r083"): FindingCategory.ERROR,
    ("llm.bill_review", "r112"): FindingCategory.ERROR,
    ("llm.bill_review", "r023"): FindingCategory.INCONSISTENCY,
    ("llm.bill_review", "r051"): FindingCategory.INCONSISTENCY,
    ("llm.bill_review", "r082"): FindingCategory.INCONSISTENCY,
    ("llm.bill_review", "r084"): FindingCategory.INCONSISTENCY,
    ("llm.bill_review", "r085"): FindingCategory.INCONSISTENCY,
    ("llm.bill_review", "r031"): FindingCategory.AMBIGUITY,
    ("llm.bill_review", "r033"): FindingCategory.AMBIGUITY,
    ("llm.bill_review", "r038"): FindingCategory.AMBIGUITY,
}


def finding_category_of(*, detector_id: str, rule_id: str) -> FindingCategory | None:
    """The category of a finding: the rule's entry in :data:`CATEGORY_BY_RULE` when it has one,
    else the detector's entry in :data:`CATEGORY_BY_DETECTOR`, else None (a detector the tables
    do not know)."""
    key = (detector_id, rule_id)
    if key in CATEGORY_BY_RULE:
        return CATEGORY_BY_RULE[key]
    return CATEGORY_BY_DETECTOR.get(detector_id)
