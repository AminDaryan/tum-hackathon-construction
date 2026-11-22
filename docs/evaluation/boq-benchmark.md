# Synthetic benchmark report: BoQ variant

Synthetic benchmark: measured on generated data, not real-world performance.

**Before step B2: measured with the checks of the baseline plan only** (first run on 2026-11-20 on B0 and B1 together with step A2 and the GAEB import, with the 15 checks of the baseline plan at that time). The kinds that plan steps B2 and B3 will check show "check not available yet"; rerun the command below and replace this file when a step lands. Compared with the first BoQ report (B1 alone, 14 baseline checks), the harness now maps the STLB-Bau column as a reviewer would, so the import's `domain.standard_text_keys` runs on the 25 bills with keys: it flags 18 planted price and unit errors whose position shares its key with another row, and nothing else. Every other quality number is unchanged (only the timing lines differ), also with the GAEB import's item type names in 19 of the Positionsart columns. Rerun on 2026-11-21 with the finding categories of plan section 5a: the new table "By finding category" counts planted and found errors per category, and every other quality number is unchanged (only the timing lines differ). Rerun again on 2026-11-21 after `main` was merged in: its peer-price check, `statistical.peer_price` (S1 of plan step B3), is registered but opt-in and not in the baseline plan, so this run does not plan it and the kinds expected from it still show "check not available yet" (`--plan-step statistical.peer_price` adds it). Every number is unchanged; only the timing lines and three sentences differ: the one on signal checks (opt-in, not planned in this run), the definition of "check not available yet" (a check this run does not plan, or one planned without a profile setting it needs), and the one that says a finding's category comes from its check and rule.

**Rerun on 2026-11-21 with every check of step B2** (plan sections 5a and 8; 24 checks registered, 23 of them in the baseline plan, `domain.boq_separate_payment` only when a plan names it). The four kinds that waited for B2 are now measured, each found by its expected check with recall 1.000 and cell localization 1.000: `placeholder_price` 10 of 10 by `domain.boq_bid_prices` (`token_price` for 0,01 and `zero_price` for 0,00: one bid price check instead of a `deterministic.price_completeness`, ADR 0010), `code_outside_section` 10 of 10 by `deterministic.hierarchy`, `component_sum_error` 9 of 9 by `deterministic.unit_price_components` and `duplicate_position` 10 of 10 by `deterministic.exact_duplicates`, which now compares positions within a Titel without their OZ; `line_total_slip` stays 10 of 10. Rule findings rose from 133 to 270: 212 on planted rows (were 133) and 58 correct risk notes. The 79 more findings on planted rows: 29 of `deterministic.unit_price_components` (the 9 component errors, and 20 planted errors of seven price and unit kinds on rows with components: they change the unit price but not its components), 10 of `deterministic.hierarchy`, 10 more of `deterministic.exact_duplicates`, 10 of `domain.boq_bid_prices`, 17 lists of `domain.boq_position_types` that name a planted row (a Bedarfsposition that repeats a position with a planted error is one of the rows where the scoring accepts a report, and the high contingency prices are planted into Bedarfspositionen; the list highlights no planted cell, so it localizes none) and 3 of `domain.boq_typos` (near-copies whose changed word is a rare spelling). The 58 risk notes are each a German bill's list of its contingency positions; checked against the generated bill's own item types, every one names only contingency positions ("Risk notes on unplanted rows, checked against the generated bill: 58, all correct"), so there is still no false positive, 0.000 per 1,000 rows. Those findings also raise "Found by any check" for kinds whose expected check comes in B3 (`price_decimal_slip` 2 to 6, `price_digit_swap` 1 to 2, `inconsistent_rate` 4 to 6, `wrong_rate_copied` 2 to 4, `high_contingency_price` 3 to 8, `quantity_decimal_slip` and `quantity_unit_slip` 0 to 6, `price_per_wrong_unit` 2 to 3, `near_duplicate_position` 0 to 3); they stay "check not available yet". Findings per planted error rose from 0.577 to 0.944. By finding category, Error measures 94 of 94 planted errors (`placeholder_price`, `code_outside_section` and `component_sum_error` joined) and Inconsistency 20 of 20 (`duplicate_position` joined `duplicate_row`). Every other quality number is unchanged, also row classification 1.000 with the GAEB position kinds of B2.6 in the 19 Positionsart columns that write the import's names. The timing lines differ: more checks run (0.500 s median per bill, 788 rows per second, 93.3 s for the whole run, was 0.353 s, 1005 and 78.9 s). Run again after the review fixes of step B2 (a bid that offers few of its positions is checked, a contingency list is scored by every position it names, and the wording and typo rules skip a few correct phrasings): every quality number above is the same, and the risk notes are still all correct when every listed position is checked; that run took 0.545 s median per bill, 759 rows per second, 97.0 s.

