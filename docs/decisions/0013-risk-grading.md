# 0013: Risk grading reminds; it does not decide

Status: proposed (2026-11-20). Needs the owner's review before it is accepted.

Status note, 2026-11-21: the owner chose "findings first, risk list second" for Phase B: the
issue register (six finding categories) is the main list, and the risk report stays a second
view of questions for the client, without repeating what the register finds. So the rules that
checked the same thing as a check of the issue register (B2) were removed or narrowed, and those
checks are listed in `findings.yaml` (version 0.3) with the risk types and the questions the rules
had: D05 (dig, backfill) and D30 (disposal class) are left to `domain.boq_companion_work` and
`domain.boq_required_attributes`; D08 no longer reads pressure or drinking-water pipes; A01 asks
for the exposure class only, and A04 (pipe sizes) is gone; V03 (a document without a number) is
left to `domain.boq_clauses`, V05 no longer reads "nach Aufwand", "nach Erfordernis" and "nach
Bedarf", and V08 reads only alternative positions. Two details of the removed rules moved into
the register's checks (a waste class "noch festzulegen" is no class; Stahlbeton and
Transportbeton with a verb of placing need a strength class). D07, D19, V01, V02 and V07 stay: they ask other
questions (a firestop in a fire-rated wall, a sleeve, who is responsible, what is included, which
soil report). C04 repeats `deterministic.reference_integrity`, not a B2 check, and stays until
the owner and the package's author decide. This ADR stays proposed.

## Context

Estimators need a short, ordered list of places in a bill that are worth checking before a
bid: missing supporting work, values a position does not state, wording that leaves scope
open, and the detectors' own findings. The challenge lists 135 risk types; most need
documents the workbench does not have (drawings, soil reports, other trades' bills). A
keyword hit is not an engineering error, and work found elsewhere in the bill is not proof
that it covers a given component.

## Decision

1. One package, `backend/app/risk`, computes a risk report for a finished validation run on
   request (`GET /api/v1/validation-runs/{run_id}/risks`). The report is not stored and no
   model is called while it is read; only explicitly started discovery runs are stored (9).
   The detector registry is not changed.
2. Rules live in data tables per profile (`app/risk/data/boq/*.yaml`), never in code:
   dependencies (D01-D30), required values (A01-A11), wording (V01-V08), short/long text
   consistency (C01-C03), references to positions of the bill (C04), the
   detector-to-risk-type map, tiers and texts.
3. Evidence and priority are separate fields. `state` (risk, cannot_tell, covered, ...) and
   `evidence_class` say how strong the evidence is; `tier` says how soon to review it.
   Safety may be reviewed first but is never called a confirmed hazard; evidence from
   keywords alone is never raised above high.
4. Work found elsewhere covers a position only when it is linked: an explicit reference, a
   shared component, system, room or axis key, both building and storey, or the same
   component word at the same location. Otherwise the result is `cannot_tell` with a
   question, never `covered`. Not finding work is a question, not an omission.
5. Money has a basis: a computed difference is exact; a possible double count is an estimate
   with its quantity, price and range; a comparison with similar positions is not a loss;
   everything else is `unknown`, with a size class that only orders the list. The 1 % and 5 %
   tier thresholds are marked as unvalidated defaults.
6. Candidates that share evidence are merged before signals are counted; the same evidence
   found by two methods is one signal and its money is not summed.
7. The local model is optional and bounded. The model review of open reminders asks about
   at most five of them and runs only for an explicit in-process caller: reading a report
   never calls a model (`model_review=true` is refused with a migration note). Discovery (9)
   looks for problems no rule raised.
   Answers are JSON whose positions (by request ids, never guessed) and verbatim quotes are
   checked against the text actually sent; what fails is recorded with its reason. A model
   never changes a state, tier or amount of a rule result, its findings are `cannot_tell`
   tasks without money, and failures leave every other result unchanged.
8. The report keeps the review burden small. Only reminders with concrete evidence (state
   `risk`), a tier of medium or above and a next action reach the main list (`risks`);
   safety doubts of that tier stay visible whatever their state. Every other reminder stays
   in `record` with its own state and is never marked as passed. Open questions
   (`cannot_tell`) are not to-dos of their own: they are grouped by the document they need,
   or by rule and cause, and asked once (`open_questions`). A `funnel` reports the raw
   doubts, how many the bill itself explained, how many remain after merging, and which
   checks lack information. The rule is a table setting (`main_list` in `grading.yaml`).
9. Discovery runs only when a client starts it (`POST .../risks/discovery-runs`): one run per
   set of inputs (validation run, dataset revision, profile, bill text, table versions,
   prompt and checks, strategy, model, and a digest of the positions chosen and the requests
   sent, which reviews change); a repeated start returns that run, `rerun` starts a
   new one. Each run is stored with its prompts, raw answers, rejections, times and inputs. A
   report applies it by `discovery_run_id`; when the inputs changed it is shown as `outdated`
   and not applied. Two hypotheses on the same words are two findings unless the model names
   a known reminder of the same cause; a shared document is asked for once, listing the
   questions it serves.
10. Display order is separate from grading: `sort_by` (`priority`, `price_impact`,
    `confidence`) and `sort_order` only reorder `risks` and `record`, each on its own, after
    grading; `priority_rank` keeps the default place. Price impact uses the money basis of
    (5) without evidence weights; confidence is the evidence level, never a model's.
11. Coverage says what was checked, apart from what was found: a rule lists the positions it
    read, a detector its counts (`scope`). A detector that ran but checked nothing does not
    cover its risk types; an empty reminder list is not a passed check.

## Consequences

- The catalogue is a taxonomy: the report's coverage table lists every type and says which
  ones have no check in this version.
- Thresholds, word lists, tiers and the main-list rule need validation on the development
  projects; the held-out test projects are used once per version, not for tuning.
- New checks are added to `app.risk.checks.CHECKS`; new detectors need one line in
  `findings.yaml`.
