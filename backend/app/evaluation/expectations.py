"""Which check is expected to find each planted error kind, of which anomaly type it is and
under which finding category the reviewer should see it.

The checks of the ``boq`` kinds come in plan steps B2 (rule checks) and B3 (signal checks), and
both are built (B2's are marked step "available"; B3's keep their step's name, and S1,
``statistical.peer_price``, also stands for M1). Every run plans every registered check. For a
check that is not registered, or one without a profile setting it needs (below), the report
says "check not available yet" instead of a recall of 0. Where the plan names no rule id, any
rule of the check counts.

A check is *available* when it is registered (``registered``) and, for a check that needs a
profile setting (``Check.setting``), the profile's defaults for that detector hold the
setting. One expected
check has such a setting: ``exact_duplicates`` for ``duplicate_position``, which finds a copy
under a new OZ only when it ignores the item code; B2 sets that in the BoQ profile.
"""

from __future__ import annotations

from collections.abc import Container, Mapping
from dataclasses import dataclass
from typing import Any

from app.evaluation.synthetic import EXPECTED_RULES, ErrorKind
from app.models.finding_category import FindingCategory

ANOMALY_TYPES = ("price", "quantity", "unit", "semantic", "structural", "logical", "duplicate")


@dataclass(frozen=True)
class Check:
    detector_id: str
    step: str  # the plan step that adds the check, or "available" for today's checks
    rule_ids: tuple[str, ...] = ()  # empty: any rule of the check
    setting: tuple[str, str] | None = None  # (config field, value it must list) in the profile

    def matches(self, detector_id: str, rule_id: str) -> bool:
        return detector_id == self.detector_id and (not self.rule_ids or rule_id in self.rule_ids)

    def available(
        self, registered: Container[str], defaults: Mapping[str, Mapping[str, Any]]
    ) -> bool:
        if self.detector_id not in registered:
            return False
        if self.setting is None:
            return True
        name, value = self.setting
        listed = defaults.get(self.detector_id, {}).get(name, ())
        return isinstance(listed, list | tuple) and value in listed


# S1 also stands for M1, the similar-positions price check of ADR 0010: its text group is the
# nearest positions by character n-grams in the same unit, so M1 was not built a second time.
S1 = Check("statistical.peer_price", "B3")
S2 = Check("statistical.rate_consistency", "B3")
S3 = Check("statistical.quantity_factor", "B3")
U1 = Check("semantic.unit_fit", "B3")
T1 = Check("semantic.section_fit", "B3")
D1 = Check("machine_learning.near_duplicates", "B3")
LINE_TOTAL = Check("deterministic.line_total", "available", EXPECTED_RULES[ErrorKind.LINE_TOTAL])

EXPECTED_CHECKS: dict[ErrorKind, tuple[Check, ...]] = {
    ErrorKind.LINE_TOTAL: (LINE_TOTAL,),
    ErrorKind.SUBTOTAL: (Check("deterministic.subtotal", "available", ("subtotal_mismatch",)),),
    ErrorKind.NET_TOTAL: (
        Check("deterministic.grand_total", "available", ("grand_total_mismatch",)),
    ),
    ErrorKind.TAX: (Check("deterministic.grand_total", "available", ("tax_mismatch",)),),
    ErrorKind.UNKNOWN_UNIT: (
        Check("deterministic.unit_vocabulary", "available", ("unknown_unit",)),
    ),
    ErrorKind.DUPLICATE_ROW: (
        Check("deterministic.exact_duplicates", "available", ("exact_duplicate",)),
    ),
    ErrorKind.MISSING_PRICE: (
        Check("deterministic.required_values", "available", ("required_value",)),
    ),
    ErrorKind.INVALID_QUANTITY: (
        Check("deterministic.data_type_conformance", "available", ("invalid_value", "wrong_type")),
    ),
    ErrorKind.PRICE_DECIMAL_SLIP: (S1,),
    ErrorKind.PRICE_DIGIT_SWAP: (S1, S2),
    ErrorKind.INCONSISTENT_RATE: (S2,),
    ErrorKind.WRONG_RATE_COPIED: (S1,),
    ErrorKind.PLACEHOLDER_PRICE: (
        Check("domain.boq_bid_prices", "available", EXPECTED_RULES[ErrorKind.PLACEHOLDER_PRICE]),
    ),
    ErrorKind.HIGH_CONTINGENCY_PRICE: (S1,),
    ErrorKind.QUANTITY_DECIMAL_SLIP: (S3,),
    ErrorKind.QUANTITY_UNIT_SLIP: (S3,),
    ErrorKind.PRICE_PER_WRONG_UNIT: (S1,),
    ErrorKind.WRONG_UNIT: (U1,),
    ErrorKind.MISPLACED_POSITION: (T1,),
    ErrorKind.CODE_OUTSIDE_SECTION: (
        Check("deterministic.hierarchy", "available", ("item_outside_section",)),
    ),
    ErrorKind.LINE_TOTAL_SLIP: (LINE_TOTAL,),
    ErrorKind.COMPONENT_SUM_ERROR: (
        Check(
            "deterministic.unit_price_components",
            "available",
            EXPECTED_RULES[ErrorKind.COMPONENT_SUM_ERROR],
        ),
    ),
    ErrorKind.DUPLICATE_POSITION: (
        Check(
            "deterministic.exact_duplicates",
            "available",
            ("exact_duplicate",),
            setting=("ignore_fields", "item_code"),
        ),
    ),
    ErrorKind.NEAR_DUPLICATE_POSITION: (D1,),
}

