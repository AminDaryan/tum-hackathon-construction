# Canonical data model

Source of truth: `backend/app/models/`. Every model is an immutable Pydantic model
(`FrozenModel`) that rejects unknown fields. Changes create new objects through
`FrozenModel.evolve(**changes)`, which re-validates the result; `model_copy(update=...)` is not
used for domain changes because it skips validation. Computed fields (for example
`effective_evidence_class`) are serialized for clients but ignored when a document is parsed back.

## Entities

```
Document ── original_filename, format, uploaded_at, source_file (sha256 key), processing_status
   │
   └── Dataset (revision 1 = original extraction; corrections create revision N+1)
         │   profile_id/version, created_at, extraction (adapter, quality, warnings)
         └── Table ── name, source (sheet/page), header (row numbers + detection method)
               ├── Column ── original_header, normalized_name, inferred_type, type_profile,
               │             mapping (semantic field + method), header_currency, decimal_separator
               └── Row ── source_row_number, classification (kind, rule, section level,
                     │    counts_toward_totals), section_path, closes_section_id, excluded
                     └── cells{column_id: Cell}
                           raw_value · parsed_value · normalized_value · data_type · parse_status
                           formula (expression + cached_result_available) · number_format
                           source (sheet + A1 / CSV record / GAEB row, column + XML line / PDF page + bbox)
                           extraction_confidence (OCR/PDF only)
```

Invariants checked on construction (`Table._consistent`): column ids and row ids are unique,
each semantic field is mapped to at most one column, and every row has exactly one cell per
column of its table.

## Identity and navigation

* `table_id`, `column_id` and `row_id` are opaque ids assigned at ingestion and persisted.
* A cell is addressed by `CellRef(table_id, row_id, column_id)`; issues carry a copy of the cell's
  `SourceLocation`, so the UI can jump to the cell (and the original sheet coordinate) no matter
  how the grid is sorted or filtered.
* `position` fields record ingestion order only. Display order is a view concern.
* Anything that must survive re-normalization (issue fingerprints, reviewer schema decisions)
  is keyed by **source coordinates** (sheet index, source row and column numbers), never by the
  generated ids.

## Normalization output for cells

Normalization and the test builders construct every cell through `app/models/cell_rules.py`,
so detectors are tested against exactly what real files produce:

