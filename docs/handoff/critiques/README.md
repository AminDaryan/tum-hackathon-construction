# Round 2 design critiques

Five independent reviews of the Phase 1 core contracts, run as a multi-agent workflow (`docs/handoff/workflows/design-critique.workflow.js`). Findings are verbatim, most severe first. Paths are relative to the repository root and describe the tree as it was during the review, so some findings are already fixed (see each file's status line).

- [adaptability](round-2-adaptability.md): 15 findings (7 high, 7 medium, 1 low). Applied during Phase 1 (plannable parameters, section hierarchy, schema decisions, coordinate-based identity). Deferred items are listed in docs/handoff/NEXT_STEPS.md.
- [numerics-evidence](round-2-numerics-evidence.md): 14 findings (6 high, 5 medium, 3 low). Applied during Phase 1 (exact decimal bounds, tolerances, evidence model). Deferred items are listed in docs/handoff/NEXT_STEPS.md.
- [boq-domain](round-2-boq-domain.md): 18 findings (8 high, 8 medium, 2 low). Applied to the contracts (decision table, new row kinds, value markers, totals rules, BoQ wording). The normalization and detector parts are specified in NEXT_STEPS.md but not implemented yet.
- [security-robustness](round-2-security-robustness.md): 17 findings (4 high, 10 medium, 3 low). Applied to the core contracts (run limits, tamper checks, plan trust, pattern safety, bounded decimals). Ingestion integration and API parts are open items in NEXT_STEPS.md.
- [maintainability](round-2-maintainability.md): 12 findings (4 high, 5 medium, 3 low). NOT triaged yet: it finished after the handoff snapshot. Triage it first (NEXT_STEPS.md, step 1).