# The owner's seven anomaly types (plan section 5).
ANOMALY_TYPE: dict[ErrorKind, str] = {
    ErrorKind.LINE_TOTAL: "logical",
    ErrorKind.SUBTOTAL: "logical",
    ErrorKind.NET_TOTAL: "logical",
    ErrorKind.TAX: "logical",
    ErrorKind.UNKNOWN_UNIT: "unit",
    ErrorKind.DUPLICATE_ROW: "duplicate",
    ErrorKind.MISSING_PRICE: "structural",
    ErrorKind.INVALID_QUANTITY: "quantity",
    ErrorKind.PRICE_DECIMAL_SLIP: "price",
    ErrorKind.PRICE_DIGIT_SWAP: "price",
    ErrorKind.INCONSISTENT_RATE: "price",
    ErrorKind.WRONG_RATE_COPIED: "price",
    ErrorKind.PLACEHOLDER_PRICE: "price",
    ErrorKind.HIGH_CONTINGENCY_PRICE: "price",
    ErrorKind.QUANTITY_DECIMAL_SLIP: "quantity",
    ErrorKind.QUANTITY_UNIT_SLIP: "quantity",
    ErrorKind.PRICE_PER_WRONG_UNIT: "unit",
    ErrorKind.WRONG_UNIT: "unit",
    ErrorKind.MISPLACED_POSITION: "semantic",
    ErrorKind.CODE_OUTSIDE_SECTION: "structural",
    ErrorKind.LINE_TOTAL_SLIP: "logical",
    ErrorKind.COMPONENT_SUM_ERROR: "logical",
    ErrorKind.DUPLICATE_POSITION: "duplicate",
    ErrorKind.NEAR_DUPLICATE_POSITION: "duplicate",
}

ERROR = FindingCategory.ERROR
INCONSISTENCY = FindingCategory.INCONSISTENCY
RISK = FindingCategory.RISK

# The finding category of each kind: the category its expected check gives its findings (plan
# section 5a). The built checks take theirs from app.models.finding_category, and a test keeps
# the two in agreement: B2's rule checks of prices of 0,00 or 0,01, of the hierarchy and of unit
# price components find errors, its copies under a new OZ inconsistencies; B3's S2, S3, U1, T1
# and D1 find inconsistencies. S1, dropped from the plan on 2026-11-20, was then built in main
# as the check statistical.peer_price, which also does M1's comparison; its unusual unit
# prices are risks. An unknown unit is a question of reading the file: no category.
EXPECTED_CATEGORY: dict[ErrorKind, FindingCategory | None] = {
    ErrorKind.LINE_TOTAL: ERROR,
    ErrorKind.SUBTOTAL: ERROR,
    ErrorKind.NET_TOTAL: ERROR,
    ErrorKind.TAX: ERROR,
    ErrorKind.UNKNOWN_UNIT: None,
    ErrorKind.DUPLICATE_ROW: INCONSISTENCY,
    ErrorKind.MISSING_PRICE: ERROR,
    ErrorKind.INVALID_QUANTITY: ERROR,
    ErrorKind.PRICE_DECIMAL_SLIP: RISK,
    ErrorKind.PRICE_DIGIT_SWAP: RISK,
    ErrorKind.INCONSISTENT_RATE: INCONSISTENCY,
    ErrorKind.WRONG_RATE_COPIED: RISK,
    ErrorKind.PLACEHOLDER_PRICE: ERROR,
    ErrorKind.HIGH_CONTINGENCY_PRICE: RISK,
    ErrorKind.QUANTITY_DECIMAL_SLIP: INCONSISTENCY,
    ErrorKind.QUANTITY_UNIT_SLIP: INCONSISTENCY,
    ErrorKind.PRICE_PER_WRONG_UNIT: RISK,
    ErrorKind.WRONG_UNIT: INCONSISTENCY,
    ErrorKind.MISPLACED_POSITION: INCONSISTENCY,
    ErrorKind.CODE_OUTSIDE_SECTION: ERROR,
    ErrorKind.LINE_TOTAL_SLIP: ERROR,
    ErrorKind.COMPONENT_SUM_ERROR: ERROR,
    ErrorKind.DUPLICATE_POSITION: INCONSISTENCY,
    ErrorKind.NEAR_DUPLICATE_POSITION: INCONSISTENCY,
}
