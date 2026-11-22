# Validation engine

Source of truth: `backend/app/validation/`. The engine is independent of any LLM: a plan (from
the baseline planner or, later, an LLM planner) names registered detectors; the plan is
validated against the registry; the pipeline runs each detector in isolation against a read-only
`ValidationContext`; issues are created only through the run's `IssueFactory`.

```
registry ──► planner ──► PlanValidator ──► ValidationPipeline ──► detectors ──► IssueFactory
 (catalogue)  (baseline)   (trust, limits)    (isolation, limits)   (read-only     (evidence policy,
                                                                     context)       fingerprints)
```

## Detector contract

A detector is one module in a detector package (`validation/deterministic/`, later
`statistical/`, `semantic/`, `domain/`) with one `Detector` subclass:

* `spec: DetectorSpec`: id (`deterministic.line_total`), name, version, category, description,
  required and optional fields, supported data types, applicability text, the evidence classes
  and issue categories it may emit, dependencies, limitations, license, references, `baseline`,
  `cost`.
* `config_model`: a strict `DetectorConfig` subclass (unknown keys rejected, every parameter
  has a default). Parameters are **profile-controlled** unless declared with `plannable(...)`:
  plans from users or an LLM may set only plannable parameters (which fields to check,
  severities, caps); tolerances, rounding, regular expressions and switches stay in the profile.
* `validate(context, config) -> DetectorResult`: issues, `notes` and `coverage`.

Detectors read data only through the context accessors (`rows`, `number`, `text`, `marker`,
`unit`, `currency_evidence`, `value`, the column-id variants), never through
`cell.normalized_value` directly (a test scans the detector packages for it), and never mutate
the dataset. `value` returns the typed value of any type (number, text, date, yes/no, error;
`None` for empty, ambiguous and unavailable cells) for checks that compare cells as written
(`exact_duplicates`) or report what a cell holds (`formula_errors`); checks that compute use
`number` and `text`. Each per-row check runs inside `_support.row_guard`
(an `ArithmeticError` or `ValueError` from document values skips that row visibly); issue-policy
errors, model validation errors and run limits propagate. All regular expressions are applied
through `app.core.patterns` (bounded text, memoized).

`DetectorRegistry.from_packages` discovers detectors; `profile_check.check_profiles` verifies at
startup and in the tests that every `detector_defaults` entry of every profile names a
registered detector and validates against its config model.

## The baseline plan

`planner.BaselinePlanner` builds the plan that runs without any AI planner: every registered
check, in registry order, with no parameters ([ADR 0010](../decisions/0010-boq-anomaly-detection.md),
amendment of 2026-11-21). There is no opt-in check and no way to switch one off, in a profile
or in a request; a check that does not apply to a dataset reports itself as skipped with its
reason. Each step carries a fixed rationale: "Runs on every validation: a rule check that can
confirm an error." or "Runs on every validation: a signal, never a confirmed error." The plan's
note says that adaptive AI planning is not available in this version. An LLM plan must keep
every registered check (`check_missing`).

## Which detector reports which condition

One defective cell must produce one finding. `contracts/conditions.py` classifies every cell
(`cell_condition`) and names the single owner of each condition that is a finding by itself:

| Cell condition | Owner (reports it) | Evidence class | Every other detector |
| --- | --- | --- | --- |
| `error` (`#REF!`, `#DIV/0!`, …) | `deterministic.formula_errors` | confirmed rule violation (the spreadsheet itself reports the error) | abstains on the row, counts `rows_skipped_unusable_inputs` |
| `unavailable` (formula without cached result) | `deterministic.formula_errors` | extraction uncertainty | abstains, `rows_skipped_unusable_inputs` |
| `ambiguous` (`1.234`, undecidable date) | `deterministic.data_type_conformance` | extraction uncertainty | abstains, `rows_skipped_unusable_inputs` |
| `failed` (`approx. 5` in a quantity, out-of-range number) | `deterministic.data_type_conformance` | confirmed rule violation | abstains, `rows_skipped_unusable_inputs` |
| `empty` where the profile requires a value | `deterministic.required_values` | confirmed rule violation | abstains, `rows_skipped_missing_inputs` |
| `marker` (`Incl.`, `entfällt`, `psch`) | none: a legitimate value | | uses `Cell.marker` (see below) or abstains, `rows_skipped_marker` |
| low extraction confidence (OCR/PDF only) | `deterministic.extraction_quality` | extraction uncertainty | uses the value; the issue factory downgrades confirmed findings built on it |
| header, mapping and structure warnings | `deterministic.extraction_quality` | extraction uncertainty | |