**Rerun on 2026-11-21 after this branch merged pull request #10's branch** (`37ab12c`: `main` up to `5439d02` and the category fixes; 25 checks registered, 23 of them in the baseline plan; `statistical.peer_price` is opt-in, so this run does not plan it). Against this branch before the merge (`ccb9c84`), every quality number is unchanged. The timing lines differ: 0.508 s median per bill (was 0.545 s), 752 rows per second (was 759), and 97.1 s for the whole run (was 97.0 s). Three sentences came from pull request #10 in that run: no signal check is planned in this run, a kind whose expected checks are not planned in this run shows "check not available yet", and a finding's category is computed from its check and rule. Against pull request #10's branch (`37ab12c`), the numbers that differ are those of step B2 in the paragraph above. Rule findings are 270 (were 133), and the line of 58 correct risk notes is new. Findings per planted error are 0.944 (was 0.577). The four kinds that waited for B2 are measured, each with recall 1.000 and cell localization 1.000 (they showed "check not available yet"). "Found by any check" rose for the nine B3 kinds as listed above. By finding category, Error measures 94 of 94 planted errors (was 65 of 65) and Inconsistency 20 of 20 (was 10 of 10). The timing lines were 0.378 s median per bill, 998 rows per second and 79.5 s there.

**Rerun on 2026-11-21 after the review fixes of that merge and the merge of pull request #10's final head** (`104d0b9`; 25 checks registered, 23 of them in the baseline plan). Against this branch's last report (`c9f534b`, unchanged through `cec8ae4`) every quality number is the same, and only the timing lines (0.638 s median per bill, 644 rows per second and 112.1 s for the whole run; were 0.508 s, 752 and 97.1 s) and the definition of "check not available yet" differ (it now also names, as pull request #10 does, a check that the run plans while the profile lacks a setting the check needs; the `boq` profile here holds the one such setting, so `duplicate_position` stays measured), while against pull request #10's report at `104d0b9` the numbers that differ are still those of step B2 above (270 rule findings for 133, the line of 58 correct risk notes, 0.944 findings per planted error for 0.577, and the four kinds that waited for B2 measured), with its timing lines at 0.428 s, 888 rows per second and 88.6 s.

