# 0010: Anomalies in bills of quantities are signals, not verdicts

Status: accepted. The owner named the seven anomaly types on 2026-11-20 and decided the same
day that the comparison checks use NumPy only (no scikit-learn, no SciPy). This record takes
up, for bills of quantities, the statistical, semantic and machine-learning detectors that
[ADR 0008](0008-deferred-to-phase-2.md) deferred; the LLM planner stays deferred.

## Context

A bill of quantities (a GAEB file, XLSX or CSV) can have thousands of positions. The 14
deterministic detectors of Phase 1 find arithmetic and structure errors with certainty, but
nothing compares a position with similar ones, so a wrong unit price is not found when its
line total was computed from it ([known limitations](../known-limitations.md)). The GAEB
import's check `domain.standard_text_keys` ([ADR 0009](0009-gaeb-import.md)) compares only
positions that name the same standard text key, and flags any difference in their units or unit
prices. The owner listed seven anomaly types:

* price: a position much more expensive than comparable positions;
* quantity: an implausibly high quantity for the work;
* unit: the wrong unit for the position;
* semantic: the description does not fit its Titel or category;
* structural: missing mandatory fields or an inconsistent hierarchy;
* logical: a total that does not match quantity × unit price;
* duplicate: duplicate or nearly identical positions.

## Decision

**Rules confirm, comparisons only signal.** A finding is confirmed only when the document
contradicts itself: a total that does not match its parts, a missing mandatory value, a
hierarchy that does not fit, an exact copy. A comparison with other positions never confirms
anything. It is a `suspected_anomaly` (or `needs_external_context` when only information from
outside the file can settle it) and shows what it was compared with, so the reviewer can judge
it; no score is shown as a probability. The issue factory applies the evidence policy to signals
as it does to confirmed findings: a signal computed from a cell that was not read reliably
becomes `extraction_uncertainty`. Every plan step says in its rationale whether its check
can confirm an error or only raises a signal.

**The checks chosen for bills of quantities.** Steps B2 and B3 add them. Positions are compared
where an estimator would compare them, with true peers.

* Rule checks (B2), from GAEB and VOB/A: prices of 0,00 or 0,01 and positions not offered; the
  VOB/A §16c correction (when a line total does not match quantity × unit price, the unit price
  prevails) and the decimal-slip label; unit price components that do not add up to the unit
  price; an OZ outside its Titel, a Titel inside the wrong parent, an OZ out of order; GAEB
  position kinds; copies under a new OZ in the same Titel.
* Signal checks (B3), on one text index: S2 identical positions with different prices; S1
  prices within the same STLB-Bau key and unit, when the file has keys; S3 a quantity 10, 100
  or 1,000 times that of identical or nearly identical positions, with the unit slip it fits
  (cm entered as m); M1 the prices of the most similar positions with the same unit, by
  character n-grams of the text; U1 similar positions measured in another dimension (m²
  against m); T1 a text much closer to the positions of another Titel than to its own; D1
  nearly identical positions (same unit, same numbers, almost the same text) in one Titel.
* The statistics are robust and leave one out: a value is compared with the median of the other
  members of its group, in units of 1.4826 × their median absolute deviation (1.2533 × the
  mean absolute deviation when that is 0), the scale of the modified z-score of Iglewicz and
  Hoaglin. A single wrong value therefore cannot hide by moving the median and widening the
  scale it is measured with. Floats exist only inside the statistics; prices, quantities and
  medians shown to the reviewer are exact decimals.
* STLB-Bau keys come only from the user's own files. The catalogue is a paid product whose
  terms (the 2008 version was read) forbid derived works, so nothing from it is shipped.

**Not adopted.**

* AnoLLM (ICLR 2025) fine-tunes a small language model on rows assumed to be clean, which a
  single uploaded bill is not. Training its smallest model on the paper's datasets with five
  seeds took about 90 GPU hours. It rescales numbers and rounds them to one decimal place
  before the model reads them, its base model is English, and its score gives no reason a
  reviewer can check.
* Zero-shot detection by a language model: local 7B models scored below simple baselines
  (Mistral-7B 62.4 against ECOD 75.5 mean AUROC on 30 ODDS datasets in Li et al. 2024).
* Isolation Forest, for now: it flags unusual rows without saying what is wrong, and it scored
  0.623 mean AUC-ROC on the mixed-type datasets of the AnoLLM paper (ECOD 0.653, AnoLLM's
  360M model 0.810). ADBench found that no unsupervised method is statistically better than
  the others, and that unsupervised methods are more susceptible to duplicated anomalies, such
  as a wrong price copied into several positions. It may come after the comparisons with
  similar positions, together with LOF.
