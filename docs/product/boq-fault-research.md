# BoQ faults and evaluation evidence

**Real bidding failures include unit-basis and quantity mistakes whose arithmetic is internally consistent. A benchmark made only of decimal slips and broken totals would miss important failure modes.**

Research checked **20 November 2026**. This note is independent of any detector implementation. It records public evidence, its limitations, and proposed benchmark cases so later work can reuse the research. No confidential BoQ contents or derived prices are reproduced here or were submitted to public research services. This is a targeted investigation, not an estimate of how often each mistake occurs and not legal advice.

Related research: [research frontier](research-frontier.md), particularly its evaluation and review-budget recommendations; [estimator interview](estimator-interview.md) for the project's workflow context.

## Verified case: an asphalt price used on the wrong unit basis

**BGH, judgment of 11 November 2014, X ZR 32/14, “Fahrbahnerneuerung II.”** A roadworks bidder used an area-based calculation where the bill required tonnes. The resulting line multiplication was consistent, but the price basis was wrong.

Primary sources, both accessed:

- [BGH press release 163/2014, published 12 November 2014](https://www.bundesgerichtshof.de/SharedDocs/Pressemitteilungen/DE/2014/2014163.html).
- [Full BGH judgment, PDF](https://www.bundesgerichtshof.de/SharedDocs/Entscheidungen/DE/Zivilsenate/X_ZS/2014/X_ZR__32-14.pdf?__blob=publicationFile&v=1), especially paragraphs 2, 12–14, 19–20. Paragraph references are preferable to page numbers across PDF viewers.

### What the sources establish

The press release identifies an incorrect quantity basis in one bid position and an approximately €455,000 offer against the next-lowest approximately €621,000 offer. The judgment supplies the mechanism:

> “Statt der geforderten Abrechnungseinheit ‘Tonne’ (Menge: 4.125) sei die Abrechnungseinheit ‘m²’ und als Massenansatz 150 kg/m² zugrunde gelegt worden.” — paragraph 2.

The German quantity notation “4.125” means **4,125 tonnes**, not 4.125 tonnes. Paragraph 13 records a numeric unit price of **€9.60/m²**, multiplied by 4,125 to produce **€39,600**. At the stated 150 kg/m² basis, the offered area price corresponds to **€64/t**: 9.60 ÷ 0.15 = 64. The equivalent line amount is therefore 4,125 × 64 = **€264,000**, a **€224,400** difference. These last two amounts are arithmetic derived from the judgment's inputs.

Do not confuse **€59.59/t** with **€64/t**. Paragraph 13 distinguishes the bidder's own manufacturing costs (€8.94/m², approximately €59.59/t) from its offered price (€9.60/m², €64/t). Likewise, the replacement contractor's eventual cost difference is not the same measure as the correction to this position.

The unit mix-up began as the bidder's explanation, but paragraphs 12–13 state that the calculation error itself was undisputed by the time of award; its significance was disputed. This is stronger evidence than an unresolved allegation. The court did not create a universal percentage cutoff: paragraph 19 expressly rejects treating the approximately 27% gap to the next bid as a general threshold.

### What this changes in a benchmark

- **Keep totals consistent after injecting the fault.** Multiplication and subtotal checks should not be expected to catch this class of problem.
- **Test unit basis, not just the unit label.** A price can be calculated on one basis while a quantity is supplied on another. Conversion may require a stated thickness, density or coverage rate, rather than a simple unit dictionary.
- **Include related-document evidence.** A calculation sheet or price explanation may expose a basis mismatch that a lone BoQ row cannot establish. Label a case “needs external context” if the necessary conversion evidence is unavailable.
- **Evaluate the whole failure chain.** Separately test extraction, normalization, detection, exact localization, explanation and review priority. A numerically unusual price is a lead, not proof of the unit error.
- **Do not copy a 27% threshold into a detector.** It is a fact of this dispute, not a calibrated statistical or legal decision rule.

## Important contrast: omitted costs can be invisible in the offer

Paragraph 14 of the same judgment discusses **BGH, 7 July 1998, X ZR 17/97**. It says the earlier bidder's claimed omission of transport and assembly costs was not apparent from the unit prices and the alleged calculation error had not been sufficiently substantiated.

Evidence boundary: this note verified that contrast in the **2014 judgment**, not the complete 1998 case record. It must not be described as a proven instance of omitted costs.

Benchmark implication: include cases where the correct answer is **“cannot establish from the supplied documents.”** A system should not invent missing cost components simply because a price is low. A deliberately competitive price, legitimately included scope, or genuinely different work can all create apparent outliers.

## Proposed case families, not observed prevalence

These are experimental recommendations informed by the case above and the product's review goal. They are not claims that all have been verified in public court records.

| Family | Injection or control | Evidence needed to judge it |
| --- | --- | --- |
| Decimal or transcription slip | Price ×10 or ÷10; placeholder price; update totals consistently | Original/corrected value and exact affected cell |
| Wrong price basis | Area-based rate applied to a mass-based quantity, with coherent totals | Required unit plus explicit conversion assumptions or calculation sheet |
| Wrong quantity basis | Quantity derived with wrong coverage, thickness or dimensional basis | Drawing, specification or takeoff that establishes the correct quantity |
| Repeated correlated error | Several related positions receive the same wrong conversion | Independent reference outside the corrupted peer group |
| Scope inclusion or omission | Transport, access or installation claimed missing | Contractual inclusion/exclusion evidence; otherwise an unresolved question |
| Legitimate outlier control | Different performance, small quantity, access constraints, lump sum or intentional pricing | Reviewer rationale for why the unusual value is acceptable |
| Insufficient evidence control | No comparable positions or missing conversion inputs | Explicit “not checked” or “needs context” result, not a silent pass |

## A recall-first evaluation still needs a review budget

The user preference is to miss fewer real faults, accepting extra investigations. That favors **recall**, but unlimited warnings can bury a serious defect. Measure both all-findings recall and **recall at 20/50 reviewed findings**, with a fixed review policy. For two lanes, record the allocation between lanes and deduplicate findings before charging the review budget; two lists of 20 are not a 20-item budget.

The benchmark needs:

1. **An answer key:** fault identity, exact location, what changed, acceptable evidence and expected outcome. Matching only a related subtotal row is weaker than locating and explaining the actual wrong input.
2. **Clean and difficult controls:** adjudicated legitimate oddities and insufficient-evidence cases. Unlabeled rows cannot automatically be treated as false positives in natural documents.
3. **Separate denominators:** distinguish faults in scope for a check from all benchmark faults. Report coverage and abstentions, including rows without peers.
4. **Independent holdout projects:** tune thresholds on some projects, freeze them, then evaluate others. Many injected variants of one project are not many independent projects.
5. **Review-budget and impact measures:** count distinct faults found at each budget; separately estimate financial exposure captured where the correction is actually known. Peer-median deviation is a scenario, not verified loss or a ground-truth financial label.
6. **Expert adjudication:** a construction estimator reviews a sample of alerts and non-alerts. Synthetic success establishes performance on the chosen injections, not natural-error recall.

For prioritization, retain separate evidence strength, severity and exposure rather than adding arbitrary raw detector scores. A combined score can be an experimental ranking policy, but must be compared against simple baselines under the same budget; it is not an error probability. XGBoost could later learn a ranking from adjudicated outcomes, but learning only from planted faults risks learning the injection patterns. That recommendation is methodological judgment, not a result of a trained model experiment here.

## Research still open

- More independent, fully verified cases, especially omissions, inconsistent requirements and legitimate extreme prices. One detailed court case does not establish representativeness or frequency.
- A natural-error set reviewed by estimators; public case narratives are not complete project benchmark datasets.
- The full 1998 record, if needed for a separate case study. Its alleged omission should remain labeled as such until verified.
- **BGH VII ZR 201/06** was considered as a lead for extreme pricing/quantity growth, but its primary text was not retrieved in this pass. No numerical or factual conclusion about it is included here.
- The user's starting paper, **arXiv:2608.19463**, is not assessed by this case-research note. Do not cite this note as verification of that paper's methods or results.

Access note: the search tool failed during this pass and dejure's external redirect links were rate-limited. The decisive 2014 press release and judgment were retrieved directly from the BGH. Use the primary links above instead of repeating discovery through those redirects.
