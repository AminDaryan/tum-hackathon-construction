"""Risk grading of a bill of quantities: which reminders are worth reviewing, in which order.

Owned as one package. Its seams: data tables per profile in ``data/<profile>/`` (rules,
wording, tiers), :data:`app.risk.checks.CHECKS` for new checks, :mod:`app.risk.findings` for
new detectors (a line in ``findings.yaml``), and the ``generator`` of
:func:`app.risk.service.risk_report` for another local model. Entry point:
:func:`app.risk.service.risk_report`, served at ``GET /api/v1/validation-runs/{run_id}/risks``.
"""