* Embeddings, for now: multilingual sentence models under MIT or Apache-2.0 exist, but they add
  a runtime and a model download, and no published evaluation of them on bill-of-quantities
  positions was found. Character n-grams come first; local embeddings may follow.

**The language model only explains.** On request, a local model served by Ollama explains one
problem from its stored findings. The server must run on this machine unless
`TWB_LLM__ALLOW_REMOTE=true`. The model writes no numbers: it names slots such as
`{F1.unit_price}`, and the workbench fills in the stored values, because language models make
basic number errors (Number Cookbook: "9.11 > 9.9"; TableBench: GPT-4 well below humans). Each
claim is checked against the findings it cites, a claim that fails is dropped and recorded with
the reason, and each explanation is stored with the provider, the model and its digest, the
server version, the prompt version and a digest of its input. Without a model the workbench
works fully, and its health status says why no model is ready.

**The model allow-list.** A configured model must be on the allow-list in
`backend/app/agents/models.py`, or the application refuses to start. Each entry records where
the weights are published and their licence, which must be Apache-2.0 or MIT. A model joins the
list only after its licence is checked and it passes the gates of an accuracy evaluation run
against local models (B5, B7). The list is empty until then.

**Dependencies.** NumPy (2.5.5 or newer) and pandas (3.0.5) are added, with python-dateutil and
tzdata; NumPy 2.5.5 needs Python 3.12 or newer. (2026-11-21: Python 3.11 is supported again on
Windows only, with NumPy 2.4.6, whose Windows wheel bundles the same libraries; see
[SYSTEM_REQUIREMENTS.md](../../SYSTEM_REQUIREMENTS.md).) NumPy's wheels bundle `libscipy_openblas64_`:
OpenBLAS (BSD-3-Clause) and LAPACK (BSD-3-Clause-Open-MPI), with the GCC runtime `libgfortran`
statically linked into it (GPL-3.0-or-later WITH GCC-exception-3.1, the exception that permits
this use). NumPy 2.5.3 and 2.5.4 still bundled `libquadmath` (LGPL-2.1-or-later) as a separate
file, so the lock must not go below 2.5.5. pandas bundles nothing on Linux and macOS; the
Windows wheels of both bundle the Visual C++ runtime. SciPy and scikit-learn are not added:
SciPy's Linux wheel bundles `libquadmath`, and scikit-learn's bundles `libgomp`.
`backend/tests/unit/test_bundled_libraries.py` fails when an installed wheel bundles a library
outside the documented list, and [LICENSES.md](../../LICENSES.md) records every package and
bundled library.

## Consequences

* A reviewer sees confirmed errors and clearly labelled signals, each with the comparison that
  raised it.
* A bill without comparable positions gets no comparison signals. A quantity with nothing
  comparable in the same file can only be judged against the tender (X84 against X83), which
  comes after Phase B.
* Problems group the findings of one mistake (a wrong unit price can break its line total, the
  subtotal of its Titel and the grand total), the most money at stake first, and an
  explanation refers to one problem.
* The planner is injected through the workbench (`Workbench.planner`), so an LLM planner can
  be added without changing how runs are made. Later work, in this order: a bid against its
  tender, several bids against each other (Preisspiegel), the LLM planner, local embeddings
  for similar positions, Isolation Forest and LOF.

## Amendments

2026-11-20, 21:05 Berlin: the owner approved plan section 5a. Findings carry one of six finding categories. On request, the local model also reviews one Titel for missing work; each kind of model finding is offered only if at least 27 of 30 judged findings are right.

2026-11-21, step B2 (built from plan sections 5a and 8; the lead decided these deviations, for
the owner to confirm):

