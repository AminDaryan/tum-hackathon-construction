"""The risk checks that read the bill text. Each returns candidates and one outcome per rule.

To add a check, write a function with the :class:`~app.risk.checks.base.Check` signature and
list it in :data:`CHECKS`; the grader, the coverage table and the API need no change.
"""

from __future__ import annotations

from app.risk.bill import Bill
from app.risk.checks import attributes, consistency, dependency, wording
from app.risk.checks.base import Check, CheckResult, Outcome
from app.risk.models import ProjectContext
from app.risk.tables import RiskTables

CHECKS: tuple[Check, ...] = (dependency.check, attributes.check, wording.check, consistency.check)


def run_checks(bill: Bill, tables: RiskTables, project: ProjectContext) -> CheckResult:
    result = CheckResult()
    for check in CHECKS:
        result.extend(check(bill, tables, project))
    return result


__all__ = ["CHECKS", "Check", "CheckResult", "Outcome", "run_checks"]
