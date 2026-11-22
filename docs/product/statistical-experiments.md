# Statistical BoQ experiments: comparables, coherent faults and review ordering

**20 November 2026 — exploratory results, not production accuracy claims.**

**Keep text-based comparables and the two review lanes. Do not blindly lower thresholds, replace the section fallback, or introduce one universal combined score yet.** The largest remaining problem is missed candidates, not just their ordering. Three independent priced projects are too few to train or validate XGBoost responsibly.

Related: [real-world fault evidence and benchmark requirements](boq-fault-research.md), [external research map](research-frontier.md). This note records our own local experiments, independently of future implementation decisions. It contains aggregate evaluation statistics, not confidential descriptions, item identifiers, prices or document extracts. Source documents and row-level derivatives stayed local and were not sent to external services.

## Setup: what was actually measured

- Used the current ingestion pipeline to obtain canonical item records from three priced projects, labeled A/B/C here. Their 249/274/197 positions give **720 priced positions**, not 720 independent projects.
- The paired GAEB/PDF for B matched on item code, quantity, unit price and normalized unit for **all 274 positions**. The GAEB had no descriptions; the PDF did. Description enrichment was an exact local join, not fuzzy matching. Main experiments use enriched B; missing-text results are separate, not a fourth project.
- Ran the production peer-price scoring functions, with current defaults: minimum three peers, text similarity 0.30, at most ten text peers, log-scale floor 0.23, warning/medium/high thresholds 2.5/3.5/6.0. Text similarity is fitted within each bill, on comparable records as in production. No project contributes prices to another project's peers.
- Current scoring covers **660/720 positions (91.7%)**: 49 lack recognized units and 11 more lack sufficient peers. Coverage failures count as misses, not passes.
- Unmodified bills produce 26/36/13 warnings. These are **unadjudicated alerts**, not confirmed false positives or confirmed natural faults.
- Sampled 25 positions per project with fixed seed **20261120**, including positions without recognized units. The same positions and mutations were used for each strategy. Each one-fault experiment has 225 trials: 75 positions × three price changes (×10, ÷10, or 0.01 placeholder).
- Main single-fault results use descending absolute anomaly score, with source-order tie-breaking, under budgets of 20/50 distinct positions. Only reported candidates enter a queue; an unflagged row cannot be rescued by ranking.
- Mutations occur **after extraction**. Changed line totals are recomputed consistently; document-level aggregates are not exercised by this scorer harness. This is not an end-to-end file extraction, reconciliation, UI or explanation benchmark.
- A hit means the **exact altered position** appears as a price-anomaly candidate within budget. It does **not** prove the system explained the fault mechanism, inferred the correct price, or established a real construction defect. Some changed positions were already unusual before injection.

## 1. Which comparable groups help?

| Strategy | Fault-row recall @20 | @50 | Any warning | Mean warnings per trial |
| --- | ---: | ---: | ---: | ---: |
| Same unit anywhere | 40.4% | 40.9% | 40.9% | 15.8 |
| Current section, then unit | 40.4% | 40.9% | 40.9% | 15.8 |
| Current text → section → unit | **56.9%** | 60.0% | 60.0% | 25.1 |
| Deepest full section path, then unit | 48.0% | 56.9% | 57.3% | 36.1 |
| Text → deepest full section path → unit | 55.6% | **64.0%** | **64.4%** | 33.2 |

**Concrete ownership finding:** the scorer's section key uses `section_path[0]`. Each imported bill has one root section, but 24/14/27 distinct full paths. The current fallback therefore behaves identically to unit-only grouping here. This is an observed grouping limitation, not evidence that sections in general are unhelpful. The deepest-path variant used the complete path identity; it did not change production code.

Deeper sections find more planted faults eventually but also produce more warnings. They do **not** improve the first 20 reviews overall. In exploratory leave-one-project-out selection, the best strategy on the other two projects selected current text grouping for A/C, but deeper text grouping for B. B then achieved only **28.0% @20**, compared with **41.3%** using the current text strategy. Across the three selected held-out folds, @20 was **52.4%**, below the fixed current strategy's 56.9%. Do not ship the deeper fallback as an established improvement.

These are exploratory folds, not a pristine prospective test set: the deeper-path variant was motivated by inspecting these same projects. Many seeded variants do not support narrow confidence intervals or broad transfer claims.

### Missing descriptions matter, but there is a review-load tradeoff