Reconciliation detectors mention unusable members in their notes ("2 line totals in this scope
could not be read; the subtotal was not checked") instead of reporting them again.

Markers: the profile's `zero_contribution_markers` (shipped default: `nil`,
`included_elsewhere`, `not_applicable` and `by_others`; the `boq` profile adds `not_offered`,
which `domain.boq_bid_prices` reports) in an amount contribute zero to a total
(the total is complete without a number), any other marker leaves the scope incomplete; `rate_only` means the item is not
counted (normalization sets `counts_toward_totals = false`); `lump_sum` in a quantity means
"one lump sum": `line_total` abstains, `required_values` does not report a missing quantity.

## What the profile decides

Generic code holds no domain vocabulary: what a token, a marker or a column means comes from
data, with today's conventions as the shipped defaults.

* **Currency vocabulary**: `backend/app/profiles/data/currencies.yaml` is loaded for every
  profile (it is in a subdirectory, so it is never read as a profile, and the startup profile
  check validates it): `aliases` (token -> ISO 4217 code), `symbols` (recognized in headers and
  next to numbers besides 2-5 letter words), `ambiguous_symbols` (several currencies: a number
  written with one has no decided currency, and a number format resolves one only through its
  Excel locale tag), `locale_currencies` (locale id -> currency for ambiguous symbols) and
  `number_format_symbols`. A profile's `currency_aliases` add or override aliases.
* **Zero in totals**: `zero_contribution_markers`, the value markers whose amount counts as zero
  in a total (default and `boq.yaml`: `nil`, `included_elsewhere`, `not_applicable`,
  `by_others`). Duplicates are rejected.
* **Yes/no words**: `boolean_words.true_words` and `false_words`, compared without outer
  whitespace and case (both shipped profiles: `true yes ja wahr y j x` and `false no nein
  falsch n`; quote them in YAML, which reads `yes` and `no` as booleans). A word in both lists
  is rejected; a profile without words reads no yes/no text, and such cells are reported as
  unreadable.
* **Normalization thresholds**: the `normalization` block (`NormalizationThresholds`):
  `type_mismatch_share` 0.5 and `type_mismatch_min_values` 3 (a column mapped to a number field
  by its header keeps the mapping only when at least this share of its values are numbers, once
  it has that many values), `min_contains_chars` 4 (shorter synonyms match only whole headers),
  `min_fuzzy_chars` 4 (shorter headers never match by approximate spelling),
  `structural_lookahead_rows` 3 and `data_lookahead_rows` 20 (structural header detection).
  Deployment-wide tunables (`header_scan_rows`, `type_dominance_threshold`,
  `fuzzy_header_threshold`) stay in `Settings.normalization`.
* **Detector parameters**: `detector_defaults` holds the profile's parameters per detector. A
  plan step runs with the detector's code defaults, then the profile's entry, then the step's
  own parameters (`plan_validation.step_config`: later layers win, mappings merge key by key,
  the result is validated against the config model). `GET /api/v1/detectors?profile_id=<id>`
  returns, as each entry's `profile_config`, what a step that sets no parameters runs with on
  that profile (every step of every run), so an interface shows the profile's values
  rather than the code defaults (`default_config`).
* **Severities**: every finding's severity comes from its detector's config. Besides the
  plannable `severity` of some detectors, the rules whose severity used to be fixed in code
  have profile-controlled settings named `severity_<rule>` (for example `severity_unique` of
  `field_constraints`, `severity_exact_duplicate` of `exact_duplicates`,
  `severity_display_rounding` of `subtotal` and `grand_total`; a `unit_compatibility`
  description rule carries its own `severity`), with the former values as defaults. Plans
  cannot set them. A setting called just `severity` is always the plannable one, so a profile
  entry `severity` means the same in every check. Three older plannable parameters keep their
  names: `severity_field_rule` and `severity_text_rule` of `reference_integrity` and
  `severity_by_field` of `required_values`. The detector catalogue lists every parameter with
  its default and who may set it. `extraction_quality` groups low-confidence cells by band (below
  the threshold, below half of it), so a changed severity never changes a fingerprint.

