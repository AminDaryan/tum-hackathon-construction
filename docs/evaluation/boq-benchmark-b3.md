# Synthetic benchmark report: BoQ variant

Synthetic benchmark: measured on generated data, not real-world performance.

**Superseded:** every validation now runs every registered check, B2's and B3's together; [boq-benchmark.md](boq-benchmark.md) is the current measurement of this corpus. This page is kept as the record of B3 before B2 was merged.

**Measured with the baseline plan and the six opt-in signal checks of plan step B3** (2026-11-21): `statistical.peer_price`, `statistical.rate_consistency`, `statistical.quantity_factor`, `semantic.unit_fit`, `semantic.section_fit` and `machine_learning.near_duplicates`, each added with `--plan-step`. The rule checks of step B2 are not built yet, so their kinds show "check not available yet".

Synthetic documents only: generated bills with injected errors. No real-world documents were evaluated, so these numbers say nothing about performance on real bills. The values are ratios over this generated set, not probabilities.

Seed `20261120`, profile `boq`, 100 bills of about 80 to 1500 positions, 0 to 8 planted errors per bill, checked with the baseline plan and `statistical.peer_price`, `statistical.rate_consistency`, `statistical.quantity_factor`, `semantic.unit_fit`, `semantic.section_fit`, `machine_learning.near_duplicates`. Regenerate with `python -m app.evaluation --variant boq --seed 20261120 --documents 100` (see `--help`).

## Bills

Synthetic benchmark: measured on generated data, not real-world performance.

| Metric | Value |
| --- | --- |
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
| Rule findings | 133 |
| Signals | 428 |
| Rule findings on unplanted rows (false positives) | 0 |
| False positives per 1,000 rows | 0.000 |
| Findings per planted error | 1.009 |
| Row classification accuracy | 1.000 |
| Median time per bill (s) | 0.446 |
| Rows per second | 899 |

Timing machine: Darwin arm64, Python 3.13.5; the whole run took 86.8 s.

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
| price | `price_decimal_slip` | 10 | `statistical.peer_price` | 9 | 0.900 | 1.000 | 9 |
| price | `price_digit_swap` | 10 | `statistical.peer_price`; `statistical.rate_consistency` | 4 | 0.400 | 1.000 | 4 |
| price | `inconsistent_rate` | 10 | `statistical.rate_consistency` | 10 | 1.000 | 1.000 | 10 |
| price | `wrong_rate_copied` | 10 | `statistical.peer_price` | 9 | 0.900 | 1.000 | 10 |
| price | `placeholder_price` | 10 | `deterministic.price_completeness` (token_price, zero_price), B2 | check not available yet |  |  | 4 |
| price | `high_contingency_price` | 10 | `statistical.peer_price` | 6 | 0.600 | 1.000 | 10 |
| quantity | `quantity_decimal_slip` | 10 | `statistical.quantity_factor` | 2 | 0.200 | 1.000 | 2 |
| quantity | `quantity_unit_slip` | 10 | `statistical.quantity_factor` | 3 | 0.300 | 1.000 | 3 |
| unit | `price_per_wrong_unit` | 10 | `statistical.peer_price` | 10 | 1.000 | 1.000 | 10 |
| unit | `wrong_unit` | 10 | `semantic.unit_fit` | 9 | 0.900 | 1.000 | 9 |
| semantic | `misplaced_position` | 10 | `semantic.section_fit` | 9 | 0.900 | 1.000 | 9 |
| structural | `code_outside_section` | 10 | `deterministic.hierarchy` (item_outside_section), B2 | check not available yet |  |  | 0 |
| logical | `line_total_slip` | 10 | `deterministic.line_total` (line_total_mismatch) | 10 | 1.000 | 1.000 | 10 |
| logical | `component_sum_error` | 9 | `deterministic.unit_price_components`, B2 | check not available yet |  |  | 0 |
| duplicate | `duplicate_position` | 10 | `deterministic.exact_duplicates` (exact_duplicate), B2 | check not available yet |  |  | 0 |
| duplicate | `near_duplicate_position` | 10 | `machine_learning.near_duplicates` | 10 | 1.000 | 1.000 | 10 |

## By finding category

Synthetic benchmark: measured on generated data, not real-world performance.

Each kind counts under the finding category its expected check gives its findings. A planted error is found with its category when a matching finding of any check carries that category. Kinds whose expected check is not available yet are listed on a line of their own, marked "check not available yet": their errors are planted but not measured.

