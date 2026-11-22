# Synthetic benchmark report

Synthetic benchmark: measured on generated data, not real-world performance.

**Rerun on 2026-11-21 with the checks of step B2** (24 checks registered, 23 of them in the baseline plan). Two German item texts of the generator changed with B2: "Baugrube ausheben" is now "Baugrube ausheben und verfüllen", and "Boden laden, abfahren und entsorgen" now ends with the waste class ", Z 1.1". The new checks ask a bill to say how an excavated trench is backfilled (`domain.boq_companion_work`, `trench_without_backfill`) and which waste class is disposed of (`domain.boq_required_attributes`, `disposal_waste_class`); without the change, every clean German bill would get findings that the generator does not mean as errors. So the generated files differ from the earlier report's (other file hashes), with the same rows, injected errors and ground truth. The only changed numbers: findings rose from 193 to 240 (de-csv from 52 to 75, de-xlsx from 47 to 71). The 47 added findings are each a German bill's list of its contingency positions (`domain.boq_position_types`, "Bedarfsposition mit/ohne GB"); checked against the generated bill, every one names only contingency positions, so each is a correct risk note (the line "Risk notes on unplanted rows, checked against the generated bill"), not a false positive. Precision, recall, false positives per 1,000 rows, detection with the expected rule (0.993, the same display-rounding net-total miss in en-csv-022) and the table by error kind are unchanged; the timing lines differ (another machine). Run again after the review fixes of step B2 (a bid that offers few of its positions is checked, a contingency list is scored by every position it names, and the wording and typo rules skip a few correct phrasings): every quality number is the same; that run took 0.074 s median per document, 905 rows per second.

**Rerun on 2026-11-21 after this branch merged pull request #10's branch** (`37ab12c`, with `main` up to `5439d02`; 25 checks registered, 23 of them in the baseline plan, as `main`'s `statistical.peer_price` is opt-in). Against this branch before the merge (`ccb9c84`), every quality number is unchanged. The report has two rows from `main`, recall in the first 20 and in the first 50 findings, and both are 1.000. The timing lines differ: 0.077 s median per document and 897 rows per second (were 0.074 s and 905). Against pull request #10's branch (`37ab12c`), whose committed report was not regenerated after `main` was merged in, the findings are 240 (were 193: de-csv 75 for 52, de-xlsx 71 for 47), the 47 correct risk notes described above, and their line "Risk notes on unplanted rows, checked against the generated bill" is new. The two recall rows are new in this file as well; that branch measured 1.000 for both. The timing lines there came from another machine (Darwin arm64: 0.048 s median per document, 1453 rows per second).

**Rerun on 2026-11-21 after the review of that merge.** Only the two recall rows' labels and the Definitions paragraph changed. The merge made recall in the first 20 and 50 findings read the list that precision at K reads, which passes over correct risk notes on unplanted rows, so the label "(register order)" said more than was measured: the rows now read "Recall in first 20 findings (register order, correct risk notes on unplanted rows take no place)" (and the same for 50), and the Definitions paragraph defines them. Every quality number is unchanged (both recall rows are still 1.000); the run also has the review's two boq profile fixes (GAEB 90 record 30 and the bid notes), which this corpus of CSV and XLSX bills does not reach. The timing lines differ: 0.075 s median per document and 912 rows per second (were 0.077 s and 897).

**Rerun on 2026-11-21 after the merges with `main` at `b92f13d` and `ea41168`** (the tender review and the two price context checks; 30 checks registered, 28 of them in the baseline plan of `boq`). Every quality number is the same; only the timing lines differ (0.084 s median per document, 791 rows per second).

**Rerun on 2026-11-21 with every check on** ([ADR 0010](../decisions/0010-boq-anomaly-detection.md), amendment of 2026-11-21: every validation runs all 35 registered checks, and the benchmark no longer drops the signal checks from its plan). Every injected error is still found (recall 1.000, cell localization 1.000), but the standard variant scores every finding that matches no injected error as a false positive, signals included: 848 of them on 7,507 rows (112.96 per 1,000 rows; were 0), so precision fell from 1.000 to 0.192 and precision at 5 to 0.338. They come from three signal checks: 499 of `statistical.peer_price` (`peer_price_outlier`), 310 of `semantic.section_fit` (`position_closer_to_other_section`) and 39 of `domain.boq_description_clarity` (`catch_all_wording`). The standard generator writes small bills whose items vary in price and text without regard to comparable positions, which these checks read as outliers; no rule check reports anything the bill does not hold. Timing: 0.103 s median per document, 605 rows per second.