| Raw content | `data_type` | `parse_status` | `parsed_value` | `normalized_value` | Example |
| --- | --- | --- | --- | --- | --- |
| missing cell, empty, blank text (whitespace or invisible format characters only) | `empty` | `not_applicable` | null | null | `"\u00a0 "` (raw text kept) |
| typed number, unambiguous number text | `number` | `exact` | number | same | `12.5`, `"1.234,50"` |
| number text resolved by column or document evidence | `number` | `inferred` | number | same | `"1,234"` in a column that uses `,` for thousands |
| number text with several readings | `unknown` | `ambiguous` | null | null | `"1.234"` without evidence |
| text in a numeric/date field that is not one; a number outside the bounds | `text` | `failed` | text (raw) | text (collapsed) | `"approx. 5"`, `"1E+999"` |
| profile value marker in a numeric field | `text` | `marker` (`marker` set) | text (raw) | text (collapsed) | `"Incl."`, `"entfällt"`, `"psch"` |
| plain text | `text` | `not_applicable` | text (raw) | text (collapsed) | `"  Aushub   BK 3"` → `"Aushub BK 3"` |
| unit text | `text` | `not_applicable` | text (raw) | canonical unit id when resolved, else collapsed text | `"m²"` → `"m2"` |
| boolean, date, datetime | `boolean` / `date` / `datetime` | `exact` (`inferred` when the profile's date order decided) | typed | same | |
| undecidable day/month order | `unknown` | `ambiguous` | null | null | `"03/04/2026"` with `date_order: auto` |
| spreadsheet error literal | `error` | `exact` | error | same | `#REF!` |
| formula without a cached result | `unknown` | `unavailable` | null | null | file saved without calculation |

*Collapsed text* is Unicode NFC with whitespace runs replaced by one space and outer whitespace
removed; there is no case folding or NFKC, so the normalized text is still what the document
says. Comparison keys (header matching, codes, units) are derived separately. `raw_value` is
always the extracted text, never stripped.

## Values and numbers

Typed values are tagged unions (`kind`: `number`, `text`, `date`, `datetime`, `boolean`,
`error`). Numbers are `Decimal` and serialize as strings. `NumberValue` also records `currency`,
the ISO code resolved from an explicit marker on the cell (symbol, code or Excel number format),
and `is_percent` (the value is already divided by 100).

Floats never enter the model. `ExactDecimal` rejects floats, booleans and non-finite values;
`BoundedDecimal` (used for cell numbers) also limits values to 28 significant digits and an
adjusted exponent between −20 and 24, so the exact arithmetic of the detectors cannot overflow
its context. Spreadsheet numbers that a library hands over as binary floats are converted with
15 significant digits (`Decimal(format(f, ".15g"))`), which is what Excel displays and stores
as text, so `0.1 + 0.2` style artefacts never reach a check. Numbers outside the supported range
are `failed` with a note rather than rounded silently.

`parse_status` is categorical, never an invented score:

| Status | Meaning |
| --- | --- |
| `exact` | Read verbatim from a typed source (XLSX number) or unambiguous text |
| `inferred` | Needed column- or document-level evidence, e.g. the decimal separator of `1,234` resolved from other values in the column |
| `ambiguous` | More than one interpretation remained; **no value is chosen** |
| `failed` | Text did not match the expected type (e.g. `approx. 5` in a quantity column), or a number is outside the supported range |
| `unavailable` | The source holds no value (formula without a cached result) |
| `not_applicable` | Empty cell or plain text |

`extraction_confidence` is reported only by engines that estimate (the OCR of scanned PDF
pages). Verbatim digital extraction (XLSX, CSV, GAEB) leaves it `null`: the value was read, not
estimated, and an invented `1.0` would be a fake confidence number. The issue factory
downgrades confirmed rule violations and signals (`suspected_anomaly`,
`needs_external_context`) to `extraction_uncertainty` when a cell they highlight or were
computed from is a PDF cell whose value is not verified: one from a PDF's text layer, which has
no score, or one read by OCR with a score below the configured threshold (default 0.9). A
downgraded finding keeps its finding category (see below).

Currency is never assumed. An explicit ISO code or an unambiguous symbol (`€`, `£`, `CHF`)
resolves; `$` and `¥` stay ambiguous unless an Excel number format carries a locale tag (for
example `[$$-409]` = USD, `[$$-C09]` = AUD); unmarked amounts have unknown currency.

## Row kinds, sections and totals

`item`, `section`, `subtotal`, `grand_total`, `tax`, `gross_total`, `adjustment` (a discount or
surcharge on a total), `carry_forward` (a page running total such as "Übertrag"),
`summary_line` (a line of a recap block that restates a total defined elsewhere), `text`,
`blank`. The kind is assigned by normalization from the domain profile's patterns and
structural rules, and records the rule that produced it (for example `pattern.subtotal`) so a
reviewer can see why.

The decision table (`RowClassificationRules` in `backend/app/models/profile.py`):

1. `blank`: no non-empty cell.
2. Label patterns in precedence order: carry-forward, gross total, tax, grand total,
   adjustment, summary-block heading, subtotal, section.
3. A total-like match gives that kind only when the quantity is empty, not both unit price and
   line total are filled, and some amount cell is non-empty; otherwise the row is an item (a
   row with a quantity is an item whatever its text) or text.
4. Inside a summary block, a row with an amount and neither quantity nor unit price is a
   `summary_line`.
5. `item`: quantity or unit price filled, or line total and unit filled (lump sums).
6. `section`: a section pattern matched, or the row's code is a strict prefix of the next
   item's code, and neither quantity nor unit price is filled.
7. Anything else with a numeric cell is `text` with the needs-review warning
   `unclassified_amount_row`; everything else is `text`.

Value markers (`ParseStatus.marker`, `Cell.marker`) are conventional tokens in numeric columns,
with a generic meaning from the profile: the profile's `zero_contribution_markers` (by
default `nil`, `included_elsewhere`, `not_applicable` and `by_others`; the `boq` profile adds
`not_offered`, a bid's "nicht angeboten") contribute zero to a total; `rate_only` makes an item not counted; `lump_sum` in a quantity means one lump sum. No
number is invented. Yes/no fields read the profile's `boolean_words`; the thresholds of header
matching and type checks are its `normalization` block (see the validation engine page, "What
the profile decides").

Sections are hierarchical:

* `RowClassification.section_level` (section rows only): 1 is the outermost level. Levels come
  from the depth of the section's code (`01` = 1, `01.02` = 2) when it has one.
* `Row.section_path`: the ids of the enclosing section rows, outermost first. `section_row_id`
  (computed) is the innermost one.
* `Row.closes_section_id` (subtotal rows): the section whose items the subtotal sums, when
  normalization could establish it (by a matching code, otherwise the innermost open section).
  `null` means the scope is unknown; reconciliation detectors then establish a scope by other
  documented means or abstain.
* `RowClassification.counts_toward_totals`: `true`, `false` for items that are listed but not
  added into totals (Alternativ- and Wahlpositionen, "Bedarfsposition ohne GB", items priced
  "nur EP", English optional or alternative items), or `null` when the document does not say
  (a Bedarfsposition without "mit/ohne GB"). `totals_rule` names the first matching profile
  totals rule (`TotalsRule`: pattern, where to search: label, category column, text in the
  amount cell, continuation lines). A SECTION row's match is inherited by its items with
  `not_counted_above_section_id`: they still count toward that section's own subtotal. Such
  items are checked line by line; reconciliation treats `null` as both readings
  (`docs/architecture/validation-engine.md`).
* `Row.source_hidden` and `Row.outline_level`: the row was hidden (or grouped) in the source.
  Hidden rows are kept and checked; reconciliation tests totals with and without them.
* `Row.belongs_to_row_id`: a text continuation line (long text below an item) points at the item.
* `Row.excluded`: a reviewer marked the row as not data (a mis-detected header or footer line).
  Excluded rows are skipped by every check and never counted.

## Reviewer schema decisions

`SchemaDecisions` (`backend/app/models/schema.py`) holds what a reviewer decided in the
extraction review step: header rows, column-to-field mapping, row-kind overrides, whether items
count toward totals, section levels, which section a subtotal closes, unit aliases, rows that
are not data and hidden sheets to include (ADR 0002), keyed by source coordinates. Normalization applies them on top of automatic
detection (methods `user`, rule `user`), so every check downstream reflects them. Phase 1
applies decisions in `build_dataset`; the review screen and API that collect them come in
Phase 2.

A file can declare its own structure the same way: a GAEB adapter fills `RawSheet.declared`
(a `TableDecisions`) with the row kinds, section levels, `counts_toward_totals` and the column
mapping the XML states. The reviewer's decisions are laid over it with `TableDecisions.over`,
so a reviewer still wins. Rows decided by the file carry rule `declared`, rows decided by a
reviewer rule `user`, and each source has its own extraction note (`structure_declared`,
`schema_decisions_applied`). Profile fields with `match_headers: false` (for example
the standard text key) are never matched from spreadsheet headers;
only a declared structure or a reviewer maps them (ADR 0009). BoQ profile 1.8.0 also maps
item discounts from the exact, percent-qualified headers `Nachlass %`, `Positionsnachlass %`
and `item discount %`. Its `match_headers: exact` mode accepts only the listed
`exact_header_synonyms`, without implicit label/field-id, substring or fuzzy matches.
Unqualified `Nachlass` / `Rabatt` and monetary discounts stay unmapped. Item discounts feed
the existing GAEB rounding rule in the line-total check; a blank discount means no discount.
Discounts above 100% are reported by the bid-price check (both `125` and `125%`). A 100%
discount and signed surcharges (negative percentages) remain permitted; there is still no
lower bound on quantities or prices.

## Revisions and audit

`Dataset.revision` starts at 1. A correction (Phase 2) never edits a revision; it writes revision
N+1 of the same dataset (same ids, `parent_revision = N`) and an audit event that records the
original value, the new value, the issue that motivated it and who authorized it (ADR 0001).
Re-normalization creates a new dataset. Validation runs and issues reference the exact
`(dataset_id, revision)` and profile version they examined.

## Issues

`ValidationIssue` (Part H of the brief) records:

* **Location**: `table_id`, `row_id`, `affected_cells` (the highlighted cells) and
  `input_cells` (the cells the finding was computed from, such as the factors of a product or
  the summands of a subtotal).
* **Provenance**: `detector_id`, `detector_version`, `rule_id` (which rule of the detector, for
  example `line_total`, `minimum`, `unique`), `validation_run_id`, dataset id and revision.
* **Meaning**: `issue_category`, `severity`, `evidence_class`, and the computed
  `finding_category` (below).
* **Content**: `title`, `explanation`, `observed_value`, `expected_value`, structured
  `evidence[]`, `suggested_action` (the recommendation the interface shows).
* **Signals**: `extraction_confidence` (lowest reported confidence among the involved cells,
  OCR/PDF only) and `anomaly_score`.
* **Review state**: `review_status`, `reviewer_comment`, `reviewed_at`, `version` (incremented
  by every review decision; updates naming a stale version are rejected, ADR 0005), and the
  computed `effective_evidence_class`, which becomes `human_confirmed_error` only through a
  reviewer's decision; detectors cannot assign it.

Evidence items have a `kind` (`calculation`, `value`, `rule`, `comparison`, `reference`,
`note`), a readable `detail`, the `cells` involved, scalar `data` (decimals as exact strings) and,
for recomputations, a typed `calculation`: the operation (`product`, `sum`, `percentage`,
`difference`, `comparison`), the operands with their cells (long sums may be capped, `terms`
always holds the full count), the exact result, the rounding applied, the reported value, the
difference and the allowed difference. Every export and the UI render calculations from this
one structure.

`estimated_financial_impact` is present only when it can actually be calculated: an `amount`
in an explicit currency (required; ADR 0004), with `basis`, a `kind` and, for `discrepancy` and
`reference_deviation`, `reported` and `recomputed`. For `discrepancy`, `amount = reported -
recomputed`, and the kind says only that two figures disagree, not which one is wrong.
`potential_double_count` is the value of rows that look duplicated. `reference_deviation`
(`statistical.peer_price`) is what is at stake if the row were priced like comparable rows:
`reported` is its unit price, `recomputed` the reference unit price (the median of the
comparable rows), and `amount` = quantity × (reported − recomputed) × the row's discount
factor, rounded to two decimals.

`anomaly_score` is a raw detector score with its method and an explicit interpretation. It is
never presented as a probability unless `calibrated` is true, which requires a
`calibration_reference` that the detector's spec declares. An anomaly score can never back a
confirmed rule violation.

### Finding categories

`finding_category` says what a finding means for the person who checks the bill by hand (plan
section 5a, approved on 2026-11-20; [ADR 0010](../decisions/0010-boq-anomaly-detection.md)):

| Finding category | When |
| --- | --- |
| `error` | Would be objectively wrong |
| `omission` | Work the bill needs, or says is paid separately, for which no position pays |
| `inconsistency` | Two or more positions contradict each other |
| `ambiguity` | A description leaves open what to do or supply |
| `risk` | Clear, but may cost the bidder money or time, or lead to a dispute |
| `change_order_opportunity` | The bill admits that conditions or decisions stay open until after award |
| none (`null`) | The finding is about reading the file (a value that could not be read reliably, an unknown unit, a formula without a stored result, a total whose rows or rounding cannot be told apart, a value of undecidable type); the interface shows "Reading the file" |

It is a computed field like `effective_evidence_class`: the API, the JSON export and the stored
payloads carry it as serialized, but loading drops the stored value and computes it again, so
it has no column, needs no migration and always follows the current tables, also for findings
stored before a change to them. `finding_category_of` in `backend/app/models/finding_category.py`
decides it from the detector and the rule, in this order:

1. the rule's entry in `CATEGORY_BY_RULE`, when it has one;
2. the detector's entry in `CATEGORY_BY_DETECTOR`, which has an entry for every registered
   detector (a test fails otherwise);
3. none, for a detector the tables do not know.

The evidence class does not decide it, and neither does a review decision. The evidence class
says how far a finding can be trusted, the category what it means if it holds: a finding
computed from values the extraction could not verify (a PDF's text layer, OCR below the
threshold) is downgraded to `extraction_uncertainty` by the evidence policy and keeps its
check's category, so a wrong line total on a PDF bill is an `error` to verify in the source. A
reference that matches nothing while some identifiers could not be read stays an `ambiguity`.

| Detector or rule | Finding category |
| --- | --- |
| `deterministic.line_total`, `deterministic.subtotal`, `deterministic.grand_total`, `deterministic.required_values`, `deterministic.numeric_validity`, `deterministic.field_constraints`, `deterministic.formula_errors`, `deterministic.data_type_conformance`, `deterministic.unit_compatibility`, `deterministic.hierarchy`, `deterministic.unit_price_components`, `domain.boq_bid_prices`, `domain.boq_typos` | `error` |
| `deterministic.exact_duplicates`, `deterministic.currency_consistency`, `domain.standard_text_keys`, `statistical.rate_consistency`, `statistical.quantity_factor`, `semantic.unit_fit`, `semantic.section_fit`, `machine_learning.near_duplicates`, `domain.model_quantities`, `domain.boq_tender_comparison` | `inconsistency` |
| `domain.boq_companion_work`, `domain.boq_separate_payment`, `domain.boq_numbering` | `omission` |
| `deterministic.reference_integrity`, `domain.boq_required_attributes`, `domain.boq_description_clarity`, `domain.boq_contradictions` | `ambiguity` |
| `domain.boq_clauses`, `domain.boq_position_types`, `statistical.peer_price`, `statistical.historical_price`, `statistical.open_price_reference`, `llm.bill_review` | `risk` |
| `deterministic.extraction_quality`, `deterministic.unit_vocabulary` | none |
| rule `same_description_dimension` of `deterministic.unit_compatibility` | `inconsistency` |
| rule `formula_result_unavailable` of `deterministic.formula_errors` | none |
| rule `subtotal_scope_ambiguous` of `deterministic.subtotal` | none |
| rule `subtotal_display_rounding` of `deterministic.subtotal` | none |
| rule `grand_total_scope_ambiguous` of `deterministic.grand_total` | none |
| rule `grand_total_display_rounding` of `deterministic.grand_total` | none |
| rule `gross_total_scope_ambiguous` of `deterministic.grand_total` | none |
| rule `gross_total_display_rounding` of `deterministic.grand_total` | none |
| rule `ambiguous_value` of `deterministic.data_type_conformance` | none |
| rule `price_below_floor` of `domain.boq_bid_prices` | `risk` |
| rule `assumed_condition` of `domain.boq_clauses` | `change_order_opportunity` |
| rule `deferred_decision` of `domain.boq_clauses` | `change_order_opportunity` |
| rule `document_reference` of `domain.boq_clauses` | `ambiguity` |
| rule `vague_wording` of `domain.boq_clauses` | `ambiguity` |
| rule `open_decision` of `domain.boq_description_clarity` | `change_order_opportunity` |
| rule `misplaced_item` of `domain.boq_numbering` | `error` |
| rule `model_position_missing` of `domain.model_quantities` | `omission` |
| rule `tender_position_missing` of `domain.boq_tender_comparison` | `omission` |
| rule `r016` of `llm.bill_review` | `error` |
| rule `r018` of `llm.bill_review` | `error` |
| rule `r083` of `llm.bill_review` | `error` |
| rule `r112` of `llm.bill_review` | `error` |
| rule `r023` of `llm.bill_review` | `inconsistency` |
| rule `r051` of `llm.bill_review` | `inconsistency` |
| rule `r082` of `llm.bill_review` | `inconsistency` |
| rule `r084` of `llm.bill_review` | `inconsistency` |
| rule `r085` of `llm.bill_review` | `inconsistency` |
| rule `r031` of `llm.bill_review` | `ambiguity` |
| rule `r033` of `llm.bill_review` | `ambiguity` |
| rule `r038` of `llm.bill_review` | `ambiguity` |

The checks of step B2 fill `omission`, `risk` and `change_order_opportunity`; the tender
review's numbering check assigns `omission` as well (numbers skipped, sections without
items), the peer-price check and the two price context checks assign `risk`, and the
comparison checks of step B3 `inconsistency`. The categories of the four tender review checks were
proposed on 2026-11-21 and wait for the owner's approval, with the two rule entries added
when B2 merged them (`open_decision` a `change_order_opportunity`, `misplaced_item` an
`error`). The Claude bill review (`llm.bill_review`) names an issue type of the catalogue
per claim, and its rule is that type (`r081` for R081): a price that stands out is a `risk`,
the other types take the category of the checks of the same kind; proposed on 2026-11-22 for
the owner's approval. The run's issue list filters by `finding_category` (`none` selects the findings without one), the run's
`issue_counts` count by it, and `issues.csv` and the `Issues` sheet of the run's Excel workbook
have it as the column after the severity. The [detector catalogue](detector-catalogue.md)
lists the category of each check.

### Fingerprints

`fingerprint` hashes the detector id, category and rule id, the table (sheet index and name),
the row (source row number), the **source coordinates** of the highlighted cells (never
generated ids or values) and the issue's `subject`, so the same finding at the same place in a
later run or after re-normalization gets the same fingerprint. `subject` names what the
finding is about when the place alone does not (a field id, a constraint, a group key); it is
required for findings with neither cells nor a row, and fingerprints are unique within a run
(ADR 0003). `evidence_digest` hashes the observed and expected values, the subject, and the
coordinate, raw text and normalized value of every highlighted and input cell. A review
decision will be carried forward only when both match: same place and same evidence.

### Who may claim what

Each detector category may emit only certain evidence classes, enforced when a detector spec is
defined and again by the issue factory:

| Detector category | May emit |
| --- | --- |
| `deterministic`, `domain` | every detector class (`confirmed_rule_violation`, `suspected_anomaly`, `semantic_warning`, `extraction_uncertainty`, `needs_external_context`) |
| `statistical`, `machine_learning`, `research` | `suspected_anomaly`, `extraction_uncertainty`, `needs_external_context` |
| `semantic` | `semantic_warning`, `needs_external_context`, `extraction_uncertainty` |

Issues are created only by `IssueFactory`, which assigns ids, fingerprints and digests and
applies the evidence policy; the pipeline rejects issues that the factory did not create or that
were modified afterwards.

**Evidence rule.** Every finding carries at least one evidence item from its detector (notes the
factory adds itself, such as a downgrade or a caveat, do not count), and a
`confirmed_rule_violation` points at the cells or the row where the rule failed (highlighted
cells or a row; input cells alone do not place it). The factory refuses a finding that breaks
the rule, and the pipeline checks every returned finding again; the detector is then `failed`
with the rule it broke, and the other detectors still run.

## Problems and explanations

A **problem** (`models/problem.py`) groups the findings of one run that concern the same
mistake: a wrong unit price can break its line total, the subtotal and the grand total, and
stand out against similar positions, which is four findings and one problem. It lists its
`issue_ids`, the `primary_issue_id` shown first, `links` saying why two findings belong
together (`same_cell`, `same_row`, `carried_difference`, `same_group`), the `anomaly_type` (one
of the seven: `price`, `quantity`, `unit`, `semantic`, `structural`, `logical`, `duplicate`),
and `money_at_stake` with its `currency` only when the amount is exact in an explicit currency.
Problems are computed from the stored findings whenever they are shown, never stored.
`services/problems.py` joins them deterministically (`GET /validation-runs/{run_id}/problems`):
the same cell, the same row, or a total's finding computed from a highlighted cell with the
same exact amount (two unrelated mistakes under one subtotal stay apart). The primary finding
is the strongest (confirmed first, then severity, then an item row before a total); its exact
amount is the money at stake and its recomputed value the `corrected_value`; amounts of the
other findings are never added.

An **explanation** (`models/explanation.py`, table `explanations`) is a local language model's
account of one problem, stored per run and `problem_id`: its `status` (`queued`, `running`,
`completed`, `failed`), the `claims` it makes (`summary` or `next_check`; the model's text with
slots such as `{F1.unit_price}`, the `rendered` text with the stored values filled in, and the
findings it `cites`), the claims verification `dropped` with the reason, and what is needed to
judge and repeat it: provider, model and its digest, server version, prompt version, a digest
of the input, the prompt and the raw output (each at most 64 KiB), the error of a failed one
and the duration. `uow.explanations` stores them (`add`, `update`, `get`,
`latest_for_problem`, `list_for_run`); schema version 5 added the table. Nothing creates
explanations in this version.

## Storage and schema versions

The SQL adapter (`backend/app/repositories/sql/`, SQLAlchemy Core) stores each record whole as
a JSON payload (a dataset revision as a compressed snapshot) plus the indexed columns projected
from it; the payload is the source of truth, and the columns are rewritten from it on every
write. The same tables work on SQLite and PostgreSQL. Text that orders a listing is compared by
code point on both (`COLLATE "C"` on PostgreSQL), so the issue order does not depend on the
server's collation.

The database records its schema version (`schema_info`). This build writes **version 7**:

| Version | Change |
| --- | --- |
| 1 | the first layout |
| 2 | issues gain `document_id` (carrying review decisions within a document), `version` (compare-and-set reviews, ADR 0005), `reviewed_at` and `seq`; impacts without a currency are dropped |
| 3 | datasets gain `table_count` and `row_count` (document listings read them instead of decoding snapshots) |
| 4 | issues gain `rule_id`; the run-order index follows the issue order (detector, rule, fingerprint and insertion sequence after the source position) |
| 5 | the `explanations` table (language model explanations of a run's problems, see above) |
| 6 | the `projects` table (a bid's documents and its latest project-wide validation) |
| 7 | the `users` table (user accounts: name, email, role, active flag, and the SHA-256 digest of the personal access token in a unique column; [ADR 0015](../decisions/0015-users-and-roles.md)) |

Each version change comes with a migration step in `backend/app/repositories/sql/migrations.py`
(`MIGRATIONS`: the step from version *n* upgrades *n* to *n* + 1). An older database is upgraded
by applying the pending steps in order, in one transaction: if a step fails, nothing changes.
Step 3 to 4 fills `rule_id` from each stored issue's payload (`default` when it names none);
step 4 to 5 creates the empty `explanations` table, 5 to 6 the `projects` table and 6 to 7 the
`users` table. A database written by a newer build is
always refused, so an older build never misreads newer records.

When an older database is upgraded is a setting (`TWB_PERSISTENCE__AUTO_UPGRADE`):

* `sqlite` (the default): SQLite files are upgraded at start-up, after a consistent copy is
  written next to the file (`TWB_PERSISTENCE__BACKUP_BEFORE_UPGRADE`, on by default); an older
  PostgreSQL database is refused with a message naming `db upgrade`, because a shared server
  database should be backed up and upgraded once, deliberately.
* `always`: every database is upgraded at start-up (instances starting together take turns
  under an advisory lock).
* `never`: every older database is refused.

`python -m app.cli db current` reports the recorded version, this build's version and the
pending steps; `db upgrade` applies them. Commands and backups:
[deployment](../deployment.md#migrations).
