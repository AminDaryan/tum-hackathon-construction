# Evaluation

The synthetic benchmark of brief Part L and NEXT_STEPS step 10. The latest reports are
[synthetic-benchmark.md](synthetic-benchmark.md) (the standard variant) and
[boq-benchmark.md](boq-benchmark.md) (the BoQ variant); the code is `backend/app/evaluation/`.
Every number in them is labelled "Synthetic benchmark: measured on generated data, not
real-world performance".

## Main score: F2 at 50

Every benchmark leads with **F2 at 50**: per bill, the first 50 findings in the issue register's
order (spelling and text-style findings last, otherwise severity, then position), precision P = the share of them that are right (0 when none
are shown), recall R = the share of the bill's planted errors they find, and
F2 = 5PR / (4P + R), the F-beta score with beta = 2, which weighs recall four times as much as
precision. The headline is the mean over the bills with planted errors (a bill without them has
no F2; its findings count as false positives), with the mean precision and recall at 50 beside
it. Every finding counts, signals included. On generated bills a finding is right when it is a
true positive of the benchmark's rule (`backend/app/evaluation/scoring.py`); on a bill with an
answer key, when one of its rows is a fault's row. The code is `f2_of` and `mean_at_50` in
`scoring.py`, which the answer-key scorer and the ablation use too.

Plan step B7 measured every check at once, each check's value by leaving it out, the 26-fault
answer key and status-quo reading orders: [boq-benchmark-b7.md](boq-benchmark-b7.md). Benchmark
B8 scores the checks on held-out bills whose faults were planted blind:
[boq-benchmark-b8.md](boq-benchmark-b8.md).

The checks of step B2 were also measured on the sample bills and scored on a planted-fault
test bill: [b2-rule-measurement.md](b2-rule-measurement.md).

The larger development set, [practice P1](boq-practice-p1.md), has 176 independently planted
faults across eight variants of four priced offers, plus 64 look-alike controls. It is for
tuning; B8 remains held-out and score-only. P1 uses B7's shared answer-key scorer.

How the rule checks and the language-model review work together on one bill (checks, rule
reliability, three reading passes over the whole bill, certain claims, reading list) is drawn as
a flowchart with the P1 results of 21 Nov 2026:
[error-finding-flow.html](error-finding-flow.html). Open the file in a browser. It shows the
design chosen after the fresh run of 21 Nov (no judge); P1 is a development set, so its numbers
are not a blind test.

The fresh model-review runs on P1, their reading lists, cost and time, and why the default list
needs no judge: [boq-practice-p1-model-review.md](boq-practice-p1-model-review.md).

## What it does

1. **Generates bills** from a fixed seed: English and German, each as XLSX and CSV. A bill has
   sections of priced items, a subtotal per section, the net total, a tax line and the gross
   total. It also has what real bills have and what must not be reported: a title block,
   continuation text rows, blank rows, contingency and alternative items left out of the totals
   (and contingency items "mit GB" that are counted), and "rate only" items.
2. **Injects errors** into ordinary priced items and totals, the way they happen: digit swaps in a
   line total (summed into the totals as written), a subtotal, the net total or the tax line; an
   unknown unit; a duplicated row; a missing rate on a measured item; a quantity misread as text.
   The ground truth (`manifest.json`) names each error's cell and every row where reporting it is
   correct (its own row and the totals it throws off).
3. **Runs the product's own path** on every file: upload (security checks, extraction,
   normalization) and a validation run with the `boq` profile, which runs every registered check.
4. **Scores** the findings against the ground truth: F2 at 50 (above), precision, recall, F1, precision at K, false
   positives per 1,000 rows, cell localization, row classification accuracy and processing time.
   The exact definitions are in `backend/app/evaluation/scoring.py` and at the end of the report.

## Run it

From `backend/`:

```bash
.venv/bin/python -m app.evaluation
```

Options: `--variant` (`standard` or `boq`, below), `--seed`, `--documents` (per language and
format, default 25), `--max-errors` (per document, default 3), `--k`, `--out`
(default `var/benchmark`, ignored by git). The output folder
holds the generated files, `manifest.json`, `report.json` and `report.md`. Copy `report.md` here
as `synthetic-benchmark.md` when the detectors change. The tests in
`backend/tests/evaluation/` (marker `evaluation`) check that the corpus is reproducible byte for
byte, that clean bills have no findings and that every error kind is found and localized.