**Rerun on 2026-11-21 with the standard generator fixed** (36 checks registered, every one run). The 848 false positives of the run above came from the generator, not from the checks: copies of one catalogue item had unrelated random prices (an "Internal door set" at 128 and at 1013 in one bill), items were placed in sections named for other trades (an "Excavate trench" under "Drainage"), and two German texts really were catch-all wording ("Innentür komplett", the continuation "einschließlich aller Nebenarbeiten"). The generator now fills each section with the work its name says (`SECTION_ITEMS` in `backend/app/evaluation/synthetic.py`), prices the copies of one item within 10 % of each other, and writes "Innentür mit Zarge" and "inkl. Befestigungsmaterial"; no check was loosened for it. The bills are different files with other injected errors (the table by error kind), and every injected error is still found. False positives fell from 848 to 3 (0.414 per 1,000 rows; 2 of `semantic.section_fit`, 1 of `statistical.peer_price`), precision rose from 0.192 to 0.984 and recall stays 1.000. On seed 31, the confirmation seed, false positives fell from 952 to 3, precision from 0.184 to 0.986, recall 1.000. Timing: 0.096 s median per document, 631 rows per second.

**F2 at 50 added on 2026-11-21 (plan step B7)**, on `main` at `d171553` and again at `3ddaa48` (same results): F2 at 50 is now the main score of every benchmark (defined in [README.md](README.md#main-score-f2-at-50)). It is 0.996, with a mean precision at 50 of 0.986 and a mean recall at 50 of 1.000. Every other quality number of the run is the same as above; the timing lines are kept from that run.

Synthetic documents only: generated bills with injected errors. No real-world documents were evaluated, so these numbers say nothing about performance on real bills. The values are ratios over this generated set, not probabilities.

Seed `20261119`, profile `boq`, 25 documents per language and format. Regenerate with `python -m app.evaluation` (see `--help`).

## Synthetic documents

| Metric | Value |
| --- | --- |
| **F2 at 50 (main score)** | **0.996** |
| Precision at 50 (mean) | 0.986 |
| Recall at 50 (mean) | 1.000 |
| Documents | 100 |
| Data rows | 7243 |
| Injected errors | 137 |
| Findings | 238 |
| Precision | 0.984 |
| Recall | 1.000 |
| Recall in first 20 findings (register order, correct risk notes on unplanted rows take no place) | 1.000 |
| Recall in first 50 findings (register order, correct risk notes on unplanted rows take no place) | 1.000 |
| F1 | 0.992 |
| Precision at 5 | 0.986 |
| False positives per 1,000 rows | 0.414 |
| Risk notes on unplanted rows, checked against the generated bill | 46, all correct |
| Detected with the expected rule | 1.000 |
| Cell localization | 1.000 |
| Row classification accuracy | 1.000 |
| Median time per document (s) | 0.096 |
| Rows per second | 631 |

Timing machine: Darwin arm64, Python 3.13.5.

## Real-world documents

None evaluated: no labelled real bills are available. Synthetic results must not be read as real-world performance.

## By error kind

| Error kind | Injected | Detected | With expected rule | Cell localized |
| --- | --- | --- | --- | --- |
| `line_total_arithmetic` | 17 | 17 | 17 | 17 |
| `subtotal_mismatch` | 17 | 17 | 17 | 17 |
| `net_total_mismatch` | 17 | 17 | 17 | 17 |
| `tax_mismatch` | 17 | 17 | 17 | 17 |
| `unknown_unit` | 18 | 18 | 18 | 18 |
| `duplicate_row` | 17 | 17 | 17 | 17 |
| `missing_unit_price` | 17 | 17 | 17 | 17 |
| `invalid_quantity` | 17 | 17 | 17 | 17 |

## By language and format

| Variant | Documents | Rows | Injected | Detected | Findings | False positives |
| --- | --- | --- | --- | --- | --- | --- |
| de-csv | 25 | 1906 | 30 | 30 | 66 | 0 |
| de-xlsx | 25 | 1892 | 36 | 36 | 73 | 2 |
| en-csv | 25 | 1690 | 33 | 33 | 46 | 1 |
| en-xlsx | 25 | 1755 | 38 | 38 | 53 | 0 |

## Missed or misnamed errors

None.

## False positives

| Document | Rule | Rows | Title |
| --- | --- | --- | --- |
| en-csv-017.csv | `position_closer_to_other_section` | 17 | Position closer to section 3 'Section 3 Roofing' than to its own section 2 'Section 2 Steelwork' |
| de-xlsx-012.xlsx | `peer_price_outlier` | 6 | Unit price 3.59 far below comparable positions (median 174.8) |
| de-xlsx-019.xlsx | `position_closer_to_other_section` | 7 | Position closer to section 03 'Titel 03 Dacharbeiten' than to its own section 01 'Titel 01 Stahlbau' |

## Definitions

A finding is a true positive when it highlights a row where reporting an injected error is correct: the error's own row, or a total the error throws off (a wrong net total also breaks the tax and gross checks). Precision at K uses the order a reviewer sees (severity, then position) and divides by the number of findings shown, at most K; it is averaged over documents with findings. Recall in the first 20 (or 50) findings divides the injected errors that the first 20 (or 50) findings in that order match by all injected errors. Like precision at K, it passes over correct risk notes on unplanted rows, which take no place in the list; a wrong risk note keeps its place and matches nothing. Cell localization counts detected errors whose wrong cell is highlighted. See `backend/app/evaluation/scoring.py`.
