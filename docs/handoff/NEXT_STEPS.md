# Next steps

Written on 2026-11-20. Read this file first, then [`docs/product/brief.md`](../product/brief.md)
(the master brief, Parts A to M, verbatim). The brief is the requirement; this file is the plan,
and [`PROGRESS.md`](PROGRESS.md) says where each part stands.

## 1. Where things stand

Phase 1 and its first round of fixes are merged into `main` (pull request #3, 2026-11-20). Step
A2, which finishes the smaller fixes of that round, was built and merged on
`claude/project-thread-0s4qdy`, and so were the fixes of its two independent reviews; that
branch reached `main` with pull request #5 on 2026-11-20 (merge commit `10d6ca9`). The
questions the reviews leave for the owner are listed in
[PROGRESS.md](PROGRESS.md#open-questions). Phase B, which the owner approved on 2026-11-20, has
started: its steps B0 and B1 are built (below). Every change reaches `main` through a pull
request that the owner merges.

The teammate's GAEB import, pull request #4, was merged into `main` on 2026-11-20. It reads
GAEB DA XML 3.3 bills in the phases X81, X83 and X84 and validates them against the official schemas, raises
the BoQ profile `boq.yaml` to version 1.2.0 with the fields `discount_percent`,
`standard_text_key` and `standard_text_catalog`, and adds a fifteenth baseline check,
`domain.standard_text_keys` ([ADR 0009](../decisions/0009-gaeb-import.md)). `main` also holds
the hackathon's sample bills (`Sample BoQ Dataset/`) and the challenge brief
([challenge-a.md](../product/challenge-a.md)). They are GAEB DA XML 3.1 and 3.2, GAEB 90
(`.D83`, `.D84`, `.D86`), PDF and Word files, which the import of pull request #4 did not read.
The teammates' work in `main` (commits `c2e2ee2` to `5439d02`) now reads all nine GAEB files
([ADR 0010, older GAEB formats](../decisions/0010-older-gaeb-formats.md)) and all 34 PDFs
([ADR 0011](../decisions/0011-pdf-bills-and-excel-export.md); scanned pages by OCR,
[ADR 0012](../decisions/0012-ocr-for-scanned-pdfs.md)). Only the Word file is not read. The
branch `claude/project-thread-0s4qdy` brought A2 together with that `main`, and pull request #5
merged it into `main`; Phase B builds from the latest `main`.

Steps B0 and B1 were built on the branch `wp/b01` and merged onto `claude/project-thread-0s4qdy`
at commit `35a3926`, the last commit of pull request #5, on the branch that holds this page,
`wp/b01-main`, which pull request #6 merged into `main` (`d462253`). After the merge, the
branch applies the first nine decisions of the review that aligned Phase B with the GAEB
import, each in its own commit ([PROGRESS.md](PROGRESS.md#phase-b-steps-b0-and-b1-in-main)
lists them and the checks): Phase B uses the import's `standard_text_key`; no header maps the
unit price components; B0's decision record is ADR 0010; `boq.yaml` is version 1.3.0; the lock
file is rebuilt from fresh environments and the licence inventory lists what lxml links
statically; the item frame reads the long text and the item discount; an unchanged benchmark
means unchanged quality numbers; and the BoQ benchmark writes the import's item type names and
maps its STLB-Bau column as a reviewer would. The later decisions of that review are not
applied yet: GAEB files in the benchmark (B1.7), the checks of steps B2 to B7, and detector
counts that the tests read from the API instead of hard-coding them. What `main` gained after
`35a3926` is documentation only (the merge commit `10d6ca9`; research reports, the opening
speech and the estimator interview in `docs/product/`; and their rows in the README); the
branch merged it up to `dd4010f`.

The finding categories of plan section 5a (every finding sorted into Error, Omission,
Inconsistency, Ambiguity, Risk or Change order opportunity, or none for reading the file) are
built on `claude/project-thread-0s4qdy`, after `main` up to `e720fa7`
([PROGRESS.md](PROGRESS.md#phase-b-finding-categories)); that branch then merged `main` up to
`5439d02` (older GAEB formats, PDF bills with OCR, the Excel export and the peer-price check:
[PROGRESS.md](PROGRESS.md#older-gaeb-formats-pdf-bills-ocr-the-excel-export-and-the-peer-price-check-in-main))
and took the fixes of the review of that merge and of a final review, then merged `main` up to
`1f7924c` (risk grading: [PROGRESS.md](PROGRESS.md#risk-grading-in-main)). Pull request #10
merged that branch into `main` on 2026-11-21 (merge commit `1283444`, with the same tree as its
head `100c1f3`).

Step B2 is built on the local branch `wp/b2-final`, on top of the finding categories: the
rule checks of plan sections 5a and 8 (tender wording, bid prices, companion work, missing
attributes, misspellings, the prevailing unit price, unit price components, the numbering
hierarchy, GAEB position kinds and duplicates within a Titel), with the lead's six decisions
for the owner to confirm ([PROGRESS.md](PROGRESS.md#phase-b-step-b2-this-branch), ADR 0010's
amendment of 2026-11-21). The branch then merged pull request #10's branch at `37ab12c`
(merge commit `6a5a8fb`), took the fixes of the review of that merge, merged pull request #10
at `104d0b9` (merge commit `2a70812`; every B2 check runs without an error on the sample bills,
PDFs included), and then at its head `100c1f3`, with `main`'s risk grading (merge commit
`c00fa57`; with one change to the risk package, every check passes on the merged tree:
[PROGRESS.md](PROGRESS.md#check-it-yourself)). After `main` moved to `fef7c13` (documents
only, merged in `0ff5268`), the branch took the owner's decision of 2026-11-21, "findings first,
risk list second": the risk rules that repeated B2's checks were removed or narrowed, and B2's
checks are listed in the risk report's table with those rules' risk types and client questions
([PROGRESS.md](PROGRESS.md#risk-grading-in-main)). So it can go up as one pull request against
`main`; it has merged `main` up to `daa3c81` (the tender review, Word documents, the price
context checks, corrections and review, B3's signal checks and B4's problems), keeping one check per condition
([ADR 0013](../decisions/0013-tender-review-checks.md), status note). The workbench now
registers 35 checks, 28 of them in the baseline plan (`domain.boq_separate_payment` and
the six signal checks of step B3 run only when a plan names them), and `boq.yaml` is version
1.6.0.

B3 (the checks against similar positions) and B5 (the local language model) are being built
by teammates from the prompts in `/mnt/project-files/parallel-work/` (with a third prompt for
the risk report page); B4 (problems: related findings grouped) is next for Claude.

## 2. Step A2: finish the smaller fixes

One pull request from the latest `main`: type checking, five backend items, seven interface
items, a documentation pass and two independent reviews.

Contracts between the backend and the interface work:

* **K8 Profile-resolved defaults.** `GET /api/v1/detectors` and `GET
  /api/v1/detectors/{detector_id}` take an optional `profile_id`; each descriptor gains
  `profile_config` (the configuration a run on that profile uses when the plan sets nothing),
  the list gains a top-level `profile_id`; both are `null` without the parameter; an unknown id
  answers `422 invalid_input` with `details.profile_id` and `details.available`
  ([REST API](../api/rest-api.md#system-and-catalogue)).
* **K9 Type checking.** `.venv/bin/python -m mypy`, run in `backend/` with no arguments, checks
  the `app` package in strict mode; CI's backend job runs it in a step named "Type check".
* **K10 Wording.** Adaptive AI planning is "not available in this version" (health note, the
  baseline planner's note, Settings > System).

Tasks: mypy strict with real types and the stubs it needs (T1); K8 in the backend (T2); the
evidence rule fails visibly in its two last edge cases (T3); the exact-duplicates severity
setting renamed to `severity_exact_duplicate` (T4); K10 and a stale comment (T5); the
interface side of K8 and K10, 44 px hit areas (48 px on coarse pointers) with a browser check,
focus after "Reset to defaults", an honest run summary, general plan problems shown, and a
browser test whose backend inherits no `TWB_*` setting (U1 to U7); this documentation pass
(D1 to D8). Then a security review and a contract and data-integrity review, each by an
independent reviewer who fixes what it can prove with a failing test first.

## 3. Phase B: anomaly detection for bills of quantities

Approved by the owner on 2026-11-20.

**Aim.** People upload GAEB bills whose positions use STLB-Bau texts. The workbench reads them
exactly (a teammate builds the GAEB import), finds the anomalies, and shows and explains them.
The challenge: bills of quantities have thousands of line items, people still check them by
hand, and one mistake can get expensive. Priorities: reliable, easy to understand, functional,
secure, simple, nothing over-engineered.

**What a reviewer gets.** A short list of problems, the most money at stake first. Each problem
shows the cells, the calculation or the comparison that proves it, and a plain explanation.
Rule checks confirm errors. Statistical and machine-learning checks only say "check this", with
the comparison shown. On request, a local language model explains a problem in plain words, and
every number it shows comes from the stored finding.

**Three layers.**

* Rules find arithmetic and structure errors with certainty. Fourteen rule checks existed
  before Phase B; the GAEB import added a fifteenth baseline check,
  `domain.standard_text_keys`, which compares items that name the same standard text (another
  unit or unit price, keys from several catalogues or catalogue versions); its findings are
  warnings and signals, never confirmed errors. B2 added what GAEB and VOB/A define and the
  tender checks of plan 5a; `main` added the tender review (missing items, unclear
  descriptions, contradictions, typing slips) and two price context checks. 35 checks are
  registered, 28 in the baseline plan.
* Statistics and machine learning flag unit prices that do not fit comparable positions (B3;
  `main`'s opt-in `statistical.peer_price` is the first). These are signals, never verdicts.
* A local language model explains one problem and its evidence (B5). An accuracy evaluation with
  pass gates decides which models may be used (B5, B7).

**Changes to the earlier design**, recorded with their sources in ADR 0010 (B0; ADR 0009 is the
GAEB import's):

| Earlier | Now | Why |
| --- | --- | --- |
| S1 peer price deviation and S2 rate consistency in the BoQ baseline | Kept; S1 compares first within the same STLB-Bau key and unit when the file has keys. S1 is in `main` as the opt-in `statistical.peer_price` (by text, then section, then unit), still without the key tier and not in a baseline plan; both stay open for B3 | The same standard text and unit are true peers. Keys come only from the user's own files: the STLB-Bau catalogue is a paid product whose terms forbid derived works |
| S3 quantity deviation, opt-in | Deferred | Quantities of identical work legitimately differ within one bill; quantity changes matter when a bid is compared with its tender |
| S4 generic numeric column outliers | Dropped | Not specific to bills of quantities |
| M1 Isolation Forest over engineered features | M1 becomes a similar-positions price check: the nearest neighbours by character n-grams of the short text, with the same unit | Most positions are unique, so exact peer groups are small; similar positions are the comparison an estimator makes, and the reviewer sees them with their prices |
| (none) | New step B2: GAEB and VOB/A rule checks | Price completeness, the VOB/A §16c correction (the unit price prevails), decimal-slip labels and unit price components are the first steps of every arithmetical bid check |
| An LLM analysis of the whole run | An LLM explanation of one problem, on request | Small requests suit CPU-only machines and can be measured one by one |
| Grounding drops claims with unverifiable numbers | The model writes no digits at all: it names slots, and the application fills in the stored values | Language models make basic number errors; slots remove that failure by construction |
| (none) | An accuracy evaluation with gates, run against local models before one is allowed | The owner asked for language-model accuracy proven by tests |
| (none) | No fine-tuned or zero-shot language-model anomaly detection | It needs GPUs, can hide a factor-10 slip by rescaling prices, and gives no reason a reviewer can check |

**What Phase B needs from the GAEB import.** Phase B builds only on the canonical dataset, so the
import and the checks meet there: one row per position with exact decimal values (item code,
short and long text, quantity, unit, unit price, line total, currency); the position kind from
the GAEB flags, not from text (normal, lump sum, contingency items with and without total,
base and alternative positions, omitted positions); "not offered" kept as a value marker,
distinct from an empty price and from 0,00; the STLB-Bau reference as `standard_reference` and
up to six unit price components; titles and lots as section rows and the file's own totals as
total rows. The GAEB DA XML 3.3 element names for these could not be verified when this plan
was written; the teammate confirms them. On this branch the import is merged:
[ADR 0009](../decisions/0009-gaeb-import.md) says what it provides, and
`backend/app/ingestion/gaeb/flatten.py` lists its columns. Three differences from this list:
the STLB-Bau reference is `standard_text_key` (its catalogue and version in
`standard_text_catalog`), not `standard_reference`; the position kinds are German names in
`item_type`, set from the flags, so "not offered" is the item type "nicht angeboten", not a
value marker; and the unit price components are not read yet. Phase B follows the import in
all three: B0's fields and item frame use `standard_text_key`; the BoQ benchmark writes the
import's item type names in half of its Positionsart columns, and B2.1 is to take "nicht
angeboten" in the item type as well as the value marker; and no header maps the unit price
components (a reviewer does, until the import reads them).

**Steps**, one pull request at a time from the latest `main`:

| Step | Adds |
| --- | --- |
| B0 | Python 3.12, NumPy and pandas; `validation/support/` (item frame, robust statistics, text keys); `baseline_detectors` and the new BoQ fields; planner injection; the signal policy; explanation records, storage and schema version 5; LLM settings and the health block; ADR 0010 |
| B1 | A BoQ benchmark variant with realistic similar positions and planted price errors; metrics per check |
| B2 | GAEB and VOB/A rule checks |
| B3 | S2 and M1, and the checks of plan section 5a (S1, the peer-price check, is already in `main` as an opt-in check built by a teammate) |
| B4 | Problems: related findings grouped deterministically |
| B5 | LLM explanations: provider interface, Ollama adapter, slots, verification, background job, storage, safety, accuracy evaluation |
| B6 | Interface and exports |
| B7 | Measurement, tuning, documents, final review |

B0 and B1 are in `main` (pull request #6, see section 1). B2 is built on `wp/b2-final` (see
section 1); B3 and B5 are with teammates, and B4 is next for Claude.

Later, in this order: comparing several bids (price comparison), the LLM planner, local
embeddings for similar positions, Isolation Forest and LOF. A bid is compared with its tender by
`domain.boq_tender_comparison` (see `docs/evaluation/README.md`, "Bid against its tender").

Contracts between the steps (P1 to P11): the item frame (`validation/support/items.py`, read
once per run), robust statistics (`validation/support/robust.py`), the effective baseline
(`DomainProfile.baseline_detectors`), planner injection (`Workbench.planner`), the signal policy
in `IssueFactory.create`, the problem and explanation records (schema version 5), the LLM
settings (`Settings.llm`, an `llm` block in the health answer), the routes
`GET /api/v1/validation-runs/{run_id}/problems` (B4) and `POST` and `GET
…/problems/{problem_id}/explanation` (B5), the benchmark variant (B1), the text index of the
similar-position checks (`validation/support/similar.py`, B3) and the reference amount (B3):
`FinancialImpact.kind` gains `"reference_deviation"`, what is at stake if a position were
priced or measured like the positions it is compared with. That amount is multiplied by the
item's `discount_factor` from the item frame (1 without a discount; no amount when the discount
cell is unreadable), so it is as discounted as the line total it stands for. The item frame
also reads the long text (`long_description`).

## 4. Rules that must keep holding

- Security (brief Part B.5, verbatim there): uploaded documents and cell contents are untrusted;
  never execute formulas, macros, shell commands or code from documents; the LLM may only
  request approved validation tools through a restricted, schema-validated interface; protect
  against malicious and oversized files, ZIP and XML attacks, path traversal, CSV formula
  injection, prompt injection in descriptions; keep the original upload unchanged. Security
  never gets weaker: upload checks, host, origin and CORS checks, body limits, formula-injection
  protection in exports, sign-in.
- Exact decimals everywhere money is computed; floats only inside statistics and scores.
- Signals, not verdicts: statistical, machine-learning and language-model output never becomes a
  confirmed error; only rule checks and reviewers confirm. Every score is uncalibrated until a
  calibration report exists; no invented confidence, accuracy or probability.
- Abstain rather than guess on ambiguous, missing or low-confidence input.
- No business rules in generic code: words, units, thresholds, groupings and severities live in
  profile YAML or typed configuration.
- Plans: trust comes from the code path; plans set only `plannable` parameters; tolerances and
  patterns stay in profiles; LLM plans keep every baseline check.
- Licences: MIT, BSD, Apache-2.0, ISC, PSF, MIT-0, 0BSD, BlueOak; MPL-2.0 only for packages
  used unmodified at build or test time or as data; never GPL, LGPL or AGPL. Every new package
  gets a row in `LICENSES.md`. The GNU
  libiconv (LGPL 2.1) that the lxml wheels link statically is an open question for the owner
  ([PROGRESS.md](PROGRESS.md#open-questions), question 14).
- The synthetic benchmark keeps its documented numbers unless a step changes them on purpose
  (seed 20261119: 100 bills, 7,507 rows, 141 injected errors, 193 findings, every injected
  error found, no false positive), always labelled "Synthetic benchmark: measured on generated
  data, not real-world performance". "Unchanged" compares the quality numbers (bills, rows,
  injected errors, findings, false positives and the table by kind), not the timing lines,
  which differ from run to run and machine to machine.
- Interface: every control at least 44 × 44 CSS px (48 × 48 on coarse pointers), keyboard
  access, visible focus, plain words, WCAG 2.1 AA contrast; no non-functional controls and
  nothing the backend does not produce.
- Part M: no fake progress, no broken routes, no hardcoded example findings, no unsupported
  reliability claims, never silently skip failed tests.

## 5. Notes for the next session

- The scripts in `docs/handoff/workflows/` are the multi-agent workflows used so far; each
  assigns strict file ownership so agents can work in parallel. Change `ROOT` to the new
  checkout path before reusing them. `design-critique.workflow.js` produced the reviews in
  `docs/handoff/critiques/`.
- The owner follows Apple's Human Interface Guidelines for layout and Material Design.
- Commits and pull requests carry the attribution lines your environment prescribes; the owner
  reviews and merges.