**Same seed, same bytes.** Two runs with the same seed write identical documents and an
identical `manifest.json`, so its `sha256` values identify the files of a run. XLSX files carry
a fixed creation and modification time (1 January 2026, `WORKBOOK_TIMESTAMP` in
`backend/app/evaluation/synthetic.py`) in their document properties and ZIP entries instead of
the time of the run. This holds for the same versions of Python (and its zlib) and openpyxl;
another version may compress or write the files differently.

## The BoQ variant

`--variant boq` generates bills of quantities that behave like real ones and plants errors of
all seven anomaly types a BoQ (GAEB) can hold: price, quantity, unit, semantic, structural,
logical and duplicate. Code: `prices.py` (catalogue and price model), `boq.py` (bills and
planting), `expectations.py` (which check should find each kind, and under which finding
category), `boq_report.py` (the report).

- **Bills.** One Titel per trade (12 trades, positions written for this project in German and
  English; no STLB-Bau text is copied, the keys are synthetic `SYN-...` keys), 80 to 1,500
  positions per bill (`--positions`). A quarter of the bills repeat their positions per building
  under Lose (Haus A, Haus B), with the same unit price for the same work; a quarter carry an
  STLB-Bau key column and a quarter unit price component columns (EP-Anteil, two to four); half
  of the German bills have a Positionsart column, the others mark Bedarfs- and Wahlpositionen in
  the text; a quarter are in English. Of the Positionsart columns, every second one writes the
  names the GAEB import gives its item types (Normalposition, Grundposition, Bedarfsposition mit
  GB, Bedarfsposition ohne GB, Wahlposition) and the others the short codes of spreadsheet bills
  (N, G, BmGB, BoGB, Wahl); they are taken in turn, not drawn, so nothing else in a seed's bills
  changes with them. Located work (per Bauabschnitt) repeats the same position several times in
  a Titel. The `boq` profile maps the Positionsart column to `item_type` by its header. No
  header maps the standard text key or the unit price components (only a GAEB file's declared
  structure or a reviewer does), so the harness maps them at upload, as a reviewer would: the
  STLB-Bau column to `standard_text_key`, so that `domain.standard_text_keys` runs on the bills
  with keys, and the EP-Anteil columns to `unit_price_component_1` to `_4`
  (`SyntheticDocument.column_fields`, recorded in `manifest.json`). A clean bill gives that
  check nothing to report: one key always has one unit and one unit price in a bill. In a
  planted bill it also flags a changed unit price or unit of a position whose key another row
  shares, which the report lists under the check that found it. The item frame of the comparison
  checks reads every generated position with its exact values
  (`tests/evaluation/test_boq_item_frame.py`).
- **Prices.** Base price × option factors × a bill factor (regional price level) × noise per
  position family, rounded to cents; quantities lognormal around a typical size. Amounts are
  `Decimal`; the random factors are floats only inside the generator.
- **Planted kinds** (up to 8 per bill, dealt from a shuffled deck of all kinds): the eight
  standard kinds; price: `price_decimal_slip`, `price_digit_swap`, `inconsistent_rate` (one copy
  of a repeated position priced differently), `wrong_rate_copied`, `placeholder_price`,
  `high_contingency_price`; quantity: `quantity_decimal_slip`, `quantity_unit_slip` (cm or mm
  in an m position); unit: `wrong_unit`, `price_per_wrong_unit` (a price per m² in a m³
  position); semantic: `misplaced_position`; structural: `code_outside_section`; logical:
  `line_total_slip`, `component_sum_error`; duplicate: `duplicate_position` (the next code),
  `near_duplicate_position` (slightly changed text). A changed price or quantity is carried
  into the line total and every total, so only the check named for the kind can find it.
- **Ground truth** names the wrong cell and every row where reporting the error is right: for a
  changed price or quantity also the same position elsewhere (a comparison may flag either), for
  a copy also the original.
- **Expected checks.** `expectations.py` names the check (and, where the plan names them, the
  rules) expected to find each kind. Those of plan steps B2 (rule checks) and B3 (signal
  checks) are built, and every run plans every registered check. While no expected check of a
  kind is available, the report says "check not available yet" for the kind, not a recall of
  0. A check is not available when it is not registered, or when it needs a profile setting
  (`Check.setting`) that the profile's defaults lack. One expected check needs one:
  `deterministic.exact_duplicates` finds `duplicate_position` only when it ignores the item
  code, and the `boq` profile sets that, so the kind is measured.