| Category | Kinds | Planted | Found with this category |
| --- | --- | --- | --- |
| Error | `line_total_arithmetic`, `subtotal_mismatch`, `net_total_mismatch`, `tax_mismatch`, `missing_unit_price`, `invalid_quantity`, `line_total_slip` | 65 | 65 |
| Error | `placeholder_price`, `code_outside_section`, `component_sum_error` | 29 | check not available yet |
| Inconsistency | `duplicate_row`, `inconsistent_rate`, `quantity_decimal_slip`, `quantity_unit_slip`, `wrong_unit`, `misplaced_position`, `near_duplicate_position` | 70 | 53 |
| Inconsistency | `duplicate_position` | 10 | check not available yet |
| Omission | none planted | 0 |  |
| Ambiguity | none planted | 0 |  |
| Risk | `price_decimal_slip`, `price_digit_swap`, `wrong_rate_copied`, `high_contingency_price`, `price_per_wrong_unit` | 50 | 37 |
| Change order opportunity | none planted | 0 |  |
| Reading the file | `unknown_unit` | 10 | 10 |

## By check and kind

Synthetic benchmark: measured on generated data, not real-world performance.

Every check that flagged a planted error, expected or not.

| Check | Kind | Planted | Flagged | Recall | Cell localized |
| --- | --- | --- | --- | --- | --- |
| `deterministic.data_type_conformance` | `invalid_quantity` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.exact_duplicates` | `duplicate_row` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.field_constraints` | `duplicate_row` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.grand_total` | `net_total_mismatch` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.grand_total` | `subtotal_mismatch` | 10 | 2 | 0.200 | 0.000 |
| `deterministic.grand_total` | `tax_mismatch` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.line_total` | `line_total_arithmetic` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.line_total` | `line_total_slip` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.required_values` | `missing_unit_price` | 5 | 5 | 1.000 | 1.000 |
| `deterministic.subtotal` | `subtotal_mismatch` | 10 | 10 | 1.000 | 1.000 |
| `deterministic.unit_compatibility` | `wrong_unit` | 10 | 1 | 0.100 | 1.000 |
| `deterministic.unit_vocabulary` | `unknown_unit` | 10 | 10 | 1.000 | 1.000 |
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
| `statistical.peer_price` | `high_contingency_price` | 10 | 6 | 0.600 | 1.000 |
| `statistical.peer_price` | `inconsistent_rate` | 10 | 1 | 0.100 | 1.000 |
| `statistical.peer_price` | `placeholder_price` | 10 | 3 | 0.300 | 1.000 |
| `statistical.peer_price` | `price_decimal_slip` | 10 | 9 | 0.900 | 1.000 |
| `statistical.peer_price` | `price_digit_swap` | 10 | 3 | 0.300 | 1.000 |
| `statistical.peer_price` | `price_per_wrong_unit` | 10 | 10 | 1.000 | 1.000 |
| `statistical.peer_price` | `wrong_rate_copied` | 10 | 9 | 0.900 | 1.000 |
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
| `domain.boq_numbering` | 0 | 0.000 |
| `domain.boq_typos` | 0 | 0.000 |
| `machine_learning.near_duplicates` | 0 | 0.000 |
| `semantic.section_fit` | 0 | 0.000 |
| `semantic.unit_fit` | 0 | 0.000 |
| `statistical.historical_price` | 0 | 0.000 |
| `statistical.open_price_reference` | 0 | 0.000 |
| `statistical.peer_price` | 327 | 6.532 |
| `statistical.quantity_factor` | 0 | 0.000 |
| `statistical.rate_consistency` | 0 | 0.000 |

### The 10 strongest, for inspection

| Bill | Check | Rule | Severity | Rows | Title |
| --- | --- | --- | --- | --- | --- |
| boq-de-099.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 95 | Unit price 6.77 far below comparable positions (median 48.10) |
| boq-en-032.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 122 | Unit price 6.36 far below comparable positions (median 43.0) |
| boq-de-036.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 55 | Unit price 56.75 far above comparable positions (median 8.53) |
| boq-de-010.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 151 | Unit price 6.12 far below comparable positions (median 40.91) |
| boq-de-082.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 46 | Unit price 44 far above comparable positions (median 6.78) |
| boq-de-082.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 314 | Unit price 44 far above comparable positions (median 6.78) |
| boq-en-032.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 123 | Unit price 6.7 far below comparable positions (median 43.0) |
| boq-de-015.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 35 | Unit price 5.64 far below comparable positions (median 33.47) |
| boq-de-017.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 100 | Unit price 6.28 far below comparable positions (median 36.72) |
| boq-de-094.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 30 | Unit price 6.89 far below comparable positions (median 39.66) |

## Rule findings on unplanted rows (false positives)

Synthetic benchmark: measured on generated data, not real-world performance.

None.

## Missed by an available expected check

Synthetic benchmark: measured on generated data, not real-world performance.

| Bill | Kind | Row | Change | Rules found |
| --- | --- | --- | --- | --- |
| boq-de-003.xlsx | `high_contingency_price` | 94 | unit price 2.21 of a Bedarfsposition without total written as 5.17 (2.3409 times its normal position 01.05.0070) | identical_positions_price_differs |
| boq-en-008.xlsx | `price_digit_swap` | 146 | unit price 164.97 written as 164.79 | none |
| boq-de-009.xlsx | `quantity_unit_slip` | 433 | quantity 147.15 m entered in mm as 147150.00 | none |
| boq-de-009.xlsx | `misplaced_position` | 578 | position 02.05.0270 moved into Titel 02.10 as 02.10.0300 | none |
| boq-en-021.xlsx | `price_digit_swap` | 77 | unit price 39.68 written as 39.86 | none |
| boq-de-022.xlsx | `quantity_unit_slip` | 452 | quantity 183.90 m entered in mm as 183900.00 | none |
| boq-de-022.xlsx | `quantity_decimal_slip` | 436 | quantity 267.67 written as 26767.00 (× 100) | none |
| boq-de-030.xlsx | `quantity_decimal_slip` | 288 | quantity 43.15 written as 0.04315 (× 0.001) | none |
| boq-de-045.xlsx | `high_contingency_price` | 11 | unit price 20.56 of a Bedarfsposition without total written as 44.19 (2.1494 times its normal position 01.0050) | identical_positions_price_differs |
| boq-de-045.xlsx | `price_decimal_slip` | 9 | unit price 15.31 written as 153.10 (× 10) | none |
| boq-de-047.xlsx | `quantity_decimal_slip` | 215 | quantity 11 written as 1100 (× 100) | none |
| boq-de-059.xlsx | `quantity_unit_slip` | 169 | quantity 18.84 m entered in mm as 18840.00 | none |
| boq-de-061.xlsx | `high_contingency_price` | 169 | unit price 1086.13 of a Bedarfsposition without total written as 2969.37 (2.7339 times its normal position 05.0100) | identical_positions_price_differs |
| boq-de-062.xlsx | `price_digit_swap` | 754 | unit price 12.43 written as 21.43 | none |
| boq-de-065.xlsx | `quantity_unit_slip` | 63 | quantity 32.40 m entered in mm as 32400.00 | none |
| boq-de-065.xlsx | `quantity_decimal_slip` | 644 | quantity 1 written as 100 (× 100) | none |
| boq-de-065.xlsx | `price_digit_swap` | 70 | unit price 56.17 written as 56.71 | none |
| boq-de-069.xlsx | `quantity_decimal_slip` | 54 | quantity 137.32 written as 13732.00 (× 100) | none |
| boq-de-072.xlsx | `high_contingency_price` | 274 | unit price 5.63 of a Bedarfsposition without total written as 15.16 (2.6923 times its normal position 01.05.0100) | identical_positions_price_differs, same_key_unit_prices |
| boq-de-072.xlsx | `quantity_decimal_slip` | 102 | quantity 184.19 written as 18.419 (× 0.1) | none |
| boq-en-074.xlsx | `wrong_unit` | 31 | unit m3 written as m2, quantity and unit price kept | none |
| boq-de-076.xlsx | `quantity_unit_slip` | 112 | quantity 133.75 m entered in cm as 13375.00 | none |
| boq-de-085.xlsx | `price_digit_swap` | 281 | unit price 1.51 written as 1.15 | none |
| boq-de-086.xlsx | `quantity_decimal_slip` | 233 | quantity 72.72 written as 0.7272 (× 0.01) | none |
| boq-de-086.xlsx | `quantity_unit_slip` | 97 | quantity 134.66 m entered in cm as 13466.00 | none |
| boq-de-095.xlsx | `quantity_decimal_slip` | 243 | quantity 124.55 written as 1.2455 (× 0.01) | none |
| boq-de-095.xlsx | `quantity_unit_slip` | 270 | quantity 36.78 m entered in cm as 3678.00 | none |
| boq-de-096.xlsx | `price_digit_swap` | 576 | unit price 74.11 written as 47.11 | none |
| boq-de-098.xlsx | `wrong_rate_copied` | 229 | unit price 7.16 replaced by 4.23, the unit price of position 01.01.0140 | identical_positions_price_differs |

## Definitions

A planted error is found by a check when a finding of that check highlights a row where reporting the error is correct: its own row, the totals it throws off, and for a changed price or quantity the position's identical copies (a comparison of two copies cannot tell which one is wrong). Recall is found errors over planted errors of the kind; cell localization is found errors whose wrong cell the check highlights over found errors. The expected checks are in `backend/app/evaluation/expectations.py`; a kind shows "check not available yet" instead of a recall when none of its expected checks is available in this run: not planned (not built yet, or opt-in and not added with --plan-step), or planned while the profile lacks a setting the check needs (B2 makes deterministic.exact_duplicates ignore the item code in the boq profile, which --plan-step cannot add). The expected finding category of each kind (`EXPECTED_CATEGORY`, same file) is the category its expected check gives its findings; a finding's category is computed from its check and rule (`backend/app/models/finding_category.py`), and findings about reading the file have none ("Reading the file"). See `backend/app/evaluation/boq_report.py`.