**Rerun on 2026-11-21 after the merges with `main` at `b92f13d` and `ea41168`** (the tender review and the two price context checks; 30 checks registered, 28 of them in the baseline plan). `domain.boq_typos` is now the tender review's signal check of the same id with B2's matcher, so its 3 findings on near-copies are signals, no longer rule findings: rule findings are 267 (were 270), findings per planted error 0.932 (were 0.944), and `near_duplicate_position` is found by no rule check (was 3 by the typo check; its expected check comes in B3). The six signal checks of the BoQ baseline (the tender review's four and the two price context checks) flag nothing on unplanted rows (the table at the end). Every other quality number is the same; the timing lines differ (0.610 s median per bill, 665 rows per second, 115.2 s for the whole run).

**Rerun on 2026-11-21 with every check on** ([ADR 0010](../decisions/0010-boq-anomaly-detection.md), amendment of 2026-11-21: every validation runs all 35 registered checks; there are no opt-in checks, no `--plan-step` and no way to switch a check off, and the benchmark no longer drops the signal checks from its plan). Rule findings are unchanged (267, still 0 on unplanted rows, 58 correct risk notes). The signal checks now run and give 448 findings (were 0), so findings per planted error rose from 0.932 to 1.372. The nine kinds that waited for B3 are measured: `price_decimal_slip` 9 of 10, `price_digit_swap` 4, `inconsistent_rate` 10, `wrong_rate_copied` 9, `high_contingency_price` 6, `quantity_decimal_slip` 2, `quantity_unit_slip` 3, `price_per_wrong_unit` 10, `wrong_unit` 9, `misplaced_position` 9 and `near_duplicate_position` 10, each localized in its cell (M1 is no longer an expected check; S1 does its comparison). **The cost on clean rows:** 345 signals fall on rows where nothing was planted, 6.9 per 1,000 item rows: 327 of `statistical.peer_price` (6.53 per 1,000) and 18 of `domain.boq_numbering` (0.36); every other signal check flags no unplanted row. These are counted apart from rule findings and are not called false positives (a generated bill can hold a genuinely odd price), but a reviewer sees them. The run is slower: 0.750 s median per bill (was 0.401 s on the same machine), 454 rows per second (was 961), 148.5 s for the whole run (was 84.5 s).

**Rerun on 2026-11-21 with `statistical.peer_price` comparing a row only with its own kind of work** (36 checks registered, every one run). The 327 peer-price signals on unplanted rows came mostly from text peer groups that mixed unlike work (pressure tests of a pipe with laying it, single doors with double doors, scaffold of other load classes): the looser matches outvoted the row's close ones. A higher score threshold does not separate them (63 unplanted rows score 6 or more, while planted errors are found at 3.1 to 3.9). The check now keeps text peers within `text_band` (0.25) of the most similar one, but never fewer than `min_peers` of the closest. Signals on unplanted rows fell from 345 to 124 (`statistical.peer_price` 327 to 106, `domain.boq_numbering` 18 as before), precision from 0.475 to 0.716, and every planted kind is found and localized as before (recall 0.957, the table by error kind is unchanged). On seed 31 (50 bills, the confirmation seed) they fell from 201 to 80 (`statistical.peer_price` 189 to 68), precision 0.524 to 0.734, recall 0.964 unchanged. Timing: 0.576 s median per bill, 613 rows per second, 118.4 s for the whole run.

**F2 at 50 added on 2026-11-21 (plan step B7)**, rerun on `main` at `3ddaa48`: F2 at 50 is now the main score of every benchmark ([definition](README.md#main-score-f2-at-50)). It is 0.894, with a mean precision at 50 of 0.786 and a mean recall at 50 of 0.957 (on `d171553`, before the merges of #57 and #61: 0.901, 0.764 and 0.966). Two changes since the run above move the numbers. `statistical.historical_price` now matches the generated items by wording (#57): it adds 135 signals on unplanted rows (2.697 per 1,000 item rows) and also signals 8 planted kinds, mostly errors other checks find too. `statistical.peer_price`'s new floor (#61) cuts its signals on unplanted rows from 106 to 20, and finds fewer `price_per_wrong_unit` (6 of 10, was 10) and `wrong_rate_copied` (8 of 10, was 9) errors. Other checks, `statistical.historical_price` among them, still find most of those; overall one planted error fewer is found (223 of 234), so recall falls from 0.957 to 0.953. Signals rise from 228 to 312; rule findings are unchanged (267, 0 on unplanted rows).

Synthetic documents only: generated bills with injected errors. No real-world documents were evaluated, so these numbers say nothing about performance on real bills. The values are ratios over this generated set, not probabilities.

Seed `20261120`, profile `boq`, 100 bills of about 80 to 1500 positions, 0 to 8 planted errors per bill, checked with every registered check. Regenerate with `python -m app.evaluation --variant boq --seed 20261120 --documents 100` (see `--help`).

## Bills

Synthetic benchmark: measured on generated data, not real-world performance.

| Metric | Value |
| --- | --- |
| **F2 at 50 (main score)** | **0.894** |
| Precision at 50 (mean) | 0.786 |
| Recall at 50 (mean) | 0.957 |
| Recall | 0.953 |
| Bills | 100 |
| Repeated per building under Lose | 25 |
| With STLB-Bau keys | 25 |
| With unit price components | 25 |
| With a Positionsart column | 38 |
| Of them with the GAEB import's item type names | 19 |
| In English | 25 |
| Data rows | 52934 |
| Item rows | 50058 |
| Planted errors | 234 |
| Rule findings | 267 |
| Signals | 312 |
| Rule findings on unplanted rows (false positives) | 0 |
| False positives per 1,000 rows | 0.000 |
| Risk notes on unplanted rows, checked against the generated bill | 58, all correct |
| Findings per planted error | 1.526 |
| Row classification accuracy | 1.000 |
| Median time per bill (s) | 0.605 |
| Rows per second | 691 |

Timing machine: Darwin arm64, Python 3.13.5; the whole run took 101.8 s.

## By error kind

Synthetic benchmark: measured on generated data, not real-world performance.

| Type | Kind | Planted | Expected check | Found by it | Recall | Cell localized | Found by any check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| logical | `line_total_arithmetic` | 10 | `deterministic.line_total` (line_total_mismatch) | 10 | 1.000 | 1.000 | 10 |
| logical | `subtotal_mismatch` | 10 | `deterministic.subtotal` (subtotal_mismatch) | 10 | 1.000 | 1.000 | 10 |
| logical | `net_total_mismatch` | 10 | `deterministic.grand_total` (grand_total_mismatch) | 10 | 1.000 | 1.000 | 10 |
| logical | `tax_mismatch` | 10 | `deterministic.grand_total` (tax_mismatch) | 10 | 1.000 | 1.000 | 10 |
| unit | `unknown_unit` | 10 | `deterministic.unit_vocabulary` (unknown_unit) | 10 | 1.000 | 1.000 | 10 |
| duplicate | `duplicate_row` | 10 | `deterministic.exact_duplicates` (exact_duplicate) | 10 | 1.000 | 1.000 | 10 |
| structural | `missing_unit_price` | 5 | `deterministic.required_values` (required_value) | 5 | 1.000 | 1.000 | 5 |
| quantity | `invalid_quantity` | 10 | `deterministic.data_type_conformance` (invalid_value, wrong_type) | 10 | 1.000 | 1.000 | 10 |
| price | `price_decimal_slip` | 10 | `statistical.peer_price` | 9 | 0.900 | 1.000 | 10 |
| price | `price_digit_swap` | 10 | `statistical.peer_price`; `statistical.rate_consistency` | 4 | 0.400 | 1.000 | 5 |
| price | `inconsistent_rate` | 10 | `statistical.rate_consistency` | 10 | 1.000 | 1.000 | 10 |
| price | `wrong_rate_copied` | 10 | `statistical.peer_price` | 8 | 0.800 | 1.000 | 9 |
| price | `placeholder_price` | 10 | `domain.boq_bid_prices` (token_price, zero_price) | 10 | 1.000 | 1.000 | 10 |
| price | `high_contingency_price` | 10 | `statistical.peer_price` | 7 | 0.700 | 1.000 | 10 |
| quantity | `quantity_decimal_slip` | 10 | `statistical.quantity_factor` | 2 | 0.200 | 1.000 | 8 |
| quantity | `quantity_unit_slip` | 10 | `statistical.quantity_factor` | 3 | 0.300 | 1.000 | 10 |
| unit | `price_per_wrong_unit` | 10 | `statistical.peer_price` | 6 | 0.600 | 1.000 | 9 |
| unit | `wrong_unit` | 10 | `semantic.unit_fit` | 9 | 0.900 | 1.000 | 9 |
| semantic | `misplaced_position` | 10 | `semantic.section_fit` | 9 | 0.900 | 1.000 | 9 |
| structural | `code_outside_section` | 10 | `deterministic.hierarchy` (item_outside_section) | 10 | 1.000 | 1.000 | 10 |
| logical | `line_total_slip` | 10 | `deterministic.line_total` (line_total_mismatch) | 10 | 1.000 | 1.000 | 10 |
| logical | `component_sum_error` | 9 | `deterministic.unit_price_components` (component_sum_mismatch) | 9 | 1.000 | 1.000 | 9 |
| duplicate | `duplicate_position` | 10 | `deterministic.exact_duplicates` (exact_duplicate) | 10 | 1.000 | 1.000 | 10 |
| duplicate | `near_duplicate_position` | 10 | `machine_learning.near_duplicates` | 10 | 1.000 | 1.000 | 10 |

## By finding category

Synthetic benchmark: measured on generated data, not real-world performance.

Each kind counts under the finding category its expected check gives its findings. A planted error is found with its category when a matching finding of any check carries that category. Kinds whose expected check is not available yet are listed on a line of their own, marked "check not available yet": their errors are planted but not measured.

| Category | Kinds | Planted | Found with this category |
| --- | --- | --- | --- |
| Error | `line_total_arithmetic`, `subtotal_mismatch`, `net_total_mismatch`, `tax_mismatch`, `missing_unit_price`, `invalid_quantity`, `placeholder_price`, `code_outside_section`, `line_total_slip`, `component_sum_error` | 94 | 94 |
| Inconsistency | `duplicate_row`, `inconsistent_rate`, `quantity_decimal_slip`, `quantity_unit_slip`, `wrong_unit`, `misplaced_position`, `duplicate_position`, `near_duplicate_position` | 80 | 63 |
| Omission | none planted | 0 |  |
| Ambiguity | none planted | 0 |  |
| Risk | `price_decimal_slip`, `price_digit_swap`, `wrong_rate_copied`, `high_contingency_price`, `price_per_wrong_unit` | 50 | 40 |
| Change order opportunity | none planted | 0 |  |
| Reading the file | `unknown_unit` | 10 | 10 |

## By check and kind

Synthetic benchmark: measured on generated data, not real-world performance.

Every check that flagged a planted error, expected or not.

| Check | Kind | Planted | Flagged | Recall | Cell localized |
| --- | --- | --- | --- | --- | --- |
| `deterministic.data_type_conformance` | `invalid_quantity` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.exact_duplicates` | `duplicate_position` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.exact_duplicates` | `duplicate_row` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.field_constraints` | `duplicate_row` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.grand_total` | `net_total_mismatch` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.grand_total` | `subtotal_mismatch` | 10 | 2 | 0.200 | 0.000 |
| `deterministic.grand_total` | `tax_mismatch` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.hierarchy` | `code_outside_section` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.line_total` | `line_total_arithmetic` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.line_total` | `line_total_slip` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.required_values` | `missing_unit_price` | 5 | 5 | 1.000 | 1.000 |
| `deterministic.subtotal` | `subtotal_mismatch` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.unit_compatibility` | `wrong_unit` | 10 | 1 | 0.100 | 1.000 |
| `deterministic.unit_price_components` | `component_sum_error` | 9 | 9 | 1.000 | 1.000 |
| `deterministic.unit_price_components` | `high_contingency_price` | 10 | 2 | 0.200 | 1.000 |
| `deterministic.unit_price_components` | `inconsistent_rate` | 10 | 4 | 0.400 | 1.000 |
| `deterministic.unit_price_components` | `placeholder_price` | 10 | 4 | 0.400 | 1.000 |
| `deterministic.unit_price_components` | `price_decimal_slip` | 10 | 5 | 0.500 | 1.000 |
| `deterministic.unit_price_components` | `price_digit_swap` | 10 | 1 | 0.100 | 1.000 |
| `deterministic.unit_price_components` | `price_per_wrong_unit` | 10 | 2 | 0.200 | 1.000 |
| `deterministic.unit_price_components` | `wrong_rate_copied` | 10 | 2 | 0.200 | 1.000 |
| `deterministic.unit_vocabulary` | `unknown_unit` | 10 | 10 | 1.000 | 1.000 |
| `domain.boq_bid_prices` | `placeholder_price` | 10 | 10 | 1.000 | 1.000 |
| `domain.boq_position_types` | `high_contingency_price` | 10 | 8 | 0.800 | 0.000 |
| `domain.boq_position_types` | `inconsistent_rate` | 10 | 3 | 0.300 | 0.000 |
| `domain.boq_position_types` | `price_per_wrong_unit` | 10 | 1 | 0.100 | 0.000 |
| `domain.boq_position_types` | `quantity_decimal_slip` | 10 | 6 | 0.600 | 0.000 |
| `domain.boq_position_types` | `quantity_unit_slip` | 10 | 6 | 0.600 | 0.000 |
| `domain.boq_typos` | `near_duplicate_position` | 10 | 2 | 0.200 | 1.000 |
| `domain.standard_text_keys` | `high_contingency_price` | 10 | 3 | 0.300 | 1.000 |
| `domain.standard_text_keys` | `inconsistent_rate` | 10 | 4 | 0.400 | 1.000 |
| `domain.standard_text_keys` | `placeholder_price` | 10 | 1 | 0.100 | 1.000 |
| `domain.standard_text_keys` | `price_decimal_slip` | 10 | 2 | 0.200 | 1.000 |
| `domain.standard_text_keys` | `price_digit_swap` | 10 | 1 | 0.100 | 1.000 |
| `domain.standard_text_keys` | `price_per_wrong_unit` | 10 | 2 | 0.200 | 1.000 |
| `domain.standard_text_keys` | `wrong_rate_copied` | 10 | 2 | 0.200 | 1.000 |
| `domain.standard_text_keys` | `wrong_unit` | 10 | 3 | 0.300 | 1.000 |
| `machine_learning.near_duplicates` | `near_duplicate_position` | 10 | 10 | 1.000 | 1.000 |
| `semantic.section_fit` | `misplaced_position` | 10 | 9 | 0.900 | 1.000 |
| `semantic.unit_fit` | `wrong_unit` | 10 | 9 | 0.900 | 1.000 |
| `statistical.historical_price` | `inconsistent_rate` | 10 | 2 | 0.200 | 1.000 |
| `statistical.historical_price` | `placeholder_price` | 10 | 2 | 0.200 | 1.000 |
| `statistical.historical_price` | `price_decimal_slip` | 10 | 7 | 0.700 | 1.000 |
| `statistical.historical_price` | `price_digit_swap` | 10 | 2 | 0.200 | 1.000 |
| `statistical.historical_price` | `price_per_wrong_unit` | 10 | 6 | 0.600 | 1.000 |
| `statistical.historical_price` | `quantity_decimal_slip` | 10 | 7 | 0.700 | 1.000 |
| `statistical.historical_price` | `quantity_unit_slip` | 10 | 9 | 0.900 | 1.000 |
| `statistical.historical_price` | `wrong_rate_copied` | 10 | 7 | 0.700 | 1.000 |
| `statistical.peer_price` | `high_contingency_price` | 10 | 7 | 0.700 | 1.000 |
| `statistical.peer_price` | `placeholder_price` | 10 | 3 | 0.300 | 1.000 |
| `statistical.peer_price` | `price_decimal_slip` | 10 | 9 | 0.900 | 1.000 |
| `statistical.peer_price` | `price_digit_swap` | 10 | 2 | 0.200 | 1.000 |
| `statistical.peer_price` | `price_per_wrong_unit` | 10 | 6 | 0.600 | 1.000 |
| `statistical.peer_price` | `wrong_rate_copied` | 10 | 8 | 0.800 | 1.000 |
| `statistical.quantity_factor` | `quantity_decimal_slip` | 10 | 2 | 0.200 | 1.000 |
| `statistical.quantity_factor` | `quantity_unit_slip` | 10 | 3 | 0.300 | 1.000 |
| `statistical.rate_consistency` | `high_contingency_price` | 10 | 8 | 0.800 | 1.000 |
| `statistical.rate_consistency` | `inconsistent_rate` | 10 | 10 | 1.000 | 1.000 |
| `statistical.rate_consistency` | `price_decimal_slip` | 10 | 2 | 0.200 | 1.000 |
| `statistical.rate_consistency` | `price_digit_swap` | 10 | 3 | 0.300 | 1.000 |
| `statistical.rate_consistency` | `price_per_wrong_unit` | 10 | 2 | 0.200 | 1.000 |
| `statistical.rate_consistency` | `wrong_rate_copied` | 10 | 2 | 0.200 | 1.000 |

## Signals on unplanted rows

Synthetic benchmark: measured on generated data, not real-world performance.

Signals are findings of statistical, machine-learning, semantic and research checks. On rows where nothing was planted they are counted here, apart from rule findings, and not called false positives: a generated bill can hold a genuinely odd price by chance.

| Check | Signals on unplanted rows | Per 1,000 item rows |
| --- | --- | --- |
| `domain.boq_contradictions` | 0 | 0.000 |
| `domain.boq_description_clarity` | 0 | 0.000 |
| `domain.boq_numbering` | 18 | 0.360 |
| `domain.boq_typos` | 0 | 0.000 |
| `machine_learning.near_duplicates` | 0 | 0.000 |
| `semantic.section_fit` | 0 | 0.000 |
| `semantic.unit_fit` | 0 | 0.000 |
| `statistical.historical_price` | 135 | 2.697 |
| `statistical.open_price_reference` | 0 | 0.000 |
| `statistical.peer_price` | 20 | 0.400 |
| `statistical.quantity_factor` | 0 | 0.000 |
| `statistical.rate_consistency` | 0 | 0.000 |

### The 10 strongest, for inspection

| Bill | Check | Rule | Severity | Rows | Title |
| --- | --- | --- | --- | --- | --- |
| boq-en-008.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 29 | Unit price 6.65 far below comparable positions (median 38.1) |
| boq-de-054.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 30 | Unit price 43.81 far above comparable positions (median 7.76) |
| boq-de-054.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 31 | Unit price 43.81 far above comparable positions (median 7.76) |
| boq-en-008.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 30 | Unit price 7.45 far below comparable positions (median 38.1) |
| boq-de-036.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 55 | Unit price 56.75 far above comparable positions (median 8.57) |
| boq-de-009.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 136 | Unit price 417.68 far below comparable positions (median 1484.58) |
| boq-de-009.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 443 | Unit price 417.68 far below comparable positions (median 1484.58) |
| boq-de-047.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 257 | Unit price 4281.71 far above comparable positions (median 1320.28) |
| boq-de-082.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 97 | Unit price 389.97 far below comparable positions (median 1211.94) |
| boq-de-082.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 366 | Unit price 389.97 far below comparable positions (median 1211.94) |

## Rule findings on unplanted rows (false positives)

Synthetic benchmark: measured on generated data, not real-world performance.

Risk notes on unplanted rows, checked against the generated bill: 58, all correct. A list of the bill's contingency and hourly positions (`domain.boq_position_types`) is a correct note when every row it names is such a position of the generated bill (the generator's own item types); it claims no error, so it is counted here and not as a false positive. A list that names any other row is a false positive below.

None.

## Missed by an available expected check

Synthetic benchmark: measured on generated data, not real-world performance.

| Bill | Kind | Row | Change | Rules found |
| --- | --- | --- | --- | --- |
| boq-en-004.xlsx | `price_per_wrong_unit` | 108 | unit price 159.88 per m3 written as 63.95, the price per m2 of a 0.40 m thick part | none |
| boq-en-008.xlsx | `price_digit_swap` | 146 | unit price 164.97 written as 164.79 | none |
| boq-de-009.xlsx | `quantity_unit_slip` | 433 | quantity 147.15 m entered in mm as 147150.00 | historical_quantity_outlier |
| boq-de-009.xlsx | `misplaced_position` | 578 | position 02.05.0270 moved into Titel 02.10 as 02.10.0300 | none |
| boq-en-021.xlsx | `price_digit_swap` | 77 | unit price 39.68 written as 39.86 | none |
| boq-de-022.xlsx | `quantity_unit_slip` | 452 | quantity 183.90 m entered in mm as 183900.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-022.xlsx | `quantity_decimal_slip` | 436 | quantity 267.67 written as 26767.00 (× 100) | contingency_and_hourly, historical_quantity_outlier |
| boq-de-030.xlsx | `quantity_decimal_slip` | 288 | quantity 43.15 written as 0.04315 (× 0.001) | contingency_and_hourly, historical_quantity_outlier |
| boq-de-045.xlsx | `high_contingency_price` | 11 | unit price 20.56 of a Bedarfsposition without total written as 44.19 (2.1494 times its normal position 01.0050) | component_sum_mismatch, contingency_and_hourly, identical_positions_price_differs |
| boq-de-045.xlsx | `price_decimal_slip` | 9 | unit price 15.31 written as 153.10 (× 10) | component_sum_mismatch, historical_price_outlier |
| boq-de-047.xlsx | `quantity_decimal_slip` | 215 | quantity 11 written as 1100 (× 100) | contingency_and_hourly, historical_quantity_outlier |
| boq-de-059.xlsx | `quantity_unit_slip` | 169 | quantity 18.84 m entered in mm as 18840.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-061.xlsx | `high_contingency_price` | 169 | unit price 1086.13 of a Bedarfsposition without total written as 2969.37 (2.7339 times its normal position 05.0100) | contingency_and_hourly, identical_positions_price_differs |
| boq-de-062.xlsx | `price_digit_swap` | 754 | unit price 12.43 written as 21.43 | none |
| boq-de-065.xlsx | `quantity_unit_slip` | 63 | quantity 32.40 m entered in mm as 32400.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-065.xlsx | `quantity_decimal_slip` | 644 | quantity 1 written as 100 (× 100) | none |
| boq-de-065.xlsx | `price_digit_swap` | 70 | unit price 56.17 written as 56.71 | none |
| boq-en-066.xlsx | `wrong_rate_copied` | 33 | unit price 231.11 replaced by 78.52, the unit price of position 1.5 | none |
| boq-de-067.xlsx | `price_per_wrong_unit` | 56 | unit price 183.89 per m3 written as 73.56, the price per m2 of a 0.40 m thick part | historical_price_outlier |
| boq-de-069.xlsx | `quantity_decimal_slip` | 54 | quantity 137.32 written as 13732.00 (× 100) | contingency_and_hourly, historical_quantity_outlier |
| boq-de-072.xlsx | `high_contingency_price` | 274 | unit price 5.63 of a Bedarfsposition without total written as 15.16 (2.6923 times its normal position 01.05.0100) | contingency_and_hourly, identical_positions_price_differs, same_key_unit_prices |
| boq-de-072.xlsx | `price_per_wrong_unit` | 28 | unit price 170.30 per m3 written as 68.12, the price per m2 of a 0.40 m thick part | contingency_and_hourly, identical_positions_price_differs, same_key_unit_prices |
| boq-de-072.xlsx | `quantity_decimal_slip` | 102 | quantity 184.19 written as 18.419 (× 0.1) | none |
| boq-en-074.xlsx | `wrong_unit` | 31 | unit m3 written as m2, quantity and unit price kept | none |
| boq-de-076.xlsx | `quantity_unit_slip` | 112 | quantity 133.75 m entered in cm as 13375.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-085.xlsx | `price_digit_swap` | 281 | unit price 1.51 written as 1.15 | component_sum_mismatch |
| boq-de-085.xlsx | `price_per_wrong_unit` | 121 | unit price 193.26 per m3 written as 77.30, the price per m2 of a 0.40 m thick part | component_sum_mismatch, historical_price_outlier |
| boq-de-086.xlsx | `quantity_decimal_slip` | 233 | quantity 72.72 written as 0.7272 (× 0.01) | contingency_and_hourly, historical_quantity_outlier |
| boq-de-086.xlsx | `quantity_unit_slip` | 97 | quantity 134.66 m entered in cm as 13466.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-095.xlsx | `quantity_decimal_slip` | 243 | quantity 124.55 written as 1.2455 (× 0.01) | contingency_and_hourly |

## Definitions

F2 at 50, the main score, weighs recall four times as much as precision (F-beta, beta = 2) over the first 50 findings of each bill in the issue register's order, every finding counted, signals included, averaged over the bills with planted errors (`f_beta` and the metric definitions in `backend/app/evaluation/scoring.py`). A planted error is found by a check when a finding of that check highlights a row where reporting the error is correct: its own row, the totals it throws off, and for a changed price or quantity the position's identical copies (a comparison of two copies cannot tell which one is wrong). Recall is found errors over planted errors of the kind; cell localization is found errors whose wrong cell the check highlights over found errors. The expected checks are in `backend/app/evaluation/expectations.py`; a kind shows "check not available yet" instead of a recall when none of its expected checks is available in this run: not built yet, or built while the profile lacks a setting the check needs (the `setting` of its entry in that file); every run plans every registered check. The expected finding category of each kind (`EXPECTED_CATEGORY`, same file) is the category its expected check gives its findings; a finding's category is computed from its check and rule (`backend/app/models/finding_category.py`), and findings about reading the file have none ("Reading the file"). See `backend/app/evaluation/boq_report.py`.