## Abstention

Abstain rather than guess. Arithmetic detectors use only `usable` and `inferred` inputs
(`inferred` values carry a caveat added by the issue factory). Unusable inputs never produce a
confirmed finding; they are counted in `coverage`, and a detector that could check only part
of the data says so in `notes`, so silence is never mistaken for a clean result.

## Coverage vocabulary

`DetectorResult.coverage` uses these keys (`contracts/conditions.py: Coverage`) for the shared
meanings; detectors may add specific keys (for example `tax_rows_without_rate`).

| Key | Meaning |
| --- | --- |
| `rows_checked` | rows on which the rule was evaluated |
| `rows_consistent`, `rows_inconsistent` | outcome of row checks |
| `rows_skipped_missing_inputs` | an input was empty |
| `rows_skipped_marker` | an input was a value marker |
| `rows_skipped_unusable_inputs` | an input was an error, unavailable, ambiguous or failed cell (reported by its owner) |
| `rows_skipped_not_applicable` | a documented abstention (e.g. a unit with a multiplier such as `100 St`) |
| `rows_failed` | the row check raised and was skipped (`row_guard`) |
| `totals_checked`, `totals_consistent`, `totals_inconsistent` | reconciliations of total rows |
| `totals_undecided` | the result depends on context the document does not contain |
| `totals_skipped_no_scope`, `totals_skipped_incomplete_scope`, `totals_skipped_missing_amount` | totals that could not be reconciled, and why |
| `cells_checked` | cell-level checks |

## Evidence classes

* `confirmed_rule_violation`: a deterministic rule failed on usable inputs, under every
  admissible reading of the document.
* `extraction_uncertainty`: the source could not be read or structured reliably (also: a
  total that matches none of several *structural* readings, because the mismatch may come from
  misreading the structure).
* `needs_external_context`: the document alone cannot settle it (a reference to a position in
  another document; a total whose result depends on undecided items that could not all be
  combined).
* `semantic_warning`: advisory text/unit rules (`unit_compatibility`).
* `suspected_anomaly`: statistical signals (none in Phase 1 except clearly labelled minority
  types in unmapped columns).
* `human_confirmed_error`: only from a reviewer's decision.

The issue factory downgrades confirmed findings computed from unverified cells (OCR/PDF below
the confidence threshold) to `extraction_uncertainty`, and adds caveat notes for inferred
formatting and for tables whose extraction needs review. Signals (`suspected_anomaly`,
`needs_external_context`) follow the same policy: a value can stand out only because it was
misread, so a signal computed from an unverified cell becomes `extraction_uncertainty` with an
"Evidence downgraded" note, and the other signals carry the same caveat notes. XLSX, CSV and
GAEB cells are read verbatim (no engine score), so this changes nothing for them; it applies to
PDF bills, whose text-layer values carry no engine score, and to OCR below the threshold. A
downgraded finding keeps its finding category, which comes from its check and rule only
([data model](data-model.md)): a wrong total on a PDF bill is an error to verify in the
source.

## Evidence rule

Every finding carries at least one evidence item from its detector (what was observed, the
rule, a calculation; notes the factory adds itself do not count), and a
`confirmed_rule_violation` points at the cells or the row where the rule failed: highlighted
`cells` or a `row` (input cells alone do not place it). `IssueFactory.create` refuses a finding
that breaks the rule with `IssuePolicyError`, and the pipeline checks every returned finding
again (`evidence_rule_problem`), so a finding without support cannot enter a run by any path.

The refusal is visible in every case:

* The issue rules come before the caps: when the detector's or the run's finding cap is
  reached, a finding that breaks the evidence rule (or another issue rule) is still refused for
  that rule and fails its check, instead of being reported as `limit_reached = "issues"`.