On B's same 75 mutations, exact description enrichment improved @20 **36.0% → 41.3%**, and @50/any-warning **40.0% → 49.3%**. Mean warnings increased **23.9 → 35.9**. This supports investigating source-text recovery rather than simply changing the price formula. It does not establish that automatic cross-file joining is safe without the exact-match checks above.

## 2. Does a more realistic fault set change the picture?

The [verified wrong-basis case](boq-fault-research.md) motivated coherent numerical perturbations. The factor 0.15 and its inverse, approximately 6.667, are **stress-test factors**, not evidence that every tested item has an area/mass conversion or that our documents contain this mistake. Quantity, price and total alone cannot establish the physical conversion.

| Family | Scenarios / altered positions | Fault-row recall @20 | @50 / any warning |
| --- | ---: | ---: | ---: |
| Single price ×0.15 | 75 / 75 | 42.7% | 48.0% |
| Single price ÷0.15 | 75 / 75 | 36.0% | 42.7% |
| Three selected peers all priced ×0.15 | 67 / 201 | **24.4%** | **29.4%** |

Eight sampled anchors lacked peers; they are included as misses in single-position cases but cannot define a correlated peer group. For correlated cases, changed the anchor and the first two peers from the current scorer's chosen group. Text peers are similarity-ordered; fallback peers are source-ordered and may represent different work despite sharing a unit. This deliberately stresses contamination of the reference population, not a verified assembly-wide conversion error or a sampled real-world frequency distribution.

Before mutation, 6.7% of the single-case target positions and 11.4% of the correlated target positions were already flagged. Reported recall is row-retrieval performance after mutation, not a count of exclusively new alarms. It must not be called mechanism-detection accuracy.

### Controls and blind spots

- **75 quantity-only changes:** multiplied quantity by ten and recomputed the line amount. Every anomaly score remained exactly unchanged. A price-only statistic has no information about whether this quantity is wrong. An existing price warning on the row is not a successful quantity diagnosis. These cases need takeoff/drawing evidence or another check.
- **75 equivalent price-basis representations:** changed quoted price and price multiplier together by ×100, preserving normalized price and economics. Scores and totals remained identical. This verifies **canonical scorer invariance only**; normalization was supplied to the scorer, so it is not proof that file ingestion correctly interprets every price multiplier.
- **Arithmetic coherence:** asserted that each changed line total equals its changed quantity × normalized unit price × discount factor. Broken line arithmetic cannot explain a price-scorer hit.
- **Not yet available:** estimator-adjudicated legitimate extreme prices, natural errors, or an omission/scope ground-truth set. Unmodified rows cannot substitute for these controls. Consequently, natural precision and natural-error recall remain unknown.

## 3. Which ordering helps within one review budget?

Built **60 mixed scenarios**, 20 per project, each with ten altered positions: two decimal slips, two single basis mistakes, three correlated basis mistakes, one placeholder, and two quantity-only mistakes. There are **480 price-fault instances plus 120 quantity-fault instances**, with repetitions across the same three projects. Every strategy sees the same scorer output and the same fault set.

Ranking policies:

- **Register baseline:** severity descending, then source order, restricted to price findings.
- **Oddness:** absolute anomaly score descending.
- **Money:** absolute peer-median reference deviation descending, as in the money lane.
- **Combined heuristic:** absolute score × log(1 + absolute reference deviation). Deliberately a simple experimental ranking, not a calibrated probability; no learned weights.
- **Two lanes:** alternate high-severity price signals and money candidates, skip previously reviewed positions without charging another slot, and fall back to the other lane when one is exhausted. There are no confirmed deterministic violations in this price-only experiment. This does not evaluate the full multi-detector UI register.

**At the existing warning threshold 2.5:**

| Ordering | Price-fault recall @20 | Known price-fault exposure captured @20 | Price-fault recall @50 |
| --- | ---: | ---: | ---: |
| Register baseline | **42.5%** | 66.8% | 48.5% |
| Oddness | 42.3% | 62.8% | 48.5% |
| Money | 32.5% | 73.0% | 48.5% |
| Combined heuristic | 39.6% | 70.5% | 48.5% |
| Two lanes, 50/50 | 38.3% | **73.3%** | 48.5% |

Exposure captured is the sum of **known injected monetary changes at retrieved price-fault positions**, divided by the known changes at all price-fault positions. Ranking uses peer-median deviation, but ground-truth exposure does **not**: it uses original versus mutated line economics. These are aggregate euro-weighted ratios, not per-project averages or predictions of prevented real loss.