1. **One bid price check.** B2.1's price completeness is not a second detector
   `deterministic.price_completeness`: its rules `not_offered`, `zero_price` and `token_price`
   are rules of `domain.boq_bid_prices`, the bid price check of plan 5a, next to
   `price_below_floor`. The rules, classes and severities are plan section 8's: `not_offered`
   is a confirmed rule violation, high, medium on a position outside the sum, and in a GAEB X84
   bid it says that the tender states whether the position counts; `zero_price` (0,00 on a
   position whose quantity is not 0) and `token_price` (the profile's `token_prices`, BoQ 0,01)
   are suspected anomalies, medium, also on positions outside the sum. A spreadsheet's "nicht
   angeboten" or "not offered" in the unit price is the value marker `not_offered`, which
   contributes zero to totals.
2. **Positions not offered are exempt from `required_values`.** Plan section 8 had
   `required_values` report the empty price of a position not offered as well, for B4 to join
   the two findings. The `boq` profile exempts those rows instead (the item type "nicht
   angeboten" exempts the unit price and line total; the `not_offered` marker in the unit price
   exempts the line total), so the defect is one finding, and B4 has nothing to join. A plan that runs `deterministic.required_values`
   without `domain.boq_bid_prices` does not see such a position.
3. **The numbering check is an error.** `deterministic.hierarchy` (an OZ outside its Titel, a
   Titel under the wrong parent, an OZ out of order) is in the category Error, as plan 5a's
   table lists it; the part-2 specification had said inconsistency.
4. **Risk notes in the benchmarks.** The list of a bill's contingency and hourly positions
   (`domain.boq_position_types`) names positions that the generators write as normal content.
   The benchmarks score it against the generator's own item types: a list every row of which is
   such a position is a correct risk note, reported on its own line ("Risk notes on unplanted
   rows, checked against the generated bill") and left out of precision and false positives;
   a list that names any other row is a false positive, even when it also names a planted row.
   The list is scored by every position it names (its evidence lists them all; the highlighted
   cells stop at 20).
5. **Three rules of plan 5a are not built in B2.** Unit prices below a floor per unit set in
   the profile (Risk, in a bid): only the hourly labour floor exists (the statutory minimum
   wage, in `boq.yaml`); for other units there is no source for a floor, so the owner has to
   name the units and values before the rule can be built. Blank bidder entries (Risk, in a
   bid): the GAEB import does not read text complements or bidder entries, the reason plan 5a
   gives for leaving the check for empty blanks out of this change. A Titel without positions
   (Omission): a rule for `deterministic.hierarchy`, not built; it has to be measured on the
   sample bills first, as a Titel of preliminary notes holds text only. All three are open.
6. **The typo check's thresholds are not plan 5a's.** `domain.boq_typos` lists a word of at
   least 9 letters next to a word used at least 3 times, with swapped neighbouring letters
   counted as one edit; plan 5a says 10 letters, 4 uses and no transpositions. The thresholds
   were chosen on the five sample bills and on the planted-fault test bill itself, so the test
   bill's score is in-sample: with plan 5a's setting the check misses `pf-11`, and the test
   bill gives 20 of 26 faults found and 19 localized instead of 21 and 20.

## Amendment of 2026-11-21: the signal checks of step B3 as built

All only signal. They were built opt-in (not in a baseline plan); since the amendment below
they run on every validation. Each was measured on the BoQ benchmark
(seed 20261120 and seed 7) and on the hackathon's sample bills, locally.

* **S1 `statistical.peer_price`** also does M1's comparison (the nearest positions by character
  n-grams in the same unit), so M1 was not built a second time. It now compares only with
  similar texts by default (`peer_groups`); the section and whole-bill groups found no planted
  price error the text group missed and tripled the signals on unplanted rows. It reports from a
  score of 3.0 (was 2.5). Contingency and alternative positions are compared but are never
  peers, so a Bedarfsposition priced unlike its normal position stands out without shifting the
  group.
* **S2 `statistical.rate_consistency`**: identical positions (same text, unit, currency and,
  where both name one, the same STLB-Bau key) with different unit prices. Two copies give one
  finding that highlights both prices; a factor of ten and a digit swap are named.
* **S3 `statistical.quantity_factor`**: a quantity 10, 100 or 1,000 times that of identical
  positions, with the unit slip it fits (m entered as cm or mm). Conservative: small whole
  counts and positions of another item type are not compared, so it finds about a third of the
  planted slips.
* **U1 `semantic.unit_fit`**: a length, area or volume unit unlike that of the most similar
  positions, none of which share it.
* **T1 `semantic.section_fit`**: a position much closer to a sibling section than to its own,
  with no close member in its own section (parallel sections that repeat the same work are
  left alone). Compared within the innermost section, because in bills with Lose the top level
  is the lot.
* **D1 `machine_learning.near_duplicates`**: nearly identical positions in one section (same
  unit, price and item type, quantity within 10 %, the same numbers in the same order, and the
  differing words typos or abbreviations of each other). Exact copies stay with
  `deterministic.exact_duplicates`.

U1 and T1 report `semantic_warning`, the evidence class the detector contract allows semantic
checks; the others `suspected_anomaly`. S2, S3, U1, T1 and D1 sort their findings under
Inconsistency. The text index is shared (`validation/support/similar.py`).

## Amendment of 2026-11-21: every check runs on every validation

The owner decided that checks are not chosen: every validation runs every registered check, and
nothing can switch one off. The distinction between baseline and opt-in checks is gone with
everything that served it: `DetectorSpec.baseline`, the profiles' `baseline_detectors` and
`disabled_detectors`, the `plan` body of `POST /datasets/{id}/validation-runs` (a client can no
longer send a plan, so no run is a `user` plan), the benchmark's `--plan-step`, and the run
configuration of the web interface ("Choose checks"). A check that does not apply to a dataset
still reports itself as skipped with its reason. The `boq` profile is 1.7.0, `generic` 1.1.0.
An adaptive (LLM) planner, still deferred, must keep every registered check (`check_missing`)
and may set only plannable parameters.

The cost, measured locally on the same machine before and after:

* **BoQ benchmark** (seed 20261120, 100 generated bills, 50,058 item rows): rule findings are
  unchanged (267, none on unplanted rows). The signal checks add 448 findings, of which 345 fall
  on rows where nothing was planted (6.9 per 1,000 item rows): 327 of `statistical.peer_price`
  and 18 of `domain.boq_numbering`. The eleven kinds that waited for B3 are measured
  ([boq-benchmark.md](../evaluation/boq-benchmark.md)). Median time per bill 0.75 s (was 0.40 s).
* **Standard synthetic benchmark** (seed 20261119, 100 small generated bills, 7,507 rows):
  every injected error is still found, but 848 signals match none (112.96 per 1,000 rows; were
  0): 499 of `statistical.peer_price`, 310 of `semantic.section_fit` and 39 of
  `domain.boq_description_clarity`. That variant counts them as false positives, so its
  precision fell from 1.000 to 0.192 ([synthetic-benchmark.md](../evaluation/synthetic-benchmark.md)).
* **The planted-fault test bill** (26 faults): 65 findings (were 44), 24 faults found (were 20)
  and 23 localized (were 20); findings on rows outside every planted fault 29 (were 20): 6 more
  of `statistical.peer_price` and 3 of `statistical.rate_consistency`.
* **The public sample bill** (`samples/`): still exactly its 8 documented findings; no signal
  check flags it.

Then the signals on clean rows were cut where they came from (same day, same machine; precision
and recall before → after):

* `statistical.peer_price` compares a row only with its own kind of work: text peers within
  `text_band` (0.25) of the most similar one, never fewer than `min_peers`. BoQ benchmark seed
  20261120: 327 → 106 signals on unplanted rows, precision 0.475 → 0.716, recall 0.957 → 0.957
  (every planted kind found as before); seed 31: 189 → 68, precision 0.524 → 0.734, recall
  0.964 → 0.964. Higher score thresholds do not separate them: planted errors are found at
  scores of 3.1 to 3.9, and 63 clean rows score 6 or more.
* The standard benchmark's 848 false positives (952 on seed 31) came from its generator, not the
  checks: it priced copies of one item at random, put items in sections named for other trades,
  and wrote catch-all German texts. With the generator fixed, 3 remain on each seed; precision
  0.192 → 0.984 (seed 31: 0.184 → 0.986), recall 1.000 on both.
* The planted-fault test bill: 65 → 60 findings, 29 → 27 on rows outside every planted fault
  (`statistical.peer_price` 6 → 4), precision 0.554 → 0.550, faults found 24 → 23. The fault no
  longer counted (a quantity slip, 250 m written as 25 m) keeps its unit price, which no price
  comparison can see; peer_price had flagged that row by comparing marking tape with pipe work.
  The decimal slip of a unit price (63.50 written as 635.00) is still flagged, now at a higher
  score (10.0, was 8.4).

## Sources

* AnoLLM, ICLR 2025:
  <https://proceedings.iclr.cc/paper_files/paper/2025/file/165bbd0a0a1b9470ec34d5afec582d2e-Paper-Conference.pdf>;
  its base model: <https://huggingface.co/HuggingFaceTB/SmolLM-135M>
* Li et al. 2024, anomaly detection with language models: <https://arxiv.org/html/2406.16308v1>
* ADBench, NeurIPS 2022: <https://arxiv.org/abs/2206.09426>
* Number Cookbook: <https://arxiv.org/abs/2411.03766>; TableBench:
  <https://arxiv.org/abs/2408.09174>
* Modified z-score: NIST/SEMATECH e-Handbook of Statistical Methods,
  <https://itl.nist.gov/div898/handbook/eda/section3/eda35h.htm>
* GAEB DA XML 3.3 Fachdokumentation (unit price components, positions not offered):
  <https://www.gaeb.de/wp-content/uploads/2023/09/Fachdokumentation_GAEB-DA-XML_3.3_2023-01.pdf>
* VOB/A 2019 §16c: <https://lxgesetze.de/vob-a-2019/16c> (a reproduction, not the official
  print)
* STLB-Bau terms:
  <https://www.dinmedia.de/resource/blob/89322/b81731c2ceba3e7f15085fabbba58a83/information-bestellformular-stlb-bau-data.pdf>
* Multilingual sentence models considered: <https://huggingface.co/intfloat/multilingual-e5-small>
  (MIT), <https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2>
  (Apache-2.0)