* The factory counts each refusal per detector and reason (`IssueFactory.refusals`). A
  detector that catches `IssuePolicyError` itself and goes on is `failed` all the same, with an
  error naming how many findings were refused and for which rule ("The issue policy refused 2
  findings of this check: 2 × a finding without evidence …"); the findings the factory accepted
  from it are kept, also when a run limit stopped it.

## Issue identity

`IssueFactory.create(..., subject=...)`: the fingerprint hashes detector, category, rule, the
table (sheet index and name), the row (source row number), the highlighted cells (source
coordinates) and the `subject`; the evidence digest hashes observed and expected values, the
subject and the raw and normalized values of every highlighted and input cell. A `subject` is
required for findings with neither cells nor a row (table-level findings), and fingerprints are
unique within a run: a second finding with the same fingerprint raises `IssuePolicyError`, so
a detector that reports two different findings at one place must distinguish them by subject
(`"quantity:minimum"`, the duplicated code, the unknown unit key). Review decisions are carried
forward only when fingerprint and digest both match.

## Total scopes (reconciliation)

`subtotal` and `grand_total` share one implementation of these rules
(`app/validation/contracts/scopes.py`, exposed as `ValidationContext.rows_in_scope`), so two
detectors can never disagree about which rows a total sums.

Vocabulary. A *total row* is a SUBTOTAL, GRAND_TOTAL, TAX or GROSS_TOTAL row with a usable
amount in the total field. CARRY_FORWARD rows (page running totals) are never totals of a scope
and never members. SUMMARY_LINE rows restate totals defined elsewhere: they are members only of
the total that closes their summary block. Rows a reviewer excluded are never members and never
checked. Members are summed by their **reported** amounts (never recomputed values, so one wrong
line is reported once, by `line_total`).

**Bases** (which rows are candidates) for a SUBTOTAL row `S`:

1. *Section*: `S.closes_section_id = X` (set by normalization or a reviewer): the ITEM and
   ADJUSTMENT rows between `X` and `S` whose `section_path` contains `X`. When this basis exists
   it is the only one.
2. *Code*: `S` has a code (`classification.code`) and the identifier field is mapped: the ITEM
   rows before `S` (after the previous grand or gross total) whose code segments
   (`app.core.codes`) start with `S`'s segments.
3. *Block*: the ITEM and ADJUSTMENT rows after the nearest preceding SUBTOTAL, GRAND_TOTAL or
   GROSS_TOTAL row (or the start of the table).
4. *Summary block*: when the rows since the previous boundary hold SUMMARY_LINE rows and no
   ITEM rows, the members are those summary lines.

Without a section basis, every basis that has at least one member is a candidate. A GRAND_TOTAL
row `G` has the span of rows after the previous GRAND_TOTAL or GROSS_TOTAL row (or the table
start); its bases are the counted items of the span, the summary lines of the span (when there
are any), and, when the span holds only ADJUSTMENT and TAX rows after a previous grand total
`G0` ("Summe nach Nachlass", or a "Gesamtsumme" after net and tax that was not worded as
gross), `G0` plus those rows.

**Membership of items.** `counts_toward_totals = true` counts; `false` never counts, except
that an item whose `not_counted_above_section_id = Z` still counts toward the subtotal of `Z`
and of sections inside `Z`; `null` (undecided, e.g. a Bedarfsposition that does not say) is an
*optional* term. Items left out are listed in a note.

**Readings** (value choices within one basis): every optional term in or out; every ADJUSTMENT
term with its sign as written or negated (documents write discounts as `-500` or as `500` under
"abzgl."); hidden rows (`source_hidden`) all included or all excluded (documents total with
`SUM` or with `SUBTOTAL(109, …)`). Readings are enumerated as exact sums (a set of distinct
sums, at most 4,096; beyond that the enumeration is *truncated* and only the all-in, all-out and
as-written readings are kept). Each reading is compared with `reconcile` (exact or rounded,
`TolerancePolicy.allowed_difference(expected, terms)` with the number of terms of the basis).

**Completeness.** A basis is incomplete when a member it would count has an unusable amount
(empty without a zero-contribution marker, ambiguous, failed, unavailable, error) or when the
explicit currencies of its members conflict. Incomplete bases are never summed partially.

**Outcome** for one total row:

| Situation | Result |
| --- | --- |
| some reading of some complete basis matches | consistent (a note names the reading when it is not the plain one) |
| one complete basis (or all complete bases have the same members), every reading enumerated, none matches | `confirmed_rule_violation` (expected = the closest reading; evidence lists the readings tested) |
| as above, but the enumeration was truncated | `needs_external_context` |
| several complete bases with different members, none matches | `extraction_uncertainty` (the structure has more than one reading) |
| no basis with members | abstain: `totals_skipped_no_scope` and a note |
| only incomplete bases | abstain: `totals_skipped_incomplete_scope` and a note naming the unusable members |

**Tax and gross totals** (`grand_total`). A TAX row's net is the nearest preceding
GRAND_TOTAL, or that total plus the adjustments between them (both readings, adjustments in
either sign); only ADJUSTMENT, TAX, TEXT, BLANK and CARRY_FORWARD rows may stand between them,
otherwise (or after a GROSS_TOTAL) the row has no net and is not checked
(`tax_rows_skipped_no_net`). The rate is read with the detector's `tax_rate_pattern` (one
capture group, the percent) from the row's text: the profile's label fields first, then the
other cells, never the amount. Without a rate the row is not checked (`tax_rows_without_rate`);
when one net has several tax rows whose rates differ or are not all stated, their bases are
unknown and none is checked (`tax_rows_skipped_mixed_rates`). Expected tax = rate × net / 100,
rounded per the detector's `tax_rounding` (the exact value is accepted too); a mismatch under
every reading is `tax_mismatch` (confirmed). A GROSS_TOTAL row = net + the adjustments (each
sign) + the tax rows between net and gross, judged like a subtotal (`gross_total_*` rules); any
unusable term makes it unchecked, and a gross total without a net or without a tax line after
its net is not checked (`totals_skipped_no_scope` and a note).