At budget 50 every default-threshold candidate list was exhausted (mean 26.5 warnings), so all policies converged. **Ranking cannot recover an unreported fault.** Budget 20 used an average 19.1 reviews because some lists were shorter than 20.

Quantity-only cases are excluded from the price-fault denominator, not silently dropped from the benchmark: the two-lane @20 result is **30.7% of all planted faults** receiving an in-scope price signal. Merely reviewing a quantity-fault row incidentally is counted separately in local output, not credited as detecting its mechanism. Even price hits establish a lead, not a diagnosis.

Tested strong-lane allocations 0/25/50/75/100%, always with deduplication and fallback. Selecting allocation on two projects favored 50% for each held-out project; its held-out price recall @20 varied **26.9%–57.5%**. Allocations 50/75/100 tied in aggregate here, so this is not evidence that 50/50 is universally optimal. Preserve the two dimensions visibly instead of hiding this choice in one score.

### Recall-first does not mean “lower the threshold and stop measuring”

On the same mixed scenarios, re-ranked the saved scores at warning thresholds 2.5, 2.0 and 1.5. Medium/high definitions stayed unchanged. This is sensitivity analysis, not independently validated threshold tuning.

| Warning threshold | Mean candidate warnings | Price-fault recall, unlimited | Two-lane recall @20 | Two-lane recall @50 |
| --- | ---: | ---: | ---: | ---: |
| 2.5, current | 26.5 | 48.5% | **38.3%** | 48.5% |
| 2.0 | 42.5 | 54.2% | 33.8% | 52.3% |
| 1.5 | 59.8 | **62.7%** | 33.1% | **53.8%** |

More permissive warnings improve candidate recall but can crowd the money queue, reducing first-20 recall. Oddness ordering at threshold 1.5 achieves 43.1% @20 and 56.3% @50, but captures less known exposure @20 than money-first. Optimize candidate coverage and budgeted ranking separately; no one tested policy dominates both objectives.

## What to implement or investigate next

1. **Recover and verify comparable-item context first.** Missing descriptions and root-level grouping are observed issues. Investigate GAEB text extraction and full-path grouping, but keep the current text strategy until a budgeted, project-held-out comparison supports changing it.
2. **Keep both lanes and explicit coverage.** Display no-unit/no-peer exclusions; preserve distinct evidence strength and financial scenario. If adding a single “next item” queue, make its allocation explicit and deduplicate across lanes.
3. **Expand candidates cautiously.** Test a lower-threshold secondary queue without allowing weak, large-money signals to displace all strong signals. Freeze the policy before evaluating new projects. The current results do not justify changing the default threshold automatically.
4. **Add independent evidence for quantities and shared mistakes.** Related takeoff/calculation documents or independently priced comparables are more promising than expecting a within-bill price statistic to diagnose these mechanisms.
5. **Get an estimator's labels before supervised ranking.** Review alerts and sampled non-alerts, including legitimate unusual prices; record rationale and review time. Then compare a learned ranker such as XGBoost with these simple baselines on held-out projects. No XGBoost model was trained in this experiment.

## Reproduction and delivery boundary

Code evaluated at commit [5439d02](https://github.com/AminDaryan/tabular-integrity-workbench/commit/5439d02e51d0c758aec7cad5f97b050ee7b6c879) (type fixes on top of statistical implementation [8946f55](https://github.com/AminDaryan/tabular-integrity-workbench/commit/8946f55361901050953ad0a82baee72725e058fc)). No production detector, API, UI or defaults changed in this experiment.

Local-only harness and sensitive results are retained under `.amp/in/orb-backup/experiments/`: `prepare.py`, `inputs.pkl`, `run.py`, `results.json`, `trials.json`, `mixed_cases.pkl`, `thresholds.py`, `threshold_results.json`. They are not committed or public benchmark fixtures. From the repository root, run `backend/.venv/bin/python .amp/in/orb-backup/experiments/run.py`, then the corresponding `thresholds.py`; preparing inputs also requires the confidential files locally. The fixed seed and current scorer defaults are recorded in `results.json`.

Executed checks: full experiment run completed with all line-arithmetic, quantity-score, canonical-basis and deduplication assertions; separate threshold run exactly reproduced all default-threshold aggregate policy results. An asymmetric hand-built ranking control verified exact lane order, overlapping-lane deduplication, missing exposure and source-order ties. No new permanent test or stable CI benchmark was added. A future production policy needs public-interface regression coverage and end-to-end evaluation in addition to these scorer-level experiments.
