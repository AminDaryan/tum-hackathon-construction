# Synthetic benchmark report: BoQ variant, every check (plan step B7)

Synthetic benchmark: measured on generated data, not real-world performance.

**F2 at 50 (main score): 0.901 on the fresh seed `20261121`, 0.894 on `20261120`**, with every
registered check running, as every validation does (ADR 0010). On the 26-fault answer key: 0.760
(0.719 after the clean-original discount). Definition: [README.md](README.md#main-score-f2-at-50).

**Plan step B7's measurement** (2026-11-21, `main` at `3ddaa48`). Each check's value is measured
by leaving it out and validating every bill again (leave-one-out ablation), and our findings are
compared with status-quo reading orders on the same review budget. The main run uses a freshly
generated seed, `20261121` (`statistical.peer_price` was tuned against `20261120`); seed
`20261120` is shown beside it for continuity. The full report of seed `20261121` follows the
summary.

## Summary

Synthetic benchmark: measured on generated data, not real-world performance.

| Seed | **F2 at 50** | Precision at 50 (mean) | Recall at 50 (mean) | Planted errors | Found by any check | Recall | Findings | Signals on unplanted rows | Rule findings on unplanted rows |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 20261121 | **0.901** | 0.814 | 0.975 | 266 | 260 | 0.977 | 616 | 162 | 0 |
| 20261120 | **0.894** | 0.786 | 0.957 | 234 | 223 | 0.953 | 579 | 173 | 0 |

### Leave-one-out ablation

Synthetic benchmark: measured on generated data, not real-world performance.

What each check adds, measured by validating every bill again without it, per seed (`20261121`
/ `20261120`): the F2 at 50 of the full run minus the run without it, the planted errors no
finding matches any more without it, and the findings on unplanted rows it adds. Sorted by the
F2 it adds on `20261121`.

| Check | F2 at 50 it adds | Lost without it | Signals on unplanted rows it adds | Rule findings on unplanted rows it adds |
| --- | --- | --- | --- | --- |
| `deterministic.line_total` | +0.061 / +0.074 | 22 / 20 | 0 / 0 | 0 / 0 |
| `deterministic.grand_total` | +0.058 / +0.066 | 22 / 20 | 0 / 0 | 0 / 0 |
| `statistical.peer_price` | +0.054 / +0.016 | 13 / 6 | 22 / 20 | 0 / 0 |
| `deterministic.subtotal` | +0.046 / +0.025 | 9 / 8 | 0 / 0 | 0 / 0 |
| `deterministic.exact_duplicates` | +0.041 / +0.037 | 11 / 10 | 0 / 0 | 0 / 0 |
| `deterministic.data_type_conformance` | +0.039 / +0.034 | 11 / 10 | 0 / 0 | 0 / 0 |
| `deterministic.unit_price_components` | +0.037 / +0.066 | 14 / 10 | 0 / 0 | 0 / 0 |
| `semantic.section_fit` | +0.033 / +0.041 | 10 / 9 | 0 / 0 | 0 / 0 |
| `machine_learning.near_duplicates` | +0.028 / +0.026 | 10 / 8 | 0 / 0 | 0 / 0 |
| `deterministic.hierarchy` | +0.026 / +0.031 | 9 / 10 | 0 / 0 | 0 / 0 |
| `deterministic.required_values` | +0.024 / +0.012 | 8 / 5 | 0 / 0 | 0 / 0 |
| `deterministic.unit_vocabulary` | +0.019 / +0.045 | 11 / 10 | 0 / 0 | 0 / 0 |
| `statistical.quantity_factor` | +0.019 / +0.000 | 3 / 0 | 0 / 0 | 0 / 0 |
| `statistical.rate_consistency` | +0.016 / +0.015 | 6 / 4 | 0 / 0 | 0 / 0 |
| `domain.boq_bid_prices` | +0.015 / +0.011 | 2 / 4 | 0 / 0 | 0 / 0 |
| `semantic.unit_fit` | +0.010 / +0.025 | 6 / 5 | 0 / 0 | 0 / 0 |
| `domain.boq_position_types` | +0.006 / +0.009 | 2 / 2 | 0 / 0 | 0 / 0 |
| `domain.standard_text_keys` | +0.003 / +0.001 | 1 / 0 | 0 / 0 | 0 / 0 |
| `deterministic.field_constraints` | +0.001 / +0.002 | 0 / 0 | 0 / 0 | 0 / 0 |
| `deterministic.unit_compatibility` | +0.001 / +0.000 | 0 / 0 | 0 / 0 | 0 / 0 |
| `domain.boq_typos` | +0.000 / +0.000 | 0 / 0 | 0 / 0 | 0 / 0 |
| `domain.boq_numbering` | -0.010 / -0.012 | 0 / 0 | 19 / 18 | 0 / 0 |
| `statistical.historical_price` | -0.050 / -0.037 | 4 / 2 | 121 / 135 | 0 / 0 |

- **Every other check that finds planted errors raises F2 at 50.** No error is gained by leaving
  any check out.
- **Two checks lower it.** `statistical.historical_price` (−0.050 / −0.037) gives 121 / 135 of
  the 162 / 173 signals on unplanted rows, against 4 / 2 errors only it finds. It has signalled
  generated bills since it began matching items to the reference history by wording (#57). `domain.boq_numbering` (−0.010 / −0.012) adds 19 / 18 signals on unplanted rows
  (`code_outside_section`) and finds nothing another check misses.
- **`statistical.peer_price`** is down to 22 / 20 signals on unplanted rows (#61's floor) and adds
  F2 (+0.054 / +0.016) because it alone finds 13 / 6 errors.
- **Redundant, not harmful:** `deterministic.field_constraints`, `deterministic.unit_compatibility`
  and `domain.boq_typos` lose no error when left out (another check finds the same ones) and add
  no finding on an unplanted row.
- **Idle on these bills** (0 everywhere; no planted kind is theirs to find, or they need input
  the generator doesn't write, such as a model, a tender text or a price list):
  `deterministic.currency_consistency`, `deterministic.extraction_quality`,
  `deterministic.formula_errors`, `deterministic.numeric_validity`,
  `deterministic.reference_integrity`, `domain.boq_clauses`, `domain.boq_companion_work`,
  `domain.boq_contradictions`, `domain.boq_description_clarity`,
  `domain.boq_required_attributes`, `domain.boq_separate_payment`, `domain.model_quantities`,
  `statistical.open_price_reference`.

### Review budget

Synthetic benchmark: measured on generated data, not real-world performance.

Planted errors found within the first K items read per bill (recall in brackets), and each
list's F2 at 50 (precision: the items among the first 50 that show a planted error's row).

| Reading list | Seed | F2 at 50 | K = 20 | K = 50 | K = our findings |
| --- | --- | --- | --- | --- | --- |
| Our findings (register order) | 20261121 | 0.901 | 259 (0.974) | 260 (0.977) | 260 (0.977) |
| Lines top to bottom | 20261121 | 0.056 | 18 (0.068) | 52 (0.195) | 7 (0.026) |
| Lines in random order | 20261121 | 0.061 | 19 (0.071) | 57 (0.214) | 9 (0.034) |
| Most expensive lines first | 20261121 | 0.062 | 46 (0.173) | 60 (0.226) | 35 (0.132) |
| Findings and most expensive lines, interleaved | 20261121 | 0.336 | 253 (0.951) | 261 (0.981) | 198 (0.744) |
| Our findings (register order) | 20261120 | 0.894 | 223 (0.953) | 223 (0.953) | 223 (0.953) |
| Lines top to bottom | 20261120 | 0.049 | 17 (0.073) | 39 (0.167) | 7 (0.030) |
| Lines in random order | 20261120 | 0.064 | 17 (0.073) | 53 (0.226) | 9 (0.038) |
| Most expensive lines first | 20261120 | 0.078 | 38 (0.162) | 61 (0.261) | 33 (0.141) |
| Findings and most expensive lines, interleaved | 20261120 | 0.352 | 221 (0.944) | 225 (0.962) | 179 (0.765) |

- **Our findings beat every status-quo order** by F2 at 50 (0.90 against at most 0.08).
- Bills have few findings each (about 6), so the first 20 hold nearly all of them.
- The interleaved list finds a few more errors within 50 items (the totals the line lists
  reach) but halves precision, so its F2 is 0.34 / 0.35.
- The line lists assume a reviewer spots every error on a line read, which favours them.

## Hand-planted answer key (one real bill, counts only)

Hand-planted faults in one real bill: test material, not real-world performance; counts only.

26 faults planted by hand in a copy of a real bill of the hackathon dataset, scored with
`--answer-key` against every registered check; the clean original is the GAEB 90 file it was
made from. A hit is discounted when the same check and rule also report the same line of the
clean original. Findings in the issue register's order: 58 on the faulty bill, 38 on the clean
original.

| Metric | Before discount | After clean-original discount |
| --- | --- | --- |
| **F2 at 50 (main score)** | **0.760** | **0.719** |
| Precision at 50 | 0.540 | 0.500 |
| Recall at 50 | 0.846 | 0.808 |
| Faults found | 23 | 21 |
| Found in the first 20 findings | 11 | 10 |
| Found in the first 50 findings | 22 | 21 |
| Must-not-flag hits (findings) | 6 | 0 not also on the clean original |
| Faults only one check finds | 16 | 18 |

By category after discount: error 6 of 7, inconsistency 2 of 5, omission 2 of 3, ambiguity 4 of
4, risk 4 of 4, change order opportunity 3 of 3. `domain.boq_clauses` is the only check for 5
faults. Review budget on this bill (before discount), F2 at 50 and faults found at K = 20 / 50:
our findings 0.760 (11 / 22), top to bottom 0.039 (0 / 1), random 0.065 (2 / 2), most expensive
lines 0.400 (7 / 12), interleaved 0.487 (9 / 13).

## Full report, seed 20261121

Synthetic benchmark: measured on generated data, not real-world performance.

Synthetic documents only: generated bills with injected errors. No real-world documents were evaluated, so these numbers say nothing about performance on real bills. The values are ratios over this generated set, not probabilities.

Seed `20261121`, profile `boq`, 100 bills of about 80 to 1500 positions, 0 to 8 planted errors per bill, checked with every registered check. Regenerate with `python -m app.evaluation --variant boq --seed 20261121 --documents 100 --ablation` (see `--help`).

### Bills

Synthetic benchmark: measured on generated data, not real-world performance.

| Metric | Value |
| --- | --- |
| **F2 at 50 (main score)** | **0.901** |
| Precision at 50 (mean) | 0.814 |
| Recall at 50 (mean) | 0.975 |
| Recall | 0.977 |
| Bills | 100 |
| Repeated per building under Lose | 25 |
| With STLB-Bau keys | 25 |
| With unit price components | 25 |
| With a Positionsart column | 38 |
| Of them with the GAEB import's item type names | 19 |
| In English | 25 |
| Data rows | 50346 |
| Item rows | 47513 |
| Planted errors | 266 |
| Rule findings | 296 |
| Signals | 320 |
| Rule findings on unplanted rows (false positives) | 0 |
| False positives per 1,000 rows | 0.000 |
| Risk notes on unplanted rows, checked against the generated bill | 55, all correct |
| Findings per planted error | 1.523 |
| Row classification accuracy | 1.000 |
| Median time per bill (s) | 0.522 |
| Rows per second | 638 |

Timing machine: Darwin arm64, Python 3.13.5; the whole run took 1570.1 s.

### By error kind

Synthetic benchmark: measured on generated data, not real-world performance.

| Type | Kind | Planted | Expected check | Found by it | Recall | Cell localized | Found by any check |
| --- | --- | --- | --- | --- | --- | --- | --- |
| logical | `line_total_arithmetic` | 12 | `deterministic.line_total` (line_total_mismatch) | 12 | 1.000 | 1.000 | 12 |
| logical | `subtotal_mismatch` | 11 | `deterministic.subtotal` (subtotal_mismatch) | 11 | 1.000 | 1.000 | 11 |
| logical | `net_total_mismatch` | 11 | `deterministic.grand_total` (grand_total_mismatch) | 11 | 1.000 | 1.000 | 11 |
| logical | `tax_mismatch` | 11 | `deterministic.grand_total` (tax_mismatch) | 11 | 1.000 | 1.000 | 11 |
| unit | `unknown_unit` | 11 | `deterministic.unit_vocabulary` (unknown_unit) | 11 | 1.000 | 1.000 | 11 |
| duplicate | `duplicate_row` | 11 | `deterministic.exact_duplicates` (exact_duplicate) | 11 | 1.000 | 1.000 | 11 |
| structural | `missing_unit_price` | 8 | `deterministic.required_values` (required_value) | 8 | 1.000 | 1.000 | 8 |
| quantity | `invalid_quantity` | 11 | `deterministic.data_type_conformance` (invalid_value, wrong_type) | 11 | 1.000 | 1.000 | 11 |
| price | `price_decimal_slip` | 11 | `statistical.peer_price` | 11 | 1.000 | 1.000 | 11 |
| price | `price_digit_swap` | 11 | `statistical.peer_price`; `statistical.rate_consistency` | 5 | 0.455 | 1.000 | 8 |
| price | `inconsistent_rate` | 12 | `statistical.rate_consistency` | 12 | 1.000 | 1.000 | 12 |
| price | `wrong_rate_copied` | 11 | `statistical.peer_price` | 6 | 0.545 | 1.000 | 11 |
| price | `placeholder_price` | 12 | `domain.boq_bid_prices` (token_price, zero_price) | 12 | 1.000 | 1.000 | 12 |
| price | `high_contingency_price` | 12 | `statistical.peer_price` | 11 | 0.917 | 1.000 | 12 |
| quantity | `quantity_decimal_slip` | 11 | `statistical.quantity_factor` | 5 | 0.455 | 1.000 | 10 |
| quantity | `quantity_unit_slip` | 11 | `statistical.quantity_factor` | 5 | 0.455 | 1.000 | 11 |
| unit | `price_per_wrong_unit` | 12 | `statistical.peer_price` | 11 | 0.917 | 1.000 | 11 |
| unit | `wrong_unit` | 11 | `semantic.unit_fit` | 11 | 1.000 | 1.000 | 11 |
| semantic | `misplaced_position` | 11 | `semantic.section_fit` | 10 | 0.909 | 1.000 | 10 |
| structural | `code_outside_section` | 11 | `deterministic.hierarchy` (item_outside_section) | 11 | 1.000 | 1.000 | 11 |
| logical | `line_total_slip` | 11 | `deterministic.line_total` (line_total_mismatch) | 11 | 1.000 | 1.000 | 11 |
| logical | `component_sum_error` | 11 | `deterministic.unit_price_components` (component_sum_mismatch) | 11 | 1.000 | 1.000 | 11 |
| duplicate | `duplicate_position` | 11 | `deterministic.exact_duplicates` (exact_duplicate) | 11 | 1.000 | 1.000 | 11 |
| duplicate | `near_duplicate_position` | 11 | `machine_learning.near_duplicates` | 11 | 1.000 | 1.000 | 11 |

### By finding category

Synthetic benchmark: measured on generated data, not real-world performance.

Each kind counts under the finding category its expected check gives its findings. A planted error is found with its category when a matching finding of any check carries that category. Kinds whose expected check is not available yet are listed on a line of their own, marked "check not available yet": their errors are planted but not measured.

| Category | Kinds | Planted | Found with this category |
| --- | --- | --- | --- |
| Error | `line_total_arithmetic`, `subtotal_mismatch`, `net_total_mismatch`, `tax_mismatch`, `missing_unit_price`, `invalid_quantity`, `placeholder_price`, `code_outside_section`, `line_total_slip`, `component_sum_error` | 109 | 109 |
| Inconsistency | `duplicate_row`, `inconsistent_rate`, `quantity_decimal_slip`, `quantity_unit_slip`, `wrong_unit`, `misplaced_position`, `duplicate_position`, `near_duplicate_position` | 89 | 76 |
| Omission | none planted | 0 |  |
| Ambiguity | none planted | 0 |  |
| Risk | `price_decimal_slip`, `price_digit_swap`, `wrong_rate_copied`, `high_contingency_price`, `price_per_wrong_unit` | 57 | 47 |
| Change order opportunity | none planted | 0 |  |
| Reading the file | `unknown_unit` | 11 | 11 |

### By check and kind

Synthetic benchmark: measured on generated data, not real-world performance.

Every check that flagged a planted error, expected or not.

| Check | Kind | Planted | Flagged | Recall | Cell localized |
| --- | --- | --- | --- | --- | --- |
| `deterministic.data_type_conformance` | `invalid_quantity` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.exact_duplicates` | `duplicate_position` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.exact_duplicates` | `duplicate_row` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.field_constraints` | `duplicate_row` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.grand_total` | `net_total_mismatch` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.grand_total` | `subtotal_mismatch` | 11 | 2 | 0.182 | 0.000 |
| `deterministic.grand_total` | `tax_mismatch` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.hierarchy` | `code_outside_section` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.line_total` | `line_total_arithmetic` | 12 | 12 | 1.000 | 1.000 |
| `deterministic.line_total` | `line_total_slip` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.required_values` | `missing_unit_price` | 8 | 8 | 1.000 | 1.000 |
| `deterministic.subtotal` | `subtotal_mismatch` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.unit_compatibility` | `wrong_unit` | 11 | 5 | 0.455 | 1.000 |
| `deterministic.unit_price_components` | `component_sum_error` | 11 | 11 | 1.000 | 1.000 |
| `deterministic.unit_price_components` | `high_contingency_price` | 12 | 2 | 0.167 | 1.000 |
| `deterministic.unit_price_components` | `inconsistent_rate` | 12 | 6 | 0.500 | 1.000 |
| `deterministic.unit_price_components` | `placeholder_price` | 12 | 7 | 0.583 | 1.000 |
| `deterministic.unit_price_components` | `price_decimal_slip` | 11 | 3 | 0.273 | 1.000 |
| `deterministic.unit_price_components` | `price_digit_swap` | 11 | 2 | 0.182 | 1.000 |
| `deterministic.unit_price_components` | `price_per_wrong_unit` | 12 | 6 | 0.500 | 1.000 |
| `deterministic.unit_price_components` | `wrong_rate_copied` | 11 | 4 | 0.364 | 1.000 |
| `deterministic.unit_vocabulary` | `unknown_unit` | 11 | 11 | 1.000 | 1.000 |
| `domain.boq_bid_prices` | `placeholder_price` | 12 | 12 | 1.000 | 1.000 |
| `domain.boq_numbering` | `code_outside_section` | 11 | 2 | 0.182 | 1.000 |
| `domain.boq_numbering` | `line_total_slip` | 11 | 1 | 0.091 | 0.000 |
| `domain.boq_position_types` | `high_contingency_price` | 12 | 10 | 0.833 | 0.000 |
| `domain.boq_position_types` | `inconsistent_rate` | 12 | 5 | 0.417 | 0.000 |
| `domain.boq_position_types` | `quantity_decimal_slip` | 11 | 4 | 0.364 | 0.000 |
| `domain.boq_position_types` | `quantity_unit_slip` | 11 | 5 | 0.455 | 0.000 |
| `domain.boq_typos` | `near_duplicate_position` | 11 | 1 | 0.091 | 1.000 |
| `domain.standard_text_keys` | `high_contingency_price` | 12 | 3 | 0.250 | 1.000 |
| `domain.standard_text_keys` | `inconsistent_rate` | 12 | 1 | 0.083 | 1.000 |
| `domain.standard_text_keys` | `placeholder_price` | 12 | 2 | 0.167 | 1.000 |
| `domain.standard_text_keys` | `price_decimal_slip` | 11 | 2 | 0.182 | 1.000 |
| `domain.standard_text_keys` | `price_digit_swap` | 11 | 1 | 0.091 | 1.000 |
| `domain.standard_text_keys` | `price_per_wrong_unit` | 12 | 1 | 0.083 | 1.000 |
| `domain.standard_text_keys` | `wrong_rate_copied` | 11 | 1 | 0.091 | 1.000 |
| `machine_learning.near_duplicates` | `near_duplicate_position` | 11 | 11 | 1.000 | 1.000 |
| `semantic.section_fit` | `misplaced_position` | 11 | 10 | 0.909 | 1.000 |
| `semantic.unit_fit` | `wrong_unit` | 11 | 11 | 1.000 | 1.000 |
| `statistical.historical_price` | `inconsistent_rate` | 12 | 3 | 0.250 | 0.667 |
| `statistical.historical_price` | `placeholder_price` | 12 | 2 | 0.167 | 1.000 |
| `statistical.historical_price` | `price_decimal_slip` | 11 | 7 | 0.636 | 1.000 |
| `statistical.historical_price` | `price_digit_swap` | 11 | 4 | 0.364 | 1.000 |
| `statistical.historical_price` | `price_per_wrong_unit` | 12 | 5 | 0.417 | 1.000 |
| `statistical.historical_price` | `quantity_decimal_slip` | 11 | 7 | 0.636 | 1.000 |
| `statistical.historical_price` | `quantity_unit_slip` | 11 | 9 | 0.818 | 1.000 |
| `statistical.historical_price` | `wrong_rate_copied` | 11 | 2 | 0.182 | 1.000 |
| `statistical.peer_price` | `high_contingency_price` | 12 | 11 | 0.917 | 1.000 |
| `statistical.peer_price` | `placeholder_price` | 12 | 6 | 0.500 | 1.000 |
| `statistical.peer_price` | `price_decimal_slip` | 11 | 11 | 1.000 | 1.000 |
| `statistical.peer_price` | `price_digit_swap` | 11 | 4 | 0.364 | 1.000 |
| `statistical.peer_price` | `price_per_wrong_unit` | 12 | 11 | 0.917 | 1.000 |
| `statistical.peer_price` | `wrong_rate_copied` | 11 | 6 | 0.545 | 1.000 |
| `statistical.quantity_factor` | `quantity_decimal_slip` | 11 | 5 | 0.455 | 1.000 |
| `statistical.quantity_factor` | `quantity_unit_slip` | 11 | 5 | 0.455 | 1.000 |
| `statistical.rate_consistency` | `high_contingency_price` | 12 | 5 | 0.417 | 1.000 |
| `statistical.rate_consistency` | `inconsistent_rate` | 12 | 12 | 1.000 | 1.000 |
| `statistical.rate_consistency` | `placeholder_price` | 12 | 1 | 0.083 | 1.000 |
| `statistical.rate_consistency` | `price_decimal_slip` | 11 | 1 | 0.091 | 1.000 |
| `statistical.rate_consistency` | `price_digit_swap` | 11 | 3 | 0.273 | 1.000 |
| `statistical.rate_consistency` | `price_per_wrong_unit` | 12 | 1 | 0.083 | 1.000 |
| `statistical.rate_consistency` | `wrong_rate_copied` | 11 | 1 | 0.091 | 1.000 |

### Signals on unplanted rows

Synthetic benchmark: measured on generated data, not real-world performance.

Signals are findings of statistical, machine-learning, semantic and research checks. On rows where nothing was planted they are counted here, apart from rule findings, and not called false positives: a generated bill can hold a genuinely odd price by chance.

| Check | Signals on unplanted rows | Per 1,000 item rows |
| --- | --- | --- |
| `domain.boq_contradictions` | 0 | 0.000 |
| `domain.boq_description_clarity` | 0 | 0.000 |
| `domain.boq_numbering` | 19 | 0.400 |
| `domain.boq_typos` | 0 | 0.000 |
| `machine_learning.near_duplicates` | 0 | 0.000 |
| `semantic.section_fit` | 0 | 0.000 |
| `semantic.unit_fit` | 0 | 0.000 |
| `statistical.historical_price` | 121 | 2.547 |
| `statistical.open_price_reference` | 0 | 0.000 |
| `statistical.peer_price` | 22 | 0.463 |
| `statistical.quantity_factor` | 0 | 0.000 |
| `statistical.rate_consistency` | 0 | 0.000 |

#### The 10 strongest, for inspection

| Bill | Check | Rule | Severity | Rows | Title |
| --- | --- | --- | --- | --- | --- |
| boq-de-013.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 41 | Unit price 8.68 far below comparable positions (median 49.31) |
| boq-de-008.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 6 | Unit price 50.23 far above comparable positions (median 9.1) |
| boq-de-008.xlsx | `statistical.peer_price` | `peer_price_outlier` | high | 7 | Unit price 50.23 far above comparable positions (median 9.1) |
| boq-de-067.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 23 | Unit price 6.94 far below comparable positions (median 26.78) |
| boq-de-067.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 4 | Unit price 29.56 far above comparable positions (median 7.72) |
| boq-de-060.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 31 | Unit price 423.54 far below comparable positions (median 1567.11) |
| boq-de-056.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 46 | Unit price 40.72 far above comparable positions (median 11.41) |
| boq-de-067.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 3 | Unit price 26.78 far above comparable positions (median 7.72) |
| boq-de-067.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 24 | Unit price 7.72 far below comparable positions (median 26.78) |
| boq-en-092.xlsx | `statistical.peer_price` | `peer_price_outlier` | medium | 184 | Unit price 1241.48 far above comparable positions (median 362.06) |

### Rule findings on unplanted rows (false positives)

Synthetic benchmark: measured on generated data, not real-world performance.

Risk notes on unplanted rows, checked against the generated bill: 55, all correct. A list of the bill's contingency and hourly positions (`domain.boq_position_types`) is a correct note when every row it names is such a position of the generated bill (the generator's own item types); it claims no error, so it is counted here and not as a false positive. A list that names any other row is a false positive below.

None.

### Missed by an available expected check

Synthetic benchmark: measured on generated data, not real-world performance.

| Bill | Kind | Row | Change | Rules found |
| --- | --- | --- | --- | --- |
| boq-de-008.xlsx | `quantity_unit_slip` | 90 | quantity 34.29 m entered in mm as 34290.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-en-011.xlsx | `quantity_decimal_slip` | 103 | quantity 10 written as 1000 (× 100) | none |
| boq-de-013.xlsx | `wrong_rate_copied` | 14 | unit price 343.63 replaced by 37.04, the unit price of position 03.0090 | historical_price_outlier |
| boq-de-013.xlsx | `quantity_unit_slip` | 91 | quantity 173.78 m entered in cm as 17378.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-021.xlsx | `wrong_rate_copied` | 35 | unit price 24.31 replaced by 53.41, the unit price of position 11.0530 | component_sum_mismatch, historical_price_outlier |
| boq-en-023.xlsx | `price_per_wrong_unit` | 31 | unit price 201.22 per m3 written as 60.37, the price per m2 of a 0.30 m thick part | none |
| boq-de-025.xlsx | `quantity_decimal_slip` | 108 | quantity 5949.78 written as 594978.00 (× 100) | contingency_and_hourly, historical_quantity_outlier |
| boq-de-026.xlsx | `price_digit_swap` | 78 | unit price 7.82 written as 7.28 | none |
| boq-de-027.xlsx | `misplaced_position` | 275 | position 02.09.0160 moved into Titel 02.04 as 02.04.0160 | none |
| boq-en-032.xlsx | `price_digit_swap` | 427 | unit price 170.06 written as 107.06 | none |
| boq-de-036.xlsx | `quantity_unit_slip` | 937 | quantity 112.11 m entered in cm as 11211.00 | historical_quantity_outlier |
| boq-de-046.xlsx | `price_digit_swap` | 692 | unit price 73.29 written as 73.92 | component_sum_mismatch |
| boq-de-046.xlsx | `wrong_rate_copied` | 40 | unit price 12.81 replaced by 23.08, the unit price of position 05.0690 | component_sum_mismatch |
| boq-de-048.xlsx | `high_contingency_price` | 64 | unit price 50.74 of a Bedarfsposition without total written as 114.95 (2.2655 times its normal position 01.03.0030) | contingency_and_hourly, identical_positions_price_differs |
| boq-de-052.xlsx | `quantity_unit_slip` | 285 | quantity 441.28 m entered in mm as 441280.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-052.xlsx | `quantity_decimal_slip` | 338 | quantity 64.38 written as 643.80 (× 10) | contingency_and_hourly |
| boq-de-053.xlsx | `wrong_rate_copied` | 76 | unit price 6.38 replaced by 13.34, the unit price of position 02.0270 | component_sum_mismatch |
| boq-de-054.xlsx | `quantity_decimal_slip` | 290 | quantity 366.29 written as 3.6629 (× 0.01) | contingency_and_hourly, historical_quantity_outlier |
| boq-de-056.xlsx | `price_digit_swap` | 598 | unit price 126.88 written as 216.88 | historical_price_outlier |
| boq-de-061.xlsx | `wrong_rate_copied` | 581 | unit price 27.44 replaced by 71.70, the unit price of position 04.1120 | component_sum_mismatch, same_key_unit_prices |
| boq-de-068.xlsx | `quantity_decimal_slip` | 123 | quantity 117.06 written as 1170.60 (× 10) | contingency_and_hourly |
| boq-de-068.xlsx | `quantity_unit_slip` | 63 | quantity 238.41 m entered in mm as 238410.00 | contingency_and_hourly, historical_quantity_outlier |
| boq-de-068.xlsx | `price_digit_swap` | 116 | unit price 9.06 written as 9.60 | same_key_unit_prices |
| boq-de-076.xlsx | `price_digit_swap` | 88 | unit price 81.83 written as 81.38 | none |
| boq-de-083.xlsx | `quantity_decimal_slip` | 191 | quantity 64.20 written as 64200.00 (× 1000) | historical_quantity_outlier |
| boq-de-084.xlsx | `quantity_unit_slip` | 176 | quantity 9.39 m entered in mm as 9390.00 | contingency_and_hourly, historical_quantity_outlier |

### Definitions

F2 at 50, the main score, weighs recall four times as much as precision (F-beta, beta = 2) over the first 50 findings of each bill in the issue register's order, every finding counted, signals included, averaged over the bills with planted errors (`f_beta` and the metric definitions in `backend/app/evaluation/scoring.py`). A planted error is found by a check when a finding of that check highlights a row where reporting the error is correct: its own row, the totals it throws off, and for a changed price or quantity the position's identical copies (a comparison of two copies cannot tell which one is wrong). Recall is found errors over planted errors of the kind; cell localization is found errors whose wrong cell the check highlights over found errors. The expected checks are in `backend/app/evaluation/expectations.py`; a kind shows "check not available yet" instead of a recall when none of its expected checks is available in this run: not built yet, or built while the profile lacks a setting the check needs (the `setting` of its entry in that file); every run plans every registered check. The expected finding category of each kind (`EXPECTED_CATEGORY`, same file) is the category its expected check gives its findings; a finding's category is computed from its check and rule (`backend/app/models/finding_category.py`), and findings about reading the file have none ("Reading the file"). See `backend/app/evaluation/boq_report.py`.

### All checks

Synthetic benchmark: measured on generated data, not real-world performance.

Every registered check runs: 24 rule checks and 12 signal checks.

| Metric | Value |
| --- | --- |
| **F2 at 50 (main score)** | **0.901** |
| Precision at 50 (mean) | 0.814 |
| Recall at 50 (mean) | 0.975 |
| Planted errors | 266 |
| Found by any check | 260 |
| Recall | 0.977 |
| Findings | 616 |
| Signals on unplanted rows | 162 |
| Rule findings on unplanted rows | 0 |

#### Leave-one-out ablation

Synthetic benchmark: measured on generated data, not real-world performance.

Each bill validated again once per check, with that check left out. *Lost without it*: planted errors no finding matches any more; *gained*: errors only the run without it finds. The last three columns are the full run's count minus the run without the check. *Errors its findings match* and *only it matches* are read from the full run, for comparison. *F2 at 50 it adds*: the full run's F2 at 50 minus the run without it (negative: the score rises without it).

| Check | Kind | F2 at 50 it adds | Errors its findings match | Only it matches | Lost without it | Gained without it | Findings it adds | Signals on unplanted rows it adds | Rule findings on unplanted rows it adds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `deterministic.currency_consistency` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `deterministic.data_type_conformance` | rule | +0.039 | 11 | 11 | 11 | 0 | 11 | 0 | 0 |
| `deterministic.exact_duplicates` | rule | +0.041 | 22 | 11 | 11 | 0 | 22 | 0 | 0 |
| `deterministic.extraction_quality` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `deterministic.field_constraints` | rule | +0.001 | 11 | 0 | 0 | 0 | 11 | 0 | 0 |
| `deterministic.formula_errors` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `deterministic.grand_total` | rule | +0.058 | 24 | 22 | 22 | 0 | 44 | 0 | 0 |
| `deterministic.hierarchy` | rule | +0.026 | 11 | 9 | 9 | 0 | 11 | 0 | 0 |
| `deterministic.line_total` | rule | +0.061 | 23 | 22 | 22 | 0 | 23 | 0 | 0 |
| `deterministic.numeric_validity` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `deterministic.reference_integrity` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `deterministic.required_values` | rule | +0.024 | 8 | 8 | 8 | 0 | 8 | 0 | 0 |
| `deterministic.subtotal` | rule | +0.046 | 11 | 9 | 9 | 0 | 11 | 0 | 0 |
| `deterministic.unit_compatibility` | rule | +0.001 | 5 | 0 | 0 | 0 | 5 | 0 | 0 |
| `deterministic.unit_price_components` | rule | +0.037 | 41 | 14 | 14 | 0 | 41 | 0 | 0 |
| `deterministic.unit_vocabulary` | rule | +0.019 | 11 | 11 | 11 | 0 | 11 | 0 | 0 |
| `domain.boq_bid_prices` | rule | +0.015 | 12 | 2 | 2 | 0 | 12 | 0 | 0 |
| `domain.boq_clauses` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `domain.boq_companion_work` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `domain.boq_contradictions` | signal | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `domain.boq_description_clarity` | signal | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `domain.boq_numbering` | signal | -0.010 | 3 | 0 | 0 | 0 | 22 | 19 | 0 |
| `domain.boq_position_types` | rule | +0.006 | 24 | 2 | 2 | 0 | 75 | 0 | 0 |
| `domain.boq_required_attributes` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `domain.boq_separate_payment` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `domain.boq_typos` | signal | +0.000 | 1 | 0 | 0 | 0 | 1 | 0 | 0 |
| `domain.model_quantities` | rule | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `domain.standard_text_keys` | rule | +0.003 | 11 | 1 | 1 | 0 | 11 | 0 | 0 |
| `machine_learning.near_duplicates` | signal | +0.028 | 11 | 10 | 10 | 0 | 11 | 0 | 0 |
| `semantic.section_fit` | signal | +0.033 | 10 | 10 | 10 | 0 | 10 | 0 | 0 |
| `semantic.unit_fit` | signal | +0.010 | 11 | 6 | 6 | 0 | 11 | 0 | 0 |
| `statistical.historical_price` | signal | -0.050 | 39 | 4 | 4 | 0 | 160 | 121 | 0 |
| `statistical.open_price_reference` | signal | +0.000 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| `statistical.peer_price` | signal | +0.054 | 49 | 13 | 13 | 0 | 71 | 22 | 0 |
| `statistical.quantity_factor` | signal | +0.019 | 10 | 3 | 3 | 0 | 10 | 0 | 0 |
| `statistical.rate_consistency` | signal | +0.016 | 24 | 6 | 6 | 0 | 24 | 0 | 0 |

Checks whose removal loses no planted error: `deterministic.currency_consistency`, `deterministic.extraction_quality`, `deterministic.field_constraints`, `deterministic.formula_errors`, `deterministic.numeric_validity`, `deterministic.reference_integrity`, `deterministic.unit_compatibility`, `domain.boq_clauses`, `domain.boq_companion_work`, `domain.boq_contradictions`, `domain.boq_description_clarity`, `domain.boq_numbering`, `domain.boq_required_attributes`, `domain.boq_separate_payment`, `domain.boq_typos`, `domain.model_quantities`, `statistical.open_price_reference`. Of them adding findings on unplanted rows: `domain.boq_numbering`.

#### Review budget

Synthetic benchmark: measured on generated data, not real-world performance.

Planted errors found within the first K items a reviewer reads per bill (recall in brackets). One item is one finding or one line (an item or total row); the lists and their assumptions are described in `backend/app/evaluation/ablation.py`. The interleaved list alternates a finding and the most expensive line not yet shown. F2 at 50 of a list, per bill with planted errors and then averaged: precision is the items among its first 50 that show a row of a planted error, over the items read; recall is the planted errors they find.

| Reading list | F2 at 50 | K = 20 | K = 50 | K = our findings |
| --- | --- | --- | --- | --- |
| Our findings (register order) | 0.901 | 259 (0.974) | 260 (0.977) | 260 (0.977) |
| Lines top to bottom | 0.056 | 18 (0.068) | 52 (0.195) | 7 (0.026) |
| Lines in random order | 0.061 | 19 (0.071) | 57 (0.214) | 9 (0.034) |
| Most expensive lines first | 0.062 | 46 (0.173) | 60 (0.226) | 35 (0.132) |
| Findings and most expensive lines, interleaved | 0.336 | 253 (0.951) | 261 (0.981) | 198 (0.744) |

## Targeted follow-up to issues 12 and 70

Synthetic benchmark: measured on generated data, not real-world performance.

These are **small regression runs, not a replacement for the 100-bill B7 results above**.
Before is upstream main `126b371`; after adds the numerical history guard and limits the
quantity check's small-count exemption to the `count` dimension. No thresholds, generators,
answer keys, scoring rules or registration choices changed. Each run uses eight bills with
80–100 requested positions, every registered check, and real leave-one-out ablation. Each took
24–28 seconds on Darwin arm64, Python 3.13.5. These known seeds are not new held-out evidence.

| Seed | F2@50 before → after | Historical signals on unplanted rows | All signals on unplanted rows | Planted faults found before → after |
| --- | --- | --- | --- | --- |
| 20261121 | 0.936 → 0.972 | 2 → 0 | 4 → 2 | 23/23 → 23/23 |
| 20261120 | 0.978 → 0.991 | 4 → 0 | 7 → 3 | 23/23 → 23/23 |

The history check's marginal F2@50 changes from −0.036 / −0.012 to 0 / 0. It also loses
1 / 4 planted-fault matches; other checks still find those faults. The wider historical
matcher had borrowed projects with different numerical specifications, such as CW 50 versus
CW 100. Require every number in the compared descriptions to match in order before choosing
each project's best reference. This deliberately trades coverage for comparability: the P25
API fixture now compares 6 rather than 195 positions and retains its one planted price error.
The guard is not semantic scope matching: negation, bundled work, equivalents written in
different units, phase numbers and project-specific price/quantity effects remain limitations.

The numbering check is unchanged and still contributes −0.011 / −0.009 F2@50, two unmatched
signals per seed. Direct inspection on seed 20261121 found actual gaps: `03.0090` disappeared
when the misplaced-position fault moved its item (gap reported at rows 64–65), and `2.20`
disappeared when the outside-section fault changed its code (gap reported at rows 58 and 60,
fault at row 59). The benchmark does not credit these neighboring rows. **Accept this measured
review cost**, rather than removing a real completeness question, suppressing an intentional
rule or widening the answer key to make the score green. The original 100-bill negative
contribution is not claimed to be eliminated.

For #12, whole-number lengths, areas, volumes, masses and times below 100 are no longer
silenced by a safeguard intended for 1 versus 10 pieces. Paired and three-member regressions
exercise both reporting and continued piece-count abstention. All eleven new positive/mismatch
regression cases fail against unchanged main and pass with the fixes. The P25 API regression
also passes. A digit swap without a comparable position, source contradiction or trustworthy
external reference cannot be distinguished from a legitimate price merely by rearranging its
digits. We do not add arbitrary guesses or Isolation Forest/LOF just to name more algorithms;
ADR 0010's explainable-comparison decision remains in force.

The delivered comparison checks and B7 measurement complete the implementation scope of #12.
Broader quantity peers, scope-aware historical matching and natural-error accuracy need an
independently judged case before choosing another implementation. That useful remainder is
[tracked separately in #73](https://github.com/AminDaryan/tabular-integrity-workbench/issues/73),
not declared solved or dropped because of a demo deadline. The 100-bill B7 run and full suite
were not repeated locally; only fast targeted checks were requested.

Reproduce each small after run from `backend/` (use either seed above):

```bash
python -m app.evaluation --variant boq --seed 20261121 --documents 8 --positions 80 100 --ablation --out var/closure-check
```