- **Report.** Recall and cell localization per kind (by the expected check) and per check and
  kind (any check that flagged a planted error); planted and found errors per finding category
  (each kind under the category its expected check gives its findings, `EXPECTED_CATEGORY` in
  `expectations.py`; found means a matching finding of any check carries that category; the
  kinds whose expected check is not available yet are counted apart, planted but not
  measured, and show "check not available yet" instead of a found count); rule
  findings on unplanted rows (false positives) apart from signals on unplanted rows, which are
  counted per 1,000 item rows for each signal check, with the ten strongest listed (a generated
  bill may hold an odd price by chance, so a signal there is not called a false positive);
  findings per planted error. A list of a bill's contingency and hourly positions
  (`domain.boq_position_types`) is scored against the generator's own item types: when every
  row it names is such a position it is a correct risk note, reported on its own line ("Risk
  notes on unplanted rows, checked against the generated bill") and left out of precision and
  false positives; a list naming any other row is a false positive. Both variants score it so.
- **Clean bills.** A bill without planted errors produces no finding of today's checks but the
  correct risk note of a German bill with contingency positions, for every combination of the
  features above, as XLSX and as CSV (`tests/evaluation/test_boq_corpus.py`). CSV bills keep every decimal place of a quantity
  (masses in t have three), so their line totals agree with quantity × unit price.

```bash
.venv/bin/python -m app.evaluation --variant boq --seed 20261120 --documents 100
```

`--documents` counts bills here; `--seed` defaults to 20261120 and `--max-errors` to 8 for this
variant. The standard variant keeps its seed. Since step B2 two of its German item texts name
the backfill and the waste class, so its files differ from before; its bills, rows, injected
errors, false positives and the table by kind are the same, and its findings add 47 correct risk
notes ([report](synthetic-benchmark.md)). Only the timing lines differ from run to run.

### Each check left out, and status-quo baselines

```bash
.venv/bin/python -m app.evaluation --variant boq --seed 20261121 --documents 100 --ablation
```

`--ablation` adds a section to the report (`backend/app/evaluation/ablation.py`), on top of the
full run with every registered check:

- **Leave-one-out ablation.** Each bill is validated again once per registered check with that
  check left out of the registry, so a check's value is measured, not attributed: the F2 at 50
  it adds, the planted errors no finding matches any more without it, and how many signals and
  rule findings on unplanted rows it adds.
- **Review budget.** Planted errors found within the first K items a reviewer reads per bill,
  K = 20, 50 and the number of our findings in that bill, for five lists: our findings in the
  issue register's order (spelling and text-style findings last, otherwise severity, then
  position), the bill's lines top to bottom, the lines in
  a random order (seeded with the corpus seed and the bill's name), the item lines by line total,
  largest first, and our findings interleaved with that list (a finding, then the most
  expensive line not shown yet, in turn). Each list also gets an F2 at 50: precision is the
  items among its first 50 that show a planted error's row. A line is an item or total row; the line lists count
  an error as found when a line read is one of its rows, which assumes a reviewer recognizes it.
  Our findings are read as the recall in the first 20 and 50 findings reads them: a correct risk
  note on an unplanted row takes no place, a wrong one keeps its place and matches nothing.

Every run is scored like the benchmark (`score_document`, risk notes included). With 36
registered checks it runs 37 validations per bill, so 100 bills take about 35 minutes. Results:
[boq-benchmark-b7.md](boq-benchmark-b7.md).

## Score against the hand-planted answer key

```bash
.venv/bin/python -m app.evaluation \
  --answer-key "../Sample BoQ Dataset/Faulty Data By Claude AI/boq-StBALV23040-PLANTED-FAULTS-answer-key.json" \
  --clean "../Sample BoQ Dataset/StBALV23040.D86" --out var/benchmark/answer-key
```

Any paths and file names work, and `--bill FILE` scores a bill other than the one the key's
`file` names (needed when the key names none). Uploads the bill and its clean original with the `boq` profile, validates both
with every registered check, and reports F2 at 50, faults found, found in the first 20 and 50 findings
of the register, must-not-flag hits and the faults only one check finds, each before and after
the clean-original discount: a hit is not credited when the same check and rule also report the
same line (item code, or row kind and text) of the clean original. The clean counterpart is the
GAEB 90 file `StBALV23040.D86` the faulty copy was made from (the key's
`boq-StBALV23040-original.xlsx` is not in the dataset), read by the GAEB import, while the faulty
copy is read as a spreadsheet. The key's own rule applies to every finding: a hit is any named
row in a fault's rows. A real bill has no generator item types to check a risk note against, so
a list of positions (`domain.boq_position_types`) counts like any other finding, and its hits on
other kinds of fault can be incidental. The report (`answer-key-report.md` and `.json` in `--out`) holds
counts and check ids only. Everything runs locally; the sample data stays on this machine
(`backend/app/evaluation/answer_key.py`).

## Plant errors into your own bills

```bash
.venv/bin/python -m app.evaluation --inject-into ~/bills --out var/benchmark/inject
```

Every `.xlsx` and `.csv` file directly in the folder is read and uploaded into a temporary
workbench on in-memory storage, through the product's own path. The errors are planted **into a
copy of the canonical dataset in memory**, stored as its next revision: the files are never
changed, nothing is written into the folder, and the temporary workbench, with its copy of the
upload, is deleted at the end of the run. The validation runs on the revision as read and on
the planted one, so the report separates what a bill already held from what planting added.

Planting uses the same kinds as the BoQ variant, on item rows that count toward the totals and
whose quantity, unit price and line total agree. A changed line total is carried into the
subtotals of its sections, the net total, the tax and the gross total. A kind that no row fits
goes to the next file; the report says why a kind was not planted at all. `component_sum_error`
is never planted here: it needs unit price component columns mapped by a reviewer, and no
header maps them.

The command prints counts only, never file names, rows or cell values. The report
(`inject-report.md` and `inject-report.json`, with recall per kind and every finding that
matches no planted error, marked as already in the file as read or not) is written only to
`--out`, which must lie outside the folder. Keep it out of the repository: it names rows of
your bills and finding titles may quote their values. Options: `--seed`, `--max-errors` (per
file, default 8), `--k`.

## Bill against a model (IFC)

`domain.model_quantities` compares a bill with an attached IFC model (`PUT
/documents/{id}/model`). Its test model,
`Sample BoQ Dataset/Faulty Data By Claude AI/boq-StBALV23040-model.ifc`, is generated by
`tools/ifc_demo/generate_pipeline_model.py` from the clean original bill (StBALV23040.D86), and
made imperfect on purpose, with shares fixed before any result was seen:

- accurate positions measure 97 to 103 % of the bill (pieces exact);
- about 5 % of the modelled positions carry no item number, 5 % are measured by other rules
  (7 to 15 % off, or one piece more or less), and 5 % name the work in other words;
- three positions carry the designer's own mistakes: an element missing, a quantity 25 % too
  high, and an element linked to an item number that does not exist.

Every deviation is listed in `boq-StBALV23040-model-key.json` next to the model. Of 115
modelled positions, 18 deviate (7 unlinked, 4 measured differently, 4 renamed, 3 design faults).

Measured on 2026-11-21 on `main` 1d86ba3 (with steps B2 to B4):

| 26-fault bill | Without the model | With the model |
| --- | --- | --- |
| Baseline plan and `statistical.peer_price`: faults found | 21/26 | 23/26 |
| in the first 20 / first 50 findings | 11 / 21 | 11 / 19 |
| All opt-in checks added: faults found | 23/26 | 25/26 |
| in the first 20 / first 50 findings | 11 / 22 | 11 / 17 |

The model finds two faults no other check finds: pf-18 (a position moved to another section)
and pf-19 (a quantity of 25 m against 243 m modelled); it also finds pf-07 (the same work
priced twice), which step B2 finds as well. Its findings cost review budget: they push other
faults out of the first 50 findings. It misses pf-05, a hire period, which a design model does
not hold. On the clean original bill it reports 8 findings: the three design faults of the
model, the bill's damaged item number TEL00009, and four positions measured by other rules
(low and medium severity: a real disagreement between the documents, not an error of the bill).

The rule for work priced twice was limited to repeats within one section after the first
imperfect model showed three false alarms on work the bill repeats on purpose in other sections.

**The position rules were tuned to this bill.** The rules for moved, renumbered and twice-priced
positions were written after reading the answer key's entries for pf-07 and pf-18. A blind test
checked them: a separate agent that saw only the clean bill planted 10 such faults (3 moved, 3
renumbered, 4 priced twice) into it. Counting a finding on any row a fault touches, the checks
found 3/10 without the model (1 in the first 20 findings) and 4/10 with it (2 in the first 20);
counting only the faulty row itself, 2/10 either way. Seven of the ten sat on positions the model does
not contain; the one fault the model found, an exact copy in the same section, is also found by
`exact_duplicates`; abbreviated text and copies in other sections were missed. So the position
rules add nothing measurable; the model's value is quantities that are wrong but still add up.

**Still a generated model.** It starts from the right answers, and its deviations are the ones
the generator was written to make. Real models differ from their bills in more ways (design
revisions, other classification schemes, partial coverage). The 5 % tolerance has only been
checked against these generated deviations, not against a design model made independently of
the bill; test it on one before quoting 14/26.

## Bid against its tender

`domain.boq_tender_comparison` compares a priced bill with the tender in its project: an
unpriced bill where at least half of the bid's positions have the same item number with the
same quantity or short text (`app.services.tenders`). It reports positions added to the bid or
missing from it, and quantities, units and texts that differ. Upload the tender and the bid
into one project; nothing else is needed. Measured on 2026-11-22.

**The real pairs of the hackathon files.** Every finding below is a real difference between
the two files:

| Tender | Bid | Compared | Findings |
| --- | --- | --- | --- |
| 8209.003 D83 | [ORT_024] LV24069.D86 (contract) | 159 | the 38 change-order positions (Nachtrag 1 to 6) |
| 8209.003 X83 | [ORT_024] LV24069.D86 | 159 | the same 38, and one long text where the anonymisation wrote O016 for "Teil" |
| [NUMMER_001] X83 | StBALV23040.D84 (prices only) | 247 | 10.01.0001 "Nachträge", which the tender lacks; 8.1.3 missing, renamed TEL00009 by the anonymisation |
| [NUMMER_001] X83 | StBALV23040.D86 | 247 | the same two, and one long text where "Füllmedium" reads "Füll10pt" |

The text rules set aside what only the file formats or the anonymisation change: a short text
cut at GAEB 90's 70 characters (35 positions of StBALV23040.D86), a repeat position's lead-in
("Wie Position 3. 2. 7., jedoch"), the marks around a text complement ("[TA11 ...]"), tokens
padded to other widths, words the anonymiser took into a token in one file only, and spacing
or hyphenation at joined lines. They were written after reading these pairs.

**Practice benchmark P1, bills A and B, with their real tenders.** P1's faults were planted into
StBALV23040.D86 (A) and LV24069.D86 (B), whose tenders are among the hackathon files
([NUMMER_001] X83 and 8209.003 D83). The tenders are the client's own files, not the answer key.
Checks only, no model, mean per-bill F2@50 as in the main score:

| Variant | F2@50 without the tender | F2@50 with it | Faults found (of 22) |
| --- | --- | --- | --- |
| A-v1 | 0.578 | 0.808 | 15 → 20 |
| A-v2 | 0.724 | 0.882 | 19 → 22 |
| B-v1 | 0.818 | 0.899 | 21 → 22 |
| B-v2 | 0.713 | 0.873 | 19 → 22 |
| Mean | 0.708 | 0.866 | 74 → 86 of 88 |

The comparison's findings touch 13 of the 22 faults of each variant. The 9 it cannot see are
in prices and arithmetic (a discount, a sign, tax in a rate, a rate's decimal shift, a missing
price, an overwritten total) and one deleted quantity, which the bill's own checks report. On
the clean bills it reports 3 findings (A) and 38 (B), the real differences in the table above;
with the clean discount the mean rises from 0.60 to 0.85.

Development data: one text rule was changed after P1's misses were read (a word replaced next
to a token is reported; only words added or left out beside a token are not, because the
anonymiser takes neighbouring words into a token). Bills C and D have no tender in the files.
B8 was not run.

## How to read the numbers

- **Synthetic only.** No labelled real bills were available, so there is no real-world result.
  Do not quote these numbers as the tool's accuracy on real documents. Errors planted into your
  own bills (`--inject-into`) are generated too: their recall says nothing about the errors the
  bills really hold.
- **The errors are the kinds the checks were built for.** The generator and the detectors come
  from the same team. A perfect score shows the deterministic checks work as specified, including
  on the realistic structures above; it does not show that errors of other kinds are caught.
  Not covered, for example: a wrong quantity or rate whose total was recomputed consistently
  (no arithmetic check can see it), items in the wrong section, missing scope.
- **Error kinds occur equally often** by construction, not with real-world frequencies.
- **CSV display rounding.** In a CSV every amount may have been rounded for display, so a total
  over many lines is allowed a drift of 0.005 per summed line. A small slip in a large total can
  then only be reported as possible display rounding (severity info), not as a confirmed
  mismatch. The current report has one such case; it counts as detected, not with the expected
  rule.
- **Scores are ratios over this set, not probabilities.** No finding carries a calibrated
  probability.
- **Timing** was measured on one laptop (the report names it) with in-memory storage; it is
  indicative only.