**Display rounding.** For tables from delimited text (printed exports where every line was
rounded for display), a difference beyond the tolerance but within the tolerance plus a
per-term drift allowance (`display_rounding_drift_per_term`, profile-controlled) is reported as
an informational `extraction_uncertainty` ("explainable by rounding of N printed values"), not
as a violation.

## Pipeline guarantees

* Isolation: a detector that raises is `failed` with a sanitized message (exception type and a
  log reference; only `WorkbenchError` messages, written for users, are shown); the others run.
  A detector that breaks an issue rule (`IssuePolicyError`: the evidence rule, an undeclared
  class or category, a missing subject, a repeated fingerprint) is `failed` with that rule's
  fixed reason ("The issue policy rejected a finding without evidence …") and a log reference.
* Admission: only findings that the run's factory created for the detector, unmodified, and
  that satisfy the evidence rule enter the run; otherwise the detector is `failed` and none of
  its findings are kept. A detector whose returned findings are all admissible but which caught
  the factory's refusal of others is `failed` with the number refused, and keeps the admissible
  findings (see "Evidence rule").
* A baseline step whose profile parameters are invalid is `failed` on its own; user and LLM
  plans with invalid parameters are rejected as a whole (`invalid_validation_plan`).
* Limits: per-detector time limit (checked while iterating rows; `stopped`, findings kept,
  `limit_reached = "time"`), per-detector and per-run finding caps (`limit_reached =
  "issues"`), run time limit (later steps `skipped` with a reason).
* Run status: `completed`; `completed_with_errors` when a detector failed or stopped;
  `failed` when every detector that executed failed, or when extraction failed (nothing runs).
* Plan trust comes from the code path: clients cannot send a plan; baseline plans carry no
  parameters; LLM plans must keep every registered check.

## Adding a detector

1. Create `validation/<package>/<name>.py` with the spec, a strict config model and `validate`.
2. Declare every evidence class and category it emits; pass a `subject` wherever one place can
   produce several findings.
3. Follow the ownership table: abstain on conditions other detectors own and count them.
4. Add `tests/unit/validation/<package>/test_<name>.py`: positive cases, clean data with zero
   issues, abstention, boundaries, config validation (unknown keys rejected, profile defaults
   accepted), applicability, fingerprint stability.
5. If the profile sets defaults, the profile check test covers them automatically.
