# Progress

Where each part stands, as of 2026-11-21. The plan is in [NEXT_STEPS.md](NEXT_STEPS.md); this
page says what was built, how it was checked and what is still open.

## Phase 1 and round 1

Merged into `main` with pull request #3 on 2026-11-20.

| Part | State | Where |
| --- | --- | --- |
| Ingestion (XLSX, CSV) with security checks | done | `backend/app/ingestion/` |
| Normalization | done | `backend/app/normalization/` |
| 14 deterministic detectors | done | `backend/app/validation/deterministic/`, [catalogue](../architecture/detector-catalogue.md) |
| REST API, with optional sign-in and background runs | done | `backend/app/api/`, `backend/app/services/`, [REST API](../api/rest-api.md) |
| Exports: issues CSV, tables ZIP, JSON | done | `backend/app/exporters/` |
| Persistence: SQLite or PostgreSQL, schema version 4, versioned migrations, `python -m app.cli db` | done | `backend/app/repositories/`, [data model](../architecture/data-model.md#storage-and-schema-versions) |
| Web interface, served by the backend in the container image | done | `frontend/`, `backend/app/api/interface.py` |
| Container image and Compose file, logging | done | `Dockerfile`, `docker-compose.yml`, [deployment](../deployment.md) |
| Synthetic benchmark | done | `backend/app/evaluation/`, [evaluation](../evaluation/README.md) |
| Browser end-to-end test (Playwright, Chromium) | done | `frontend/e2e/` |
| Spreadsheet-style grid of the brief (Part J) | in part: the table preview marks the rows and cells of the latest run's findings; no sorting, filtering or search | `frontend/src/features/workspace/` |

## Step A2

One pull request that finishes the smaller fixes of round 1 (see
[NEXT_STEPS.md](NEXT_STEPS.md), section 2). The backend tasks T1 to T5, the interface tasks U1
to U7 and this documentation pass (D1 to D8) are done and merged on
`claude/project-thread-0s4qdy`. The two independent reviews, a security review and a contract
and data-integrity review, are done as well: each reviewer fixed what it could prove (every
code fix with a test that failed before it, the two corrections of the REST API page with tests
that pin what it now says), and their fixes are merged and checked with the rest (below).
The questions they leave for the owner are under [Open questions](#open-questions). The owner
merges.

Backend changes of A2: `mypy` in strict mode reports no issues in the `app` package and runs in
CI (K9); `GET /detectors?profile_id=` gives every check its `profile_config`, the parameters a
run on that profile uses when the plan sets none (K8); a check that goes on after the issue
policy refused some of its findings is reported failed, also at the finding caps, and keeps the
findings the policy accepted (T3); the duplicate check's profile-only severity is now called
`severity_exact_duplicate` (T4, see the [upgrade notes](../deployment.md#upgrade-notes));
health and the baseline plan's note say that adaptive AI planning is not available in this
version (K10).

Interface changes of A2: the run configuration starts every parameter at the dataset profile's
value (K8); "Not available in this version" for adaptive AI planning (K10); every control has a
hit area of at least 44 × 44 px, 48 × 48 on coarse pointers, measured by
`frontend/e2e/touch-targets.spec.js`; "Reset to defaults" keeps focus in the panel and is
announced; the run summary counts selected checks and says that checks a dataset cannot use
are skipped and listed after the run; a rejected plan lists every problem by check, including
the ones that concern no check; the browser test's backend gets only the settings the test
sets, and each checkout has its own Playwright output folder.

Review fixes of A2: the served interface never answers for hidden files or directories
(`.env`, `.git/`) or for a path that its file lookup turns into one under `/api` (`//api/...`,
`/x/../api/...`), and its files forbid framing by other sites (clickjacking); a page offset
above 2^63 − 1, which no database can bind, is `422 request_validation_failed` instead of a
`500`; the CSRF refusal quotes back at most 255 characters of the origin, like the other
refusals; the interface counts the detectors that a run's time limit stopped, and says
"1 detector completed" in the singular; the REST API page describes the plan size errors, the
CSRF refusal's details and the exposed headers as the API behaves.

## GAEB DA XML import

Pull request #4 (branch `gaeb-import`), built by a teammate; merged into `main` on 2026-11-20.

| Part | State | Where |
| --- | --- | --- |
| GAEB DA XML import | done (branch `gaeb-import`): X81, X83, X84 in version 3.3, STLB-Bau keys compared within a file ([ADR 0009](../decisions/0009-gaeb-import.md)) | `backend/app/ingestion/gaeb/`, `backend/app/validation/domain/boq/` |

## A2 and the GAEB import together

The branch `claude/project-thread-0s4qdy` brings step A2 together with `main`, which holds the
GAEB import since 2026-11-20; pull request #5 merged it into `main` on 2026-11-20 (merge commit
`10d6ca9`). Putting the two together needed four small changes, and none of them changes what
the application does: strict `mypy` skips the missing type information of lxml (lxml ships
none, and the lxml-stubs package lags behind lxml 6); the import's flag reading and the
discount helper of `deterministic.line_total` got types that strict `mypy` accepts; and the
integration test that counts the baseline detectors expects 15 instead of 14, because the
import adds `domain.standard_text_keys`. Its checks are below.

## Phase B: steps B0 and B1 (in `main`)

Built on the branch `wp/b01` and merged onto `claude/project-thread-0s4qdy` at commit `35a3926`
(A2 and the GAEB import, the last commit of pull request #5) on the branch `wp/b01-main`.
What `main` gained after `35a3926` (the merge commit `10d6ca9` of pull request #5; research
reports, the opening speech and the estimator interview in `docs/product/`; and their rows in
the README) is documentation only; the branch merged it up to `dd4010f`. Pull request #6
merged the branch into `main` on 2026-11-20 (merge commit `d462253`).

| Part | State | Where |
| --- | --- | --- |
| B0: Python 3.12 or later, NumPy and pandas (floats only inside statistics; money stays `Decimal`) | done | `backend/pyproject.toml`, [LICENSES.md](../../LICENSES.md) |
| B0: item frame, robust statistics and text keys for the comparison checks | done | `backend/app/validation/support/` |
| B0: profiles add checks to the baseline plan (`baseline_detectors`); the planner is injected through the workbench | done | `backend/app/models/profile.py`, `backend/app/validation/planner.py`, `backend/app/services/workbench.py` |
| B0: the evidence policy applies to signals (unverified cells make a signal an extraction uncertainty) | done | `backend/app/validation/contracts/issue_factory.py` |
| B0: language model settings and an `llm` block in the health answer; nothing connects without a provider, and the model allow-list was empty in B0; `main` added `qwen2.5:7b-instruct` on 2026-11-21 ([open question 15](#open-questions)) | done | `backend/app/agents/`, `backend/app/core/config.py` |
| B0: explanation records and their storage, schema version 5 | done | `backend/app/models/explanation.py`, [data model](../architecture/data-model.md#storage-and-schema-versions) |
| B0: the decision record of Phase B | done | [ADR 0010](../decisions/0010-boq-anomaly-detection.md) |
| B1: BoQ benchmark variant (a Titel per trade, similar and repeated positions, planted errors of all seven anomaly types, recall per check and kind) | done | `backend/app/evaluation/`, [evaluation](../evaluation/README.md#the-boq-variant), [report](../evaluation/boq-benchmark.md) |
| B1: errors planted into a folder of real bills, in memory (`--inject-into`) | done | [evaluation](../evaluation/README.md#plant-errors-into-your-own-bills) |

Bringing them onto A2 and the import applied the first nine decisions of the review that
aligned Phase B with the import, each as its own commit after the merge:

1. Phase B uses the import's `standard_text_key` (no header maps it); B0's
   `standard_reference` is gone, and the item frame reads the key.
2. The six unit price components stay, but no header maps them: a column mapped by a
   look-alike header would feed a confirmed rule, and a partly mapped breakdown sums short. A
   reviewer maps them; the BoQ benchmark maps its EP-Anteil columns the way a reviewer would,
   so `component_sum_error` can no longer be planted into a folder of unreviewed bills.
3. B0's decision record is ADR 0010 (ADR 0009 is the import's).
4. `boq.yaml` is version 1.3.0 (both branches had set 1.2.0).
5. The lock file was rebuilt from fresh environments, and [LICENSES.md](../../LICENSES.md)
   lists the five libraries the lxml wheels link statically, one of them under LGPL (open
   question 14).
6. The item frame reads the long text and the item discount (`discount_factor`), which the
   reference amount of B3 is to apply.
7. "The benchmark is unchanged" compares its quality numbers, not its timing lines.
8. The BoQ benchmark writes the import's German item type names in every second Positionsart
   column.
9. The BoQ benchmark maps its STLB-Bau column as a reviewer would, so
   `domain.standard_text_keys` runs on its bills with keys.

The later decisions of that review (writing GAEB files in the benchmark, B1.7; the checks of
steps B2 to B7; and detector counts that the tests read from the API instead of hard-coding
them) are not part of this branch. Strict `mypy` also needed the pandas type stubs
(`pandas-stubs`, a development dependency), and in the tests that B0 and B1 added every
`type: ignore` now has a real type instead or its reason on the same line. The checks on that
branch are in [Check it yourself](#check-it-yourself).

## Older GAEB formats, PDF bills, OCR, the Excel export and the peer-price check (in `main`)

Built by teammates and pushed to `main` on 2026-11-20 (commits `c2e2ee2` to `5439d02`); the
branch of pull request #10, `claude/project-thread-0s4qdy`, merged them, and this branch merged
that branch.

| Part | State | Where |
| --- | --- | --- |
| GAEB DA XML 3.1 and 3.2, phase X86, and GAEB 90 (`.d81`, `.d83`, `.d84`, `.d86`) read into the same model | done | `backend/app/ingestion/gaeb/`, [ADR 0010 (older GAEB formats)](../decisions/0010-older-gaeb-formats.md) |
| Printed bills read from a PDF's text layer by their column layout; Excel export of extracted tables and of runs | done | `backend/app/ingestion/pdf/`, `backend/app/exporters/xlsx_export.py`, [ADR 0011](../decisions/0011-pdf-bills-and-excel-export.md) |
| Scanned PDF pages read by Tesseract OCR | done | `backend/app/ingestion/pdf/ocr.py`, [ADR 0012](../decisions/0012-ocr-for-scanned-pdfs.md) |
| `statistical.peer_price`: unit prices far from comparable positions (opt-in, not in a baseline plan), and review lanes in the issue register | done | `backend/app/validation/statistical/peer_price.py`, `frontend/src/features/issues/ReviewLanes.jsx` |

Two decision records carry the number 0010 ([index](../decisions/README.md)).

## Risk grading (in `main`)

Built by a teammate and pushed to `main` on 2026-11-21 (commits `f40842e` to `1f7924c`); the
branch of pull request #10, `claude/project-thread-0s4qdy`, merged them, and this branch merged
that branch.

| Part | State | Where |
| --- | --- | --- |
| Risk reminders for a finished run, computed on request from the bill's text and its stored findings, graded and ordered (`GET /api/v1/validation-runs/{run_id}/risks`), and stored discovery runs in which a local model looks for problems no rule raised (`POST .../risks/discovery-runs`) | done; [ADR 0013](../decisions/0013-risk-grading.md) is proposed and waits for the owner's review | `backend/app/risk/`, `backend/app/api/routes/risks.py`, [REST API](../api/rest-api.md) |
| `qwen2.5:7b-instruct` (Apache-2.0) on the model allow-list, while its answers are still being evaluated ([open question 15](#open-questions)) | done | `backend/app/agents/models.py`, [deployment](../deployment.md) |

A reminder's `category` (for example `missing_scope` or `quantity`) groups risk types in the
risk catalogue; it is not one of the six finding categories below.

On this branch the risk report reads B2's findings and repeats nothing they find. The owner
chose "findings first, risk list second" on 2026-11-21: the issue register is the main list, and
the risk report is a second view of questions for the client. So the risk rules that checked the
same thing as a B2 check were removed or narrowed (D05, D30, A04 and V03 removed; D08, A01, V05
and V08 narrowed; [ADR 0013](../decisions/0013-risk-grading.md) has a status note with the
list), and `backend/app/risk/data/boq/findings.yaml` (version 0.3) lists B2's nine checks with
the risk types and client questions those rules had, so a B2 finding is one reminder that asks
the question, and the coverage table credits the check (for example R005 backfill, R088
disposal class, R118 GAEB hierarchy). B2 checks without a fitting risk type stay "Other risk".
Two details of the removed rules moved into `domain.boq_required_attributes`: a waste class the
text calls still open ("noch festzulegen") is no class, and Stahlbeton and Transportbeton with
a verb of placing in the Kurztext need a strength class ("Stahlbetonwand herstellen"). A01
also asked where the Kurztext names no placing ("Oberfläche Stahlbetondecke glätten"); the 14
such positions of the sample bills are 12 in m2, none in m3, and no long text of them names an
exposure class or a consistency, so by these keywords (not read one by one) they are work on
concrete, such as surfaces and joints, not placing it. A
Kurztext that opens with formwork, reinforcement, a coating, cutting or an opening is not
concrete work for that rule any more. On a probe bill with one position per overlap the report
went from 28 to 23 reminders (16 to 13 shown, 12 to 10 kept in the record), and no B2 finding
has a risk rule's reminder for the same condition on its position any more; on the planted-fault
test bill from 71 to 63 (46 to 40 shown, 25 to 23 in the record), with the issue register
unchanged (28 findings, 21 of 26 faults found). There, the one reminder of the removed D30
(03.02.0009, kept in the record) had read "Ver- und Entsorgungsleitungen" (utility lines) as
disposal; the register's waste-class rule excludes those words. The remaining 14 pairs of a B2
finding and a risk rule on the same position ask other questions (for example D04, excavation
for a foundation, next to the strength class). The rules that stay next to a B2 check ask
another question: D07 (a firestop in a fire-rated wall), D19 (a sleeve), V01 (who is
responsible), V02 (what is included) and V07 (which soil report). What the risk report no longer
asks is in the [known limitations](../known-limitations.md#detection). The change to the risk
package's code of the merge with pull request #10 stays: a reminder that joins several
candidates asks the question of the strongest one that asks something (`233264e`).

## Phase B: finding categories

Plan section 5a, approved by the owner on 2026-11-20 at 21:05 Berlin: every finding is sorted
into one of six categories, or into none when it is about reading the file. Built on the branch
`wp/b0-category`, reviewed by an independent reviewer who tried to break it, fixed, and merged
onto `claude/project-thread-0s4qdy` after `main` (up to `e720fa7`, the Fly.io preview gate and
the IFC coordination page, then up to `5439d02` and `1f7924c`, the teammates' work in the two
sections above). Pull request #10 merged that branch into `main` on 2026-11-21 (merge commit
`1283444`, with the same tree as the branch's head `100c1f3`).

| Part | State | Where |
| --- | --- | --- |
| The six categories (Error, Omission, Inconsistency, Ambiguity, Risk, Change order opportunity) and the table that assigns one to every check and to the rules that differ from their check; a test fails when a registered check has no entry | done | `backend/app/models/finding_category.py` |
| Each finding's category, computed from its check and rule (written into stored payloads but never read back, so a change to the table applies to stored findings too; neither the evidence class nor a review changes it, so a finding on a PDF bill that the evidence policy downgraded keeps its category) | done | `backend/app/models/issue.py`, [data model](../architecture/data-model.md) |
| A category filter and counts per category on the run's findings, in SQLite and PostgreSQL | done | `backend/app/repositories/`, `GET /api/v1/validation-runs/{run_id}/issues`, [REST API](../api/rest-api.md) |
| The category in `issues.csv` and in the `Issues` sheet of the Excel workbook (both after the severity), and in the JSON export | done | `backend/app/exporters/` |
| Planted and found errors per category in the BoQ benchmark, with the kinds whose expected check is not available in the run (not planned: not built yet or opt-in; or planned without the profile setting it needs) counted apart | done | `backend/app/evaluation/`, [report](../evaluation/boq-benchmark.md) |
| The category in the issue register (a column, a filter, the inspector) and the suggested action under the heading "Recommendation"; the older issue type is now called "Issue type", and the detector category in Settings "Check type" | done | `frontend/src/features/issues/`, `frontend/src/components/FindingCategory.jsx` |
| The category of each check in the detector catalogue; the owner's approval in ADR 0010 | done | [detector catalogue](../architecture/detector-catalogue.md), [ADR 0010](../decisions/0010-boq-anomaly-detection.md) |

Omission and Change order opportunity had no check then, and Risk only the opt-in peer-price
check from `main`; step B2 (below) added their first baseline checks, and B3 (similar positions)
adds more. The texts of the existing checks'
suggested actions are written for the bill's author ("correct the quantity"); plan 5a words
recommendations for the bidder's side, and the B2 checks follow it. Rewording the existing
texts is open.

## Phase B: step B2 (this branch)

Step B2 of plan sections 5a and 8: the checks that read a bill as a priced tender or bid. Built
in four parts on four branches, merged in pairs (parts A and B on `wp/b2-a`, parts C and D on
`wp/b2-c`), and integrated on this branch, `wp/b2-final`, from `717fba0` (the finding categories
in `main`): `wp/b2-a` merged first (`2ff58ef`), then `wp/b2-c` (`3347ad4`), each checked file by
file against both parents so that no change was lost. The six decisions of the integration
review followed, each as its own commit with its tests. The branch then merged pull request
#10's branch at `37ab12c` (merge commit `6a5a8fb`), so it holds `main` up to `5439d02` and the
category fixes as well. The review of that merge was fixed in five commits (`0625908` to
`cec8ae4`: the component check names the GAEB 90 record 30 lines that the import does not
read, the bid notes name both X84 and D84, the recall rows of the standard report say which
findings take a place, the API test names both opt-in checks, and the benchmark documents say
which expected checks are built). Then the branch merged pull request #10 at `104d0b9` (merge
commit `2a70812`), with the fixes of that pull request's final review, and then at its head
`100c1f3` (merge commit `c00fa57`), so it holds `main` up to `1f7924c` (the risk grading above)
as well
([Check it yourself](#check-it-yourself) has the checks on the merged tree). After the merge
with `main` at `fef7c13` (`0ff5268`, documents only), the risk rules that repeated B2's checks
were removed or narrowed, and B2's checks were listed in the risk report's table, as the owner
decided on 2026-11-21 ([risk grading](#risk-grading-in-main)). Then `main` at `b92f13d` (the
tender review, `5d5d311`, and Python 3.11 support), then at `ea41168` (Word documents and the
two price context checks) and at `70d17a6` (corrections and review, which change no check) were
merged, keeping one check per condition
([ADR 0013](../decisions/0013-tender-review-checks.md), status note): one typo check with B2's
matcher, misplaced items left to `deterministic.hierarchy` where it compares the numbers, the
clause check's wording left to it, and the risk wording rules V01 and V02 narrowed to what the
tender review does not read.

| Check | Reports | Category | Baseline plan |
| --- | --- | --- | --- |
| `domain.boq_clauses` | clauses that shift risk into the unit price, assumed conditions, deferred decisions, vague wording, open lump sums, references to other documents | Risk; assumed conditions and deferred decisions Change order opportunity; vague wording and document references Ambiguity | yes |
| `domain.boq_position_types` | a bill's contingency positions and hourly work, to price at rates that cover cost | Risk | yes |
| `domain.boq_bid_prices` | positions not offered, unit prices of 0,00 for a quantity (`zero_price`), token prices of 0,01 (`token_price`), hourly rates below the minimum wage | Error; the hourly-rate floor Risk | yes |
| `domain.boq_companion_work` | work without its companion work (seals, upkeep of site equipment, pressure tests, backfill) | Omission | yes |
| `domain.boq_required_attributes` | positions that omit a waste class (or call it still open), a concrete strength class (also of Stahlbeton and Transportbeton with a verb of placing, since 2026-11-21) or a pipe dimension | Ambiguity | yes |
| `domain.boq_typos` | rare spellings next to the word the bill uses often (since the merge with `main`, B2's matcher in `main`'s check of the same id, which also reports known misspellings and repeated words) | Error | yes, as a signal check (the benchmark plan leaves signals out) |
| `domain.boq_separate_payment` | work said to be paid separately without a position that pays it | Omission | no: only when a plan names it |
| `deterministic.hierarchy` | an OZ outside its Titel, a Titel under the wrong parent, an OZ out of order | Error | yes |
| `deterministic.unit_price_components` | unit price components that do not add up to the unit price | Error | yes |
| `deterministic.line_total` (changed) | says which value counts when a line total disagrees with quantity × unit price (the unit price prevails) and names the factor of a decimal slip | Error | yes |
| `deterministic.exact_duplicates` (changed) | also a position repeated under a new OZ within its Titel | Inconsistency | yes |

The `boq` profile also reads the GAEB position kinds of a Positionsart column in the totals,
position references with spaced segments, and the new value marker `not_offered` ("nicht
angeboten", "not offered"), which counts as zero in the totals. With B2 the workbench had 24
checks, 23 of them in the baseline plan of `boq`; since this branch merged pull request #10's
branch it also registers `main`'s opt-in `statistical.peer_price`: 25 checks, still 23 in the
baseline plan. Since the merge with `main` at `b92f13d` it also registers the tender review's
`domain.boq_numbering`, `domain.boq_description_clarity` and `domain.boq_contradictions` (its
`domain.boq_typos` is one check with B2's): 28 checks, 26 of them in the baseline plan. The
merge with `main` at `ea41168` added `main`'s two price context checks,
`statistical.historical_price` and `statistical.open_price_reference`, both in the BoQ baseline:
30 checks, 28 of them in the baseline plan. The merge with `main` at `daa3c81` added plan step
B3's five further opt-in signal checks and B4's problems: 35 checks, still 28 in the baseline
plan; it was pushed without a further test run, at the owner's request. `boq.yaml` is version 1.6.0 (B2's 1.5.0 and
`main`'s 1.5.0, which added the price date and tax basis fields). Those three checks had no finding category; they have one now
(`main` proposed its own in the meantime: numbering an Omission, unclear descriptions and
contradictions within an item an Ambiguity; the merge keeps those and adds two rule entries as
B2 categorises the same kinds: a decision left to the client a Change order opportunity, a
misplaced item an Error), to be confirmed by the owner.

The decisions applied after the merges:

1. Every B2 check and the rules that differ from their check have a finding category (above);
   `deterministic.hierarchy` is Error, as plan 5a lists it.
2. One bid price check: `domain.boq_bid_prices` covers plan 8's price completeness instead of a
   second check `deterministic.price_completeness`. A position not offered is a confirmed rule
   violation, high, and medium when the position is declared outside the sum; in a GAEB bid read
   without its tender, the finding says that the tender states whether the position counts. A
   unit price of 0,00 for a quantity and a token price are reported apart, both "check this",
   medium, also on positions outside the sum (an alternative must be priced too). Positions not
   offered stay exempt from `required_values`, so one defect gives one finding (ADR 0010).
3. Both benchmarks score the list of contingency positions against the generated bill: a list
   that names only contingency or hourly positions of the generated bill is a correct risk
   note, counted on its own line; a list that names any other row would be a false positive.
4. English bills get the list for positions whose item type is coded "contingency", which the
   profile's totals rules already read; English wording in the text is not matched (open).
5. `boq.yaml` is version 1.4.0.
6. The standard benchmark's generator writes two German item texts in full ("Baugrube ausheben
   und verfüllen", and the waste class after "Boden laden, abfahren und entsorgen"), so clean
   bills satisfy the companion-work and waste-class rules
   ([report](../evaluation/synthetic-benchmark.md)).

The planted-fault test bill (hackathon data, scored through the app with the `boq` profile and
the baseline plan; found means a finding names any row of the fault, localized means it names
the fault's row):

| Category | Planted | Found before (`717fba0`) | Found after (this branch) | Localized after |
| --- | --- | --- | --- | --- |
| Error | 7 | 5 | 7 (`pf-05` only incidentally) | 7 (`pf-05` only incidentally) |
| Inconsistency | 5 | 1 | 1 | 1 |
| Omission | 3 | 0 | 2 | 1 |
| Ambiguity | 4 | 0 | 4 | 4 |
| Risk | 4 | 0 | 4 | 4 |
| Change order opportunity | 3 | 0 | 3 | 3 |
| All | 26 | 6 | 21 (19 by the fault itself) | 20 (19 by the fault itself) |

Before: 12 findings from 15 check reports; after: 28 findings from 23. The typo check's
thresholds were chosen on this bill (ADR 0010, B2 item 6): with plan 5a's setting (10 letters, 4
uses, no transpositions) it misses `pf-11`, and the bill gives 20 found and 19 localized.
Missed: `pf-13`, `pf-15`, `pf-18` and `pf-19` (inconsistencies between similar positions, for
B3) and `pf-16` (found only by the optional `domain.boq_separate_payment`). `pf-26` is found
only incidentally, by a rare spelling on one of its rows, not on its own row. `pf-05` (a decimal
slip in a quantity) is found and localized only incidentally too: the one finding that names its
row is `unknown_unit` on 'm2d', a unit the answer key says is right (`ok-06`); the slip itself
is not detected (before as well). Two found faults carry another category in the app than in the
answer key: `pf-07` (key Error, found by `exact_duplicates` as an Inconsistency) and `pf-23`
(key Risk, found by `token_price` as an Error). The `must_not_flag` items: before, `ok-03` (a
required value on a row with a planted fault) and `ok-06` (units the unit checks do not know)
were hit. After, `ok-01` to `ok-06` are hit and `ok-07` to `ok-09` are not: `ok-01` by the
contingency list; `ok-02` by the position reference, hourly-rate floor and contingency list
findings, all on rows with a planted fault; `ok-03` as before and by a vague wording finding;
`ok-04` by an assumed condition on a row with a planted fault; `ok-05` by a document reference;
`ok-06` as before. The rules' hits on the sample bills and the two Nachtrag confirmations,
measured on `wp/b2-a` before parts C and D:
[b2-rule-measurement.md](../evaluation/b2-rule-measurement.md).

The checks of this branch: [Check it yourself](#check-it-yourself), the last table. Open:
English contingency wording in the text; the five missed faults; the wording checks read the
positions with their own reader (`domain/boq/_bill_text.py`), the price checks with the item
frame (`support/items.py`): two readers of the same rows, to be joined; the B2 thresholds were
set on the bills they were measured on (in-sample); the minimum-wage floor in `boq.yaml`
(`hourly_wage_floor` and `floor_source` of `domain.boq_bid_prices`) has to be updated each
January; three rules of plan 5a are not built (ADR 0010, B2 item 5): unit prices below a floor
per unit set in the profile (Risk, in a bid: no source for the floors yet, so the owner has to
name the units and values; the bid AN24-0305 has 44 unit prices below 1 EUR that no check
reports), blank bidder entries (Risk, in a bid: the GAEB import does not read text complements
or bidder entries, and plan 5a leaves the check out of this change for that reason), and a
Titel without positions (Omission: a rule for `deterministic.hierarchy`, to be measured first on
the sample bills, whose Vorbemerkungen Titel hold text only); the six decisions above wait for the owner's confirmation.

## Check it yourself

Commands: [README](../../README.md#test). Measured on 2026-11-20 on the merged branch of A2
(`claude/project-thread-0s4qdy`, after both parts and the fixes of both reviews were merged):

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` (backend) | no problems, 259 files formatted |
| `.venv/bin/python -m mypy` (backend, strict) | no issues in 151 source files |
| `.venv/bin/python -m pytest -q -m "not performance" --cov --cov-fail-under=94.5` (backend) | 2055 passed, 2 deselected, 1 warning, 64 s; coverage 95.30 % |
| `.venv/bin/python -m pytest -q -m performance` (backend, the two time-limit tests, without coverage) | 2 passed |
| PostgreSQL selection (`-k postgresql`), C and ICU en-US collation | 133 passed on each |
| `npx vitest run` (interface) | 110 passed (22 files) |
| `npm run build` | builds |
| `npm run test:e2e` (browser) | 2 passed: the main workflow, and the hit areas with fine and coarse pointers |
| `.venv/bin/python -m app.evaluation` (synthetic benchmark) | the documented numbers, see Results |

The warning comes from a third-party package (Starlette's test client deprecates `httpx`). One
interface test (`SignIn.test.jsx`, which expects the token field to have focus as soon as the
dialog appears) failed once while the backend suite ran on the same machine, and passed in
every run since, also under artificial CPU load. During the contract review, one full `vitest`
run had one failed test that was not recorded; the eight runs after it, and the run above,
passed.

Measured on 2026-11-20 on A2 and the GAEB import together (local branch `wp/pb-base`, whose
code `claude/project-thread-0s4qdy` has unchanged; the later `main` commits add only the sample
bills and the challenge brief, which no check reads):

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` (backend) | no problems, 272 files formatted |
| `.venv/bin/python -m mypy` (backend, strict) | no issues in 159 source files |
| `.venv/bin/python -m pytest -q -m "not performance" --cov --cov-fail-under=94.5` (backend) | 2087 passed, 3 skipped, 2 deselected, 1 warning, 72 s; coverage 94.87 % |
| `.venv/bin/python -m pytest -q -m performance` (backend, the two time-limit tests, without coverage) | 2 passed |
| PostgreSQL selection (`-k postgresql`), C and ICU en-US collation | 134 passed on each |
| `npx vitest run` (interface) | 112 passed (23 files) |
| `npm run build` | builds |
| `npm run test:e2e` (browser) | 2 passed: the main workflow, and the hit areas with fine and coarse pointers |
| `.venv/bin/python -m app.evaluation` (synthetic benchmark) | the documented numbers (141 injected errors, 193 findings, no false positive); only the timing lines differ |

The three skipped tests read the official BVBS GAEB test files, which are not committed; they
run when `TWB_GAEB_SAMPLES` names their folder ([ADR 0009](../decisions/0009-gaeb-import.md)).
The warning is the same third-party one as above.

Measured on 2026-11-20 on the branch `wp/b01-main` (B0 and B1 on A2 and the GAEB import, with
the nine decisions above), in a `backend/.venv` created fresh and installed from the lock file,
with no `TWB_*` setting of the shell reaching the tests (`env -u TWB_AUTH__TOKENS -u
TWB_DATABASE_URL -u TWB_TEST_DATABASE_URL`):

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` (backend) | no problems, 306 files formatted |
| `.venv/bin/python -m mypy` (backend, strict) | no issues in 173 source files |
| `.venv/bin/python -m pytest -q -m "not performance" --cov --cov-report=term --cov-fail-under=94.5` (backend) | 2485 passed, 3 skipped, 2 deselected, 1 warning, 120 s; coverage 95.20 % |
| `.venv/bin/python -m pytest -q -m performance` (backend, the two time-limit tests, without coverage) | 2 passed |
| PostgreSQL 16 selection (`TWB_TEST_REQUIRE_POSTGRESQL=1`, `-k postgresql tests/unit/repositories tests/integration`), a new database with C collation and one with ICU en-US | 144 passed on each |
| `npx vitest run` (interface, after `npm ci`) | 113 passed (24 files) |
| `npm run build` | builds |
| `npm run test:e2e` (browser) | 2 passed: the main workflow, and the hit areas with fine and coarse pointers |
| `.venv/bin/python -m app.evaluation` (synthetic benchmark) | the documented numbers (100 bills, 7,507 rows, 141 injected errors, 193 findings, no false positive, the same table by kind); only the timing lines differ |
| `.venv/bin/python -m app.evaluation --variant boq --seed 20261120 --documents 100` | 234 planted errors, 133 rule findings, none on an unplanted row ([report](../evaluation/boq-benchmark.md)) |

The first `vitest` run on this branch, right after `npm ci` with an empty cache, failed the
sign-in test that expects the token field to have focus as soon as the dialog appears (the
test noted above); run alone it passed, and one of six more full runs with an emptied cache
failed it again. The cause was in the dialog: it set the focus in an effect that React runs
after the commit, so for a moment the dialog was shown with nothing focused. It now sets the
focus in the commit itself (`useLayoutEffect`). A new test looks at exactly that moment; it
failed three times out of three before the fix. Eight full runs with an emptied cache passed
after it. The skipped tests and the warning are the ones above.

Measured on 2026-11-21 on the branch `claude/project-thread-0s4qdy`, pull request #10, at
`50ed7c3`: the finding categories with the fixes of both reviews, merged after `main` up to
`1f7924c` (risk grading). The commits after it, up to the pull request's head `100c1f3`, change
only documentation (the known limitations, `NEXT_STEPS.md` and this page). No `TWB_*` setting of the shell
reached the tests:

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` (backend) | no problems, 354 files formatted |
| `.venv/bin/python -m mypy` (backend, strict) | no issues in 206 source files |
| `.venv/bin/python -m pytest -q -m "not performance" --cov --cov-report=term --cov-fail-under=94.5` (backend) | 2810 passed, 7 skipped, 2 deselected, 1 warning, 199 s; coverage 94.78 % |
| `.venv/bin/python -m pytest -q -m performance` (backend) | 2 passed |
| PostgreSQL 16 selection (`-k postgresql tests/unit/repositories tests/integration`) | 155 passed |
| `npx vitest run` (interface) | 142 passed (29 files) |
| `npm run build` (after `git lfs pull`: the IFC demo models in `main` are Git LFS files) | builds; Vite warns that one chunk is larger than 500 kB (the IFC demo page) |
| `npm run test:e2e` (browser) | 3 passed: the main workflow, the hit areas with fine and coarse pointers, and the issue table at 28 layouts without sideways scrolling |
| `.venv/bin/python -m app.evaluation` (synthetic benchmark) | the numbers of pull request #10's report at `100c1f3` (100 bills, 7,507 rows, 141 injected errors, 193 findings, every one found); only the timing lines differ, and the two rows `main` added to the report (recall in the first 20 and 50 findings) are 1.000 |
| `.venv/bin/python -m app.evaluation --variant boq --seed 20261120 --documents 100` | 234 planted errors, 133 rule findings, none on an unplanted row, and the same table by category: every number of pull request #10's report at `100c1f3` except the timing lines; this branch's [report](../evaluation/boq-benchmark.md) adds step B2's numbers (270 rule findings for 133, 58 correct risk notes, 0.944 findings per planted error for 0.577, the four kinds that waited for B2 measured) |

The 7 skipped tests need the official BVBS GAEB samples (3, `TWB_GAEB_SAMPLES`) or Tesseract
with German and English data (4, the OCR tests from `main`). Coverage is lower than before the
merge (95.24 %) because the OCR code from `main` runs only where Tesseract is installed.

Measured on 2026-11-21 on this branch, `wp/b2-final` (step B2 on `717fba0`), after the fixes of
the review (`71e472a`; the later commits change only documents) and before the merge of pull
request #10's branch, in the backend with
`env -u TWB_AUTH__TOKENS -u TWB_DATABASE_URL -u TWB_TEST_DATABASE_URL`:

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` (backend) | no problems, 337 files formatted |
| `.venv/bin/python -m mypy` (backend, strict) | no issues in 188 source files |
| `.venv/bin/python -m pytest -q -p no:cacheprovider -m "not performance" --cov --cov-report=term --cov-fail-under=94.5` (backend) | 3082 passed, 3 skipped, 2 deselected, 1 warning, 160 s; coverage 95.72 % |
| `.venv/bin/python -m pytest -q -m performance` (backend) | 2 passed |
| PostgreSQL 16 selection (`TWB_TEST_REQUIRE_POSTGRESQL=1`, `-k postgresql tests/unit/repositories tests/integration`), a new database with C collation | 155 passed |
| `npx vitest run` (interface) | 132 passed (27 files) |
| `npm run build` | builds; Vite warns that one chunk is larger than 500 kB |
| `npm run test:e2e -- --trace off` (browser) | 3 passed |
| `.venv/bin/python -m app.evaluation` (synthetic benchmark) | 240 findings: every injected error found, no false positive, 47 correct risk notes ([report](../evaluation/synthetic-benchmark.md)) |
| `.venv/bin/python -m app.evaluation --variant boq --seed 20261120 --documents 100` | 270 rule findings: 212 on planted rows, 58 correct risk notes, none a false positive; recall 1.000 for every kind with a check ([report](../evaluation/boq-benchmark.md)) |
| The planted-fault test bill, scored through the app | 21 of 26 faults found, 20 localized (19 and 19 by the fault itself; 6 before B2); 20 and 19 with plan 5a's typo setting |

The 3 skipped tests need the BVBS samples; the warning is the one above.

Measured on 2026-11-21 on this branch, `wp/b2-final`, at `233264e`: pull request #10's head
`100c1f3` merged in (merge commit `c00fa57`, with `main` up to `1f7924c`), then the change to
the risk package described above; the commits after it change only documents. The same
environment settings, and `pypdfium2` installed from the lock file. The earlier runs, at
`2a70812` after the merge of `104d0b9` and at `6a5a8fb` after the merge of `37ab12c`, had the
same results except where a row says otherwise:

| Check | Result |
| --- | --- |
| `ruff check .`, `ruff format --check .` (backend) | no problems, 382 files formatted (353 at `2a70812`) |
| `.venv/bin/python -m mypy` (backend, strict) | no issues in 219 source files (196 at `2a70812`) |
| `.venv/bin/python -m pytest -q -p no:cacheprovider -m "not performance" --cov --cov-report=term --cov-fail-under=94.5` (backend) | 3350 passed, 7 skipped, 2 deselected, 1 warning, 259 s; coverage 95.16 % (at `2a70812`: 3194 passed, 244 s, 95.23 %; the 156 new tests are `main`'s 155 risk grading tests and its test of the rows a total leaves out (`test_rows_not_counted_are_named_as_cells`, from `1f7924c`, which pull request #10's branch merged in `50ed7c3`); `main` also replaced `test_it_is_empty_in_this_version_and_read_only` with `test_it_lists_the_checked_model_and_is_read_only`; at `6a5a8fb`: 3190 passed) |
| `.venv/bin/python -m pytest -q -m performance` (backend) | 2 passed |
| PostgreSQL 16 selection (`TWB_TEST_REQUIRE_POSTGRESQL=1`, `-k postgresql tests/unit/repositories tests/integration`), a new database with C collation | 155 passed |
| `npx vitest run` (interface) | 142 passed (29 files; 140 in 28 at `2a70812`: `main`'s `risksService.test.js` adds two) |
| `npm run build` (after `git lfs pull`) | builds; Vite warns that one chunk is larger than 500 kB |
| `npm run test:e2e` (browser) | 3 passed |
| `.venv/bin/python -m app.evaluation` (synthetic benchmark) | 240 findings: every injected error found, no false positive, 47 correct risk notes; recall in the first 20 and 50 findings 1.000; against the committed report only the timing lines differ (0.087 s median per document, 742 rows per second, measured while the interface tests ran), so it is not regenerated ([report](../evaluation/synthetic-benchmark.md)) |
| `.venv/bin/python -m app.evaluation --variant boq --seed 20261120 --documents 100` | the same numbers as before: 270 rule findings, 212 on planted rows, 58 correct risk notes, none a false positive; against the committed report only the timing lines differ (0.625 s median per bill, 679 rows per second), so it is not regenerated ([report](../evaluation/boq-benchmark.md)) |
| `.venv/bin/python -m app.validation.catalogue_markdown` | equal to `docs/architecture/detector-catalogue.md` |
| The planted-fault test bill, scored through the app | the same result as before: 21 of 26 faults found, 20 localized; the scorer's output is byte for byte that of the run at `2a70812` |
| The sample bills of `Sample BoQ Dataset/` (not its folder of planted faults), uploaded with the `boq` profile and run with the baseline plan on a SQLite database | measured at `2a70812` and not run again, because this merge changes nothing in how files are read (it adds the risk report, which reads stored runs, and names the rows a total leaves out as cells): 43 of 44 files read: 34 PDFs (3,257 rows), 4 X83, 1 D83, 2 D84 and 2 D86; the Word file is refused (`unsupported_format`). Every run completed with its 23 planned checks and none failed, also every check of B2 on the PDFs. 240 findings, 127 of them on the PDFs (Error 24, Inconsistency 11, Omission 3, Ambiguity 38, Risk 35, Change order opportunity 5, Reading the file 11; 38 of them `extraction_uncertainty`). One change: on the D86 with record 30 lines, `deterministic.unit_price_components` now runs and notes the 159 record 30 lines (unit price components) that the import does not read (it skipped before); it reports no finding there, so the counts are the same |

The 7 skipped tests are the ones of pull request #10's measurement above (BVBS samples and
Tesseract, which this machine does not have). Of the B2 checks on the PDFs, three skip where
they do not apply: `deterministic.unit_price_components` on all 34 (no table maps a unit price
component), `domain.boq_bid_prices` on the 32 that price no item (tenders), and
`deterministic.hierarchy` on the 3 without a section that has a code. On the GAEB files,
`deterministic.unit_price_components` skips where no table maps a component (4 X83, 1 D83, 2
D84 and 1 D86) and `domain.boq_bid_prices` on the 5 tenders (X83 and D83).
Three tests from `main` expected a clean self-made bill (GAEB 90 and PDF) to validate without
findings; since B2 such a bill gets the list of its one contingency position, a Risk note, and
the tests now say so.

## Results

- **Synthetic benchmark** (seed 20261119; 100 generated bills, 7,507 rows, 141 injected
  errors): 240 findings: every injected error found (193 findings), no false positive, and 47
  correct risk notes, each a German bill's list of its contingency positions, checked against
  the generated bill. One net-total slip in a CSV is reported as possible display rounding, by
  design. Synthetic benchmark: measured on generated data, not real-world performance. Details:
  [synthetic-benchmark.md](../evaluation/synthetic-benchmark.md).
- **BoQ benchmark** (seed 20261120; 100 generated bills, 52,934 rows, 234 planted errors of 24
  kinds): the 124 errors of the 13 kinds that today's checks cover are all found, each with the
  wrong cell highlighted (B2 added `placeholder_price`, `code_outside_section`,
  `component_sum_error` and `duplicate_position`). The 11 kinds that wait for the checks of B3
  show "check not available yet"; other checks already flag 48 of their 110 errors. 270 rule
  findings: 212 on planted rows and 58 correct risk notes, none a false positive; no signal,
  because the benchmark plans only the baseline checks and the one signal check,
  `statistical.peer_price`, is opt-in (`--plan-step statistical.peer_price` adds it).
  Synthetic benchmark: measured on generated data, not real-world performance.
  Details: [boq-benchmark.md](../evaluation/boq-benchmark.md).
- **Speed**, measured once during Phase 1 (2026-11-19) on one laptop with SQLite, for a CSV of
  20,000 rows, and not measured again since: upload about 10–11 s; a validation run about 3 s;
  the document list with 10 such bills 0.03 s; opening one such document about 5 s.

## Workspace redesign (issue #14)

Everything about one file is on one page, `/workspace`, for the Korrektor who checks the file.
The separate Documents, Issue register, Validation runs and Exports pages are gone; their old
links redirect to the workspace.

| Part | State | Where |
| --- | --- | --- |
| Navigation in a sidebar on the left: Workspace, History, Coordination Lab, Settings (a rail of icons below 1024 px) | done | `frontend/src/app/Sidebar.jsx` |
| Start: upload box and the 8 newest files uploaded before, with a search by file name; every upload is read as a bill of quantities (profile `boq`), so there is no "Read as" choice | done | `frontend/src/features/workspace/StartPanel.jsx` |
| History: every file uploaded before, newest first, in pages of 50, with the same search (in the browser, over the 500 newest files, since the API has no name search) | done | `frontend/src/features/history/` |
| The file as an editable sheet; an edit is saved as revision N+1 (`POST /datasets/{id}/corrections`, ADR 0001) | done | `frontend/src/features/workspace/sheet/`, `backend/app/normalization/revise.py` |
| "Validate the table" and "Choose checks" at the sheet's top right | done | `frontend/src/features/workspace/DocumentView.jsx` |
| Tabs: Properties (GAEB facts first), Requirements (which method checked what: rule, statistics, language model), Issues (open count in red), Export | done | `frontend/src/features/workspace/tabs/` |
| Issue cells washed light red; an issue opens its cell with a note and a Review button | done | `frontend/src/features/workspace/sheet/` |
| Side window: 3D model (demo model for the files in a hand-written link table), the issue, Approve / Reject / Needs clarification, then "Fix the value" (the correction route of `main`) | done | `frontend/src/features/workspace/context/` |
| "Finish review" of a run, under the Issues tab | done | `frontend/src/features/validation/RunReviewControls.jsx` |

Plan and decisions: `PLAN.md` of the redesign in the project files.

### Side panel (replaces the tabs under the sheet and the issue window)

The page no longer scrolls as a whole: the sheet column and each panel tab scroll on their own.
The panel sits beside the sheet from 1280 px (below it on narrower screens), starts at 44 % of
the width and is resized with the divider (pointer or arrow keys; double-click resets it).

| Part | Where |
| --- | --- |
| Fixed bar at the top with the file's name (and the revision after an edit); the facts of the file are in Properties | `frontend/src/features/workspace/DocumentBar.jsx` |
| Tabs: Properties, Risks (open risks counted in red, after a validation), 3D model. Risks opens by itself after a validation and when a risk is chosen; old links (`insights`, `pricing`, `issues`, `export`, `requirements`) are redirected | `frontend/src/features/workspace/DocumentView.jsx`, `panel/` |
| Properties: the file, its GAEB facts, the tables, and how the bill was checked | `tabs/PropertiesTab.jsx`, `panel/CheckingSummary.jsx` |
| Risks list: priority badge (solid red for critical, white for low), short title naming the kind, status (Open, In review, Approved, Rejected), classification (the six finding categories); search, status chips, Priority, Classification, Type, Section and Money filters, sort; questions for the client (closed), the run's problems, the review of the run and the downloads under the list | `panel/RisksTab.jsx`, `panel/RiskRow.jsx`, `panel/RiskBits.jsx`, `features/risks/riskFilters.js` |
| Risk detail: what's wrong, what to do (with the question for the client), the price of the position (open for a price risk, else closed), where, then details and evidence behind a disclosure; Approve, Reject and Needs clarification pinned at the bottom, keys J/K/A/R/C/Esc | `panel/RiskDetail.jsx`, `panel/RiskDecisionBar.jsx`, `panel/PriceSection.jsx` |
| Decisions: a risk with findings is decided on every finding; a risk without one (a question to the client) through `PUT /validation-runs/{run_id}/risk-reviews/{risk_id}`, kept as an audit event. Approve opens the risk's cell for editing in the sheet | `backend/app/services/risk_reviews.py`, `features/risks/useRiskReviews.js` |
| On the wide layout a flagged cell opens its risk in the panel and the sheet shows no note; the narrow layout keeps the note | `sheet/Sheet.jsx` (`showNotes`, `onCellFindings`) |
| Under the table after a validation: next best action, four figures (line items, risks, open, bill total and its change against the earlier revision), next priorities | `overview/` |

Saving a new price through the review route needs an approved finding on the same revision
(the backend allows `corrected` only after `confirmed_error`); otherwise the cell edit route
saves it. Tasks (the task manager of the reference app) follow in a separate pull request.

### PDF view of the sheet

A Table / PDF switch on the right of the cell bar shows the printed bill in the same box as the
table (same height, the footer pages through the PDF), with the active cell highlighted: the
position lightly (from its number to the next line at the same left edge), the cell's value
strongly (the same number, unit or text lines). When the value is not printed (an empty price
in a blank bill) only the position is marked, and the footer says so. An uploaded PDF shows
itself; for a GAEB file the print is declared by hand in `sheet/pdfLinks.js`. The table was
checked against the sample data by finding every row's position number in the PDF:

| Bill | PDF | Positions found |
| --- | --- | --- |
| 8209.003_Leistungsverzeichnis_leer.X83 / .D83 | HEM2301-2_Gesamt-LV.pdf | 187 of 187 |
| [ORT_024] LV24069.D86 | HEM2301-2_Gesamt-LV.pdf | 188 of 232 (section 08 is not in the print) |
| StBALV23040.D86 / .D84 | Abgabe LV.pdf | 280 of 283 (TEL00009 and 10.01 are not printed) |
| [NUMMER_001]_leer.X83 | Leistungsverzeichnis_leer.pdf | 280 of 280 |
| GAEB-[PROJEKT_004].X83 | LV-Ausdruck-[PROJEKT_004].pdf | 54 of 54 |
| Angebot AN24-0305.D84 | Angebot AN24-0305.pdf | 274 of 295 (the section headings are printed differently) |

Code: `sheet/SheetPdf.jsx`, `sheet/pdfLocate.js`, `sheet/pdfLinks.js`; the PDFs are copied by
`scripts/prepare-coordination-sources.mjs`. Browser test: `e2e/sheet-pdf.spec.js`.

## Web interface

Accessibility, as checked so far: text contrast (WCAG AA, measured on the rendered page), a
name on every control, hit areas (measured in the browser test), a visible focus ring, reduced
motion, and keyboard use (skip link, tabs with arrow keys, table rows with arrow keys and
Enter, Escape closes panels; focus moves to the section heading or the replacing control when
the clicked control goes away). Links inside running text stay inline. Not covered: no screen
reader was used; no automated accessibility scanner runs in the tests (it would be a new
dependency); in the issue table every row is a Tab stop, so Tab passes through up to 50 rows.

## Users, roles, the top bar and the language switch

Built on `main` after `f487247`, not committed yet.

| Part | State | Where |
| --- | --- | --- |
| User accounts (name, email, role, active) with personal access tokens; only the token's digest is stored, the token is shown once. Schema version 7 | done | `backend/app/models/user.py`, `backend/app/services/users.py`, `backend/app/repositories/sql/users.py`, [ADR 0015](../decisions/0015-users-and-roles.md) |
| Roles enforced for every route: viewer reads, reviewer also writes, admin also manages users (`403 forbidden`); `GET /me`, `/users` | done | `backend/app/api/auth.py`, `backend/app/api/routes/users.py`, [REST API](../api/rest-api.md#security) |
| The audit trail names the user who acted (and background runs the user who started them) | done | `backend/app/services/identity.py`, `backend/app/services/workbench.py` |
| Top bar: the section and what it is for, "Read only" for viewers, and the avatar with name and role; its menu has Profile and Log out | done | `frontend/src/app/TopBar.jsx`, `frontend/src/features/profile/` |
| Settings at the bottom of the sidebar | done | `frontend/src/app/Sidebar.jsx` |
| Settings, General: language (English or German, kept per browser). My profile: first and last name, email, job title, phone (editable, `PATCH /me`), role, status, member since, token; sign in with a personal token. Users: add, change role, deactivate, issue a new token, delete | done | `frontend/src/features/settings/` |
| German interface texts: navigation, top bar, profile, Settings (General and Users), sign-in, page titles; the pages' content is still English | in part | `frontend/src/i18n/` |

Checked with the backend suite (new: `tests/unit/api/test_users.py`, every adapter in
`tests/unit/repositories/test_users.py`, the migration to version 7) and the frontend suite
(new: `src/app/TopBar.test.jsx`, `src/features/settings/UsersPanel.test.jsx`).

## If you ran the app before

A database written by an older build is upgraded: SQLite files automatically at start-up, after
a backup copy; PostgreSQL with `python -m app.cli db upgrade`
([deployment](../deployment.md#migrations)). Custom profiles written before round 1 must list
`boolean_words`, and a custom profile that sets `severity` for the duplicate check must call it
`severity_exact_duplicate` ([upgrade notes](../deployment.md#upgrade-notes)).

## More bill formats, PDF and OCR, the tender review, and Word documents

Built on `main` after pull request #6, in the commits `c2e2ee2` and `abfa4b5` (formats, PDF,
OCR), `5d5d311` (the tender review and the findings on the workspace) and `c83208b`
(Word documents).

| Part | State | Where |
| --- | --- | --- |
| GAEB DA XML 3.1 and 3.2, phase X86, GAEB 90 (D81 to D86) | done | `backend/app/ingestion/gaeb/`, [ADR 0010 (older formats)](../decisions/0010-older-gaeb-formats.md) |
| Printed bills from a PDF's text layer; Excel export of extracted tables and of runs | done | `backend/app/ingestion/pdf/`, `backend/app/exporters/xlsx_export.py`, [ADR 0011](../decisions/0011-pdf-bills-and-excel-export.md) |
| OCR of scanned PDF pages (Tesseract, in the Docker image) | done | `backend/app/ingestion/pdf/ocr.py`, [ADR 0012](../decisions/0012-ocr-for-scanned-pdfs.md) |
| Tender review: missing items, unclear descriptions, contradictions, typing slips (four signal checks in the BoQ baseline since profile 1.4.0) | done | `backend/app/validation/domain/boq/`, [ADR 0013](../decisions/0013-tender-review-checks.md) |
| Findings on the workspace: the latest run's findings listed by check below the summary, and their rows and cells marked in the table preview | done | `frontend/src/features/issues/RunFindings.jsx`, `frontend/src/features/workspace/` |
| Word documents (.docx): tables, and bills written as item paragraphs | done | `backend/app/ingestion/docx/`, [ADR 0014](../decisions/0014-word-documents.md) |
| Coordination Lab fixtures across the BoQ trades. The 50 sample files are grouped into six projects on checked evidence. The 79-222 model gains structural, envelope, interior and services checks: column schedule, gates, screed and roof outlets, two of them with injected changes. Every bill row is linked to its elements by declaration and checked against the extraction. Generation is byte-reproducible and enforced in CI; the original scenarios are preserved | done, not committed | `tools/ifc_demo/` ([README](../../tools/ifc_demo/README.md)), `backend/tests/integration/test_ifc_fixtures.py` |

The tender review ran on all 43 bills in `Sample BoQ Dataset/` and found 280 findings (none in 3
bills, a median of 3, at most 45 in one bill). The Word reader reads the sample
`LV-Positionen.docx` whole: 40 items with their units in 10 groups, the `…`, `oder` and `mit`
lines as notes. Checks on 2026-11-21, after the Word documents, on `main` with `4c2b4eb` merged:

| Check | Result |
| --- | --- |
| `ruff check app tests`, `ruff format --check`, strict `mypy` (backend) | no problems (215 source files) |
| `pytest -q` (backend) on Linux (Python 3.13, Tesseract 5.5.0, the locked requirements) | 2870 passed, 3 skipped |
| `pytest -q` (backend) on Windows | 2 failures, both Windows only and both present without these changes: the gate test (`test_interface.py`), and `test_risk_api.py::test_two_starts_at_once_run_the_model_once`, whose discovery store renames a file over one another thread has open (`PermissionError`, WinError 5) |
| the Word tests (`tests/unit/ingestion/test_docx.py`, `tests/integration/test_docx_api.py`) | 24 passed |
| `npx vitest run` (interface, Node 22) and `npx vite build` | 155 passed in two of three runs; `ifc-demo/ExtractedCoordination.test.jsx` fails in the others, also on `4c2b4eb` without these changes (it waits 1 s for the coordination page); builds |

## Open questions

1. **Spreadsheet grid** (brief Part J): sorting, filtering, search, column resizing and cell
   selection are not built yet; cells with findings are highlighted since 2026-11-21.
2. **Dataset cache** (Phase 1 audit): the cache keeps 8 decoded datasets whatever their size
   (`TWB_PERSISTENCE__DATASET_CACHE_ENTRIES`); one decoded 20,000-row dataset took about 0.5 GB
   in one measurement. Whether to lower the default depends on real bill sizes and usage.
3. **Stored file without a document** (Phase 1 audit, found by reading the code, not
   reproduced, not re-checked since): if the database write fails after an upload's file was
   stored, the file stays in the file store. It costs disk space only.

The two A2 reviews left these questions for the owner, each with the reviewer's options:

4. **API documentation pages** (security review): `/docs`, `/redoc` and `/openapi.json` stay
   open when sign-in is required. The documentation pages load their scripts from
   cdn.jsdelivr.net (floating major versions) on the workbench's own origin, so such a script
   could read the access token that the interface keeps in `sessionStorage` in the same tab;
   offline, the pages fail. Options: turn them off in production, serve the assets locally, or
   put `/openapi.json` behind sign-in.
5. **Health without a token** (security review): `GET /api/v1/health` tells a caller without a
   token the version, the detector count, the profiles and the unavailable detectors; a monitor
   and the sign-in decision need less. Trimming it changes the health contract.
6. **Token strength and throttling** (security review): a one-character token is accepted at
   start, and wrong tokens get an immediate `401` without a slowdown or lockout. Option: refuse
   tokens shorter than about 32 characters at start.
7. **Data folder permissions** (security review): under the default umask the database and its
   WAL files are readable by other local users of the host (0644, folders 0755). Options:
   create the data folder 0700 and the database 0600, or document running with `umask 077`.
8. **Synchronous runs** (security review, found by reading the code): a run without
   `Prefer: respond-async` is not bounded by the background-run limits and holds one worker
   thread for up to `max_run_seconds`. Option: cap concurrent synchronous runs and refuse
   extra ones with `503`, like `run_queue_full`.
9. **Detector failures in text logs** (security review, not reproduced): a failed detector is
   logged with its exception message, which may contain document content, and the text log
   format does not escape control characters. Options: log the exception type and frames
   without the message, or escape the text format.
10. **Checks a profile disables** (contract review, K8): the catalogue does not say that a
    profile disables a check, so with an operator profile that disables one, the run panel
    preselects it and a changed plan is refused with `detector_disabled`. The built-in
    profiles disable nothing. A fix needs a new API field and an interface change.
11. **Plan step limit** (contract review): `TWB_VALIDATION__MAX_PLAN_STEPS` accepts values
    above 256, but a plan holds at most 256 steps, so such values never take effect. Options:
    bound the setting at 256, or take the plan's cap from the setting.
12. **Issue order index** (contract review, performance only): on PostgreSQL the issue page
    cannot be read in its order from `ix_issues_run_order` (mixed directions, `NULLS FIRST`,
    `COLLATE "C"`), so it sorts; results are correct on every backend. A matching index needs
    schema version 5.
13. **Retry-After for other origins** (contract review): CORS does not expose `Retry-After`,
    so a browser client on another allowed origin cannot read it on `503 run_queue_full`. The
    shipped interface is same-origin and does not need it.

Bringing Phase B together with the GAEB import left this one:

14. **GNU libiconv inside lxml** (licence): the lxml 6.1.3 binary wheels, which the GAEB import
    parses and validates with, link GNU libiconv 1.18 statically, under LGPL 2.1 as lxml's own
    licence file states, besides zlib, libxml2, libxslt and libexslt (permissive). The project's
    rule excludes LGPL. The library has no file of its own, so the bundled-library scan cannot
    see it; [LICENSES.md](../../LICENSES.md) lists it, and a test fails when lxml's list
    changes. Options: replace lxml in the import (for example with defusedxml's parser, already
    a dependency, and a pure-Python XSD validator under a permissive licence), or accept the
    library as a documented exception. The import's author decides with the owner.

Merging `main` up to `1f7924c` left this one:

15. **A model listed before its evaluation** (ADR 0010): `main` puts `qwen2.5:7b-instruct`
    (Apache-2.0) on the model allow-list on 2026-11-21 while its answers are still being
    evaluated, and its risk discovery runs call it when a client starts one
    ([ADR 0013](../decisions/0013-risk-grading.md), proposed).
    [ADR 0010](../decisions/0010-boq-anomaly-detection.md) says a model joins the list only after
    it passes the gates of an accuracy evaluation, and that the list is empty until then. Options:
    amend ADR 0010 so that a checked licence lists a model and every answer is checked against
    the bill (`main`'s approach), or take the entry off until the evaluation (B5) passes.

Merging B2 with pull request #10's branch left this one:

16. **Recall in the first 20 and 50 findings next to risk notes** (benchmark scoring): `main`
    counts the first 20 or 50 findings in the register's order; B2 leaves correct risk notes
    (a bill's list of its contingency positions) out of precision at K. The merge makes recall
    at 20/50 read the same list as precision at K: a correct risk note takes no place, and a
    risk note that names a wrong row keeps its place but finds nothing. The standard benchmark
    shows 1.000 for both either way; the BoQ report does not show them. The other option is
    the register's full order, in which every listed note uses up a place.

Merging B2 with `main`'s risk grading (through pull request #10 at `100c1f3`) left this one:

17. **B2's checks in the risk report** (risk grading, `findings.yaml`): answered in part on
    2026-11-21 by the owner's decision "findings first, risk list second". `findings.yaml`
    (version 0.3) lists B2's nine checks with a risk type per rule, the client questions of the
    risk rules they replace and the counts that say a check read something, and the risk rules
    that repeated a B2 check are gone ([risk grading](#risk-grading-in-main) has the list). That
    settles the first two consequences of the merge with pull request #10 (B2 findings of
    different rules on one position in one "Other risk" reminder, now possible only for the B2
    rules that stay "Other risk"; no coverage from B2's checks) and the drawings question of the
    third (V03 is gone, and the reminder of `domain.boq_clauses`' document references asks for
    the drawings itself). Still open for the risk package's author and the owner, and not changed
    by this branch:

    1. Candidates that share a cell merge whatever their risk type
       (`backend/app/risk/grading.py`), so a table's document-reference finding merges with
       another B2 text finding that marks one of its positions, and the reminder takes the
       stronger one's risk type.
    2. A listed check's coverage row counts every open finding of its risk type, whichever check
       raised it (`backend/app/risk/findings.py` counts by risk type): B2's document references
       make `deterministic.reference_integrity`'s R041 row read "risk",
       `deterministic.unit_price_components` does the same to the R076 rows, and
       `domain.boq_bid_prices` to the R078 and R079 rows of `deterministic.required_values` and
       `deterministic.numeric_validity`. `main` already does this between its own checks.
    3. C04 (a reference to a position the bill does not have) reports what
       `deterministic.reference_integrity` reports in the issue register.
