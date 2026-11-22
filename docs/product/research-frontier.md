# Research frontier: AI estimating, BoQ analysis and bidding

**Prioritize evidence-grounded scope reconciliation and selective human review; treat autonomous quantity takeoff, learned commercial pricing and calibrated risk prediction as separate, much less established research bets.** The most useful recent work is broader than BoQ chat: document coordination benchmarks, engineering-drawing failure studies, assembly-aware cost matching, contract triage and claims-derived lessons.

Research cut-off: **20 November 2026**. Primary window: **20 November 2025–20 November 2026**, inclusive. Older first releases and recent revisions of older work are identified below. This is a targeted research map, not a systematic review or a leaderboard of incomparable scores. All experimental results are **author-reported**, not independently reproduced here. No models were downloaded, experiments run, local checkouts changed or confidential project files inspected.

Companion research: [BoQ faults and evaluation evidence](boq-fault-research.md) records a verified German roadworks bidding error, source-level evidence, and implications for realistic fault injection and recall-first review. It is independent of the detector implementation.

Local follow-up: [statistical experiments on our priced bills](statistical-experiments.md) records independently run comparable-group, coherent-fault and deduplicated review-budget experiments. Unlike the external results below, these were run locally; they are exploratory synthetic-fault evidence, not natural-error accuracy estimates.

## What is most worth your attention

1. **AEC-Bench is the strongest immediately useful public evaluation starting point.** It tests drawing/specification coordination and deliberately planted document defects, with a public harness. It does not establish naturally occurring error prevalence or commercial loss prevention. [Paper](https://arxiv.org/html/2603.29199), [repository](https://github.com/nomic-ai/aec-bench).
2. **The most important negative result is that better-looking evidence selection may not generalize.** Mushkani, Bérard and Koseki find a region-crop advantage on repeated tasks, then a negative point estimate on a broader disjoint-project extension. Agreement-based confidence remains dangerously overconfident. [Full text](https://arxiv.org/html/2607.29058v1).
3. **Handoff-H1 is a promising but non-reproducible takeoff POC, not proof of autonomous estimating.** Its composite favors broader scope coverage; humans retain better quantity precision. The public repository omits the actual plans and reference takeoffs. [Paper](https://arxiv.org/html/2608.15032), [repository](https://github.com/handoffai/residential-takeoff-benchmark).
4. **For matching and aggregation, construction compatibility matters more than semantic resemblance.** Unit basis, assembly, thickness, performance, location and inclusion/exclusion boundaries must survive normalization. The Houston/Qatar cost-matching work is directly relevant; the Latvian RIXBUILD POC is interesting but much less auditable. [Houston/Qatar paper](https://www.mdpi.com/2075-5309/16/11/2103), [RIXBUILD full PDF](https://baltijapublishing.lv/index.php/issue/article/download/4933/4816).
5. **Ranking thousands of items is still an open product-research opportunity.** The Florida contract POC demonstrates a prioritization mechanism, not that its top-ranked clauses save the most money or reviewer time. Test review-budget recall and adjudicated usefulness, not just ranking stability. [ITcon paper](https://www.itcon.org/paper/2026/46).
6. **Go beyond errors into execution obligations and claims-linked scope.** Road-tender process maps and NCDOT claims retrieval suggest ways to surface temporary works, testing, access, utility interfaces and administrative obligations. Neither establishes that inferred tasks are genuinely omitted payable scope. [Zagreb process-map study](https://www.mdpi.com/2075-5309/16/22/4570), [C2M](https://ascelibrary.org/doi/10.1061/JCCEE5.CPENG-6754).

## Date and evidence ledger

Dates below come from original arXiv histories or publisher pages, not search-engine dates. A journal issue date is explicitly labeled when a first-online date could not be verified. Peer review is a publication status, not an endorsement of the experiment.

| Work | Verified timing | Status and access used |
|---|---|---|
| C2M / Change to Mitigate | Online **25 Nov 2025**; print **1 Mar 2026** | Peer-reviewed ASCE journal; abstract/history/data statement accessible, substantive full text paywalled |
| ViDoRe V3 | v1 **13 Jan 2026**; v2 **21 Apr 2026** | Preprint; full-text methods/results accessed |
| Abdelsalam et al., BIM–MCP estimating | **24 Jan 2026** | Peer-reviewed Buildings; abstract accessible; PDF fetch blocked |
| AEC-Bench | v1 **31 Mar 2026** | Preprint; full-text methods/results and repository accessed |
| WildTableBench | v1 **1 May 2026**; v2 **21 May 2026** | Preprint; full-text methods/results and repository accessed |
| Al-Derham et al., model/retrieval-guided costing | **25 May 2026** | Peer-reviewed Buildings; abstract accessible; PDF fetch blocked |
| Wu et al., fragmented-BIM probabilistic costing | **28 Jun 2026** | Peer-reviewed journal article; full-text methods/results accessed |
| Oh & Ashuri, change-order impact profiling | Issue **1 Jul 2026**; first-online date not verified | Peer-reviewed ESWA; full-text methods/results accessed |
| DrawingVQA | arXiv v1 **16 Jul 2026**; project identifies CVPR Findings 2026 | Author-stated conference acceptance plus preprint; original paper and project page accessed; proceedings independently unverified |
| Evidence-Grounded Constraint Checking | v1 **31 Jul 2026** | Preprint; full-text methods/results accessed |
| Handoff-H1 | v1 **15 Aug 2026** | Commercial research preprint; full text and benchmark repository accessed |
| SGR-BIM | Issue **Sep 2026**; first-online date not verified | Peer-reviewed Automation in Construction; full-text methods/results accessed |
| Moayyed & Anumba, contract prioritization | **Sep 2026**, publisher supplies month only | Peer-reviewed ITcon; paper/PDF methods/results accessed |
| Zhang et al., technical-bid evaluation | **8 Oct 2026** | Peer-reviewed Buildings; full-text methods/results accessed |
| LED-BENCH | v1 **14 Oct 2026**; v2 **17 Oct 2026** | Preprint; full text and project page accessed |
| Bagants et al., RIXBUILD | **2 Nov 2026**; received 29 Jul, accepted 12 Oct | Journal article; full PDF accessed; limited experimental reporting |
| Mihić & Vilibić, tender process maps | **16 Nov 2026** | Peer-reviewed Buildings; full-text methods/results accessed |
| **MMTabReal: older origin, recent update** | v1 **27 May 2025**; v2 **23 May 2026**; ACL Findings **Jul 2026** | Peer-reviewed 2026 publication of pre-window work; paper/project accessed |

Sources for the less obvious histories: [ViDoRe](https://arxiv.org/abs/2601.08620), [WildTableBench](https://arxiv.org/abs/2605.01018), [DrawingVQA](https://arxiv.org/abs/2607.15418), [LED-BENCH](https://arxiv.org/abs/2610.19571), [MMTabReal](https://arxiv.org/abs/2505.21771), [ACL publication](https://aclanthology.org/2026.findings-acl.2047/). The other date sources are linked in the individual entries below. For SGR-BIM and Oh–Ashuri, window inclusion is supported by the 2026 issue, but exact first appearance remains unresolved.

## Prioritized research map

Priority here means value of investigating or adapting, not highest headline accuracy. Effort estimates later in the report are my estimates, not measurements from these papers.

### A. Cross-document coordination and auditable judgments

#### AEC-Bench: evaluate actual coordination work before building another assistant

**Who:** Harsh Mankodiya, Chase Gallik and Andriy Mulyar at Nomic; Theodoros Galanos at Aurecon. **What:** 196 task instances across nine families using public-sector AEC documents and controlled defects. Tasks include detail review, drawing/specification synchronization, navigation, callout resolution, cross-reference tracing and submittal review. This is an evaluated benchmark and tool-assisted-agent comparison, not a construction-estimating application. [Paper](https://arxiv.org/html/2603.29199).

**Decisive evidence:** With Nomic-enhanced tools, GPT-5.4 task scores rise from 35.7 to 71.4 for detail review, 55.0 to 71.8 for spec/drawing synchronization and 66.7 to 100 for navigation. But callout resolution stays 28.6, while cross-reference tracing falls from 89.2 to 77.1. The best reported submittal-review reward is only 23.1. These are task-specific scores, not interchangeable accuracy measurements. The results do not support a blanket claim that tools improve every task. [Results tables](https://arxiv.org/html/2603.29199).

**Limits and reproducibility:** Single trials per task, correlated task variants, imperfect keyword/structured verifiers and injected rather than naturally sampled defects limit inference. A benchmark with known anomalies cannot estimate field precision when real errors are rare. The Apache-2.0 repository contains harness/configuration and manifest-based asset acquisition; some enhanced tool access is separate. Public harness does not mean every evaluated stack is available for free. [Repository](https://github.com/nomic-ai/aec-bench).

**Why adapt it:** Use its task decomposition and evidence-backed grading as a scaffold for natural BoQ/spec discrepancies. Retain a clean-document control set. Do not present synthetic-defect recall as field utility.

#### Evidence-Grounded Constraint Checking: four-state answers are promising; confidence is not solved

**Who:** Rashid Mushkani, Hugo Bérard and Shin Koseki, Cocoon Lab. **What:** A provenance/evidence contract with a deterministic reducer producing Meets, DoesNotMeet, Missing or Uncertain; experiments allocate PDF evidence to models on 160 AEC-Bench judgment tasks from 29 projects. The architectural discussion includes richer representations, but CAD/IFC integration and correctness of proof traces are **not** what the experiments validate. [Full text](https://arxiv.org/html/2607.29058v1).

**Decisive evidence:** On 40 repeatedly evaluated tasks from six projects, four systems and five runs, region evidence improves accuracy over page evidence by 10.6 percentage points, with a reported 95% interval of 4.3–18.0. On the broader 120-task, 23-project disjoint extension, the point estimate is **−4.1 pp**, interval −10.2–1.9; equal-four-image comparison is −9.7 pp. Thus the positive repeated-task result does not establish a transferable cropping advantage. In the repeated set, region/page accuracy is 51.0/40.4%, exact-task success 20.5/15.9%, and false-pass rates 41.1/51.6%. Finding F1 is only 9.0/5.2%, with a strict phrase matcher contributing to the low value. [Evaluation/results](https://arxiv.org/html/2607.29058v1).

**What fails:** Confidence based on agreement remains high, around 0.86–0.93, while retained risk is 43–80% in the reported settings. Independent-looking model votes may share retrieval and interpretation errors. The broader extension followed the initial results rather than constituting preregistered confirmation. Public benchmark exposure cannot be excluded. An executable public repository URL was not verified; the paper describes archived evaluation artifacts. [Limitations](https://arxiv.org/html/2607.29058v1).

**Why adapt it:** Borrow explicit evidence states and deterministic final checks. Do not borrow the confidence score as a probability that an item is safe. “Missing evidence” must remain distinct from “missing construction scope.”

#### SGR-BIM: a real graph-and-tool POC, with a less dramatic result than the abstract suggests

**Who:** Zixuan Xiao, Pei Troh Koh, Jun Ma and Jack C. P. Cheng. **What:** Spatial-Geometric Reasoning for BIM aligns regulation clauses, IFC semantic geometry and user intent through a graph and five agent roles, with an interactive inspection interface. This is primarily fire-safety compliance, not cost estimating. Exact institutional affiliations were not exposed reliably in the retrieved page and are not guessed here. [Original article](https://www.sciencedirect.com/science/article/pii/S0926580526002797).

**Test:** 679 expert-verified questions: 113 rule, 189 rule-requirement, 240 model and 137 compliance-check questions. Comparators include basic/enhanced-tool single agents, CAMEL, MetaGPT and AutoGen. The headline **84.3** is a partial-credit average, not strictly correct-answer percentage: 80.1% correct, 8.4% partial and 11.5% wrong. Enhanced-tool agent partial-credit score is 75.7, so the gain is **8.6 percentage points**, not 8.6% relative. A difficult model-query subset combining relationship and calculation scores 79.0 for SGR-BIM versus 82.0 for AutoGen; gains are not universal. [Tables 1–10](https://www.sciencedirect.com/science/article/pii/S0926580526002797).

**Limits/access:** One run per question; source BIMs were refined for completeness by researchers; deterministic tools assume correctly formatted/preprocessed data. Incomplete synthesis and faulty inference dominate the error analysis. Large dense IFC scalability is unresolved. Appendices expose prompts and mechanisms, but complete source code/data are on reasonable request, not a verified public reproducible package. [Methods, limitations and availability](https://www.sciencedirect.com/science/article/pii/S0926580526002797).

**Why adapt it:** Model a small explicit dependency graph: room use determines assembly requirement; assembly requirement determines relevant BoQ lines; IFC quantities support a deterministic check. First compare with a single agent given the **same tools** before paying for graph/agent orchestration.

### B. Drawing understanding and quantity takeoff

#### Handoff-H1: promising coverage, weaker quantities than humans

**Who:** Bruno Chicelli, Henrique Alves, Rodrigo Anselmo, Joshua Weinberg, Felipe Lemos and Jan Baryla, Handoff AI Research. **System:** Specialized computer vision, image tools, persistent trade hierarchy/knowledge base and verification. Ten residential drawing sets; 2,009 reconciled reference lines, but only 1,348 primary material items scored. Labor and secondary consumables are outside the scored task. [Paper](https://arxiv.org/html/2608.15032).

**Results:** H1 composite 81.6, coverage 86.1 and quantity precision 78.8; independent humans 77.6, 65.5 and 87.9 respectively; best frontier comparison composite 61.4. “Quantity precision” permits **±25%** error. The composite uses coverage to the power 0.4 and precision to 0.6. Ten LLM-judge repetitions and many-to-many matching help reconcile different item granularity, but judge reliability and score design matter. Siding composite is about 65 versus humans 82. This is evidence for recovering more scope, **not** universally superior quantities, correct labor or correct prices. [Benchmark/results](https://arxiv.org/html/2608.15032).

**Access/generalization:** The public repository provides runner/viewer code but not plan PDFs, gold takeoffs or complete result assets; access requires contacting the authors. System weights/prompts/orchestration are not disclosed and component gains are not isolated through ablation. Ten projects are still ten independent units, regardless of line count. Residential and trade-specific conventions limit transfer. [Repository and access instructions](https://github.com/handoffai/residential-takeoff-benchmark).

**Research value:** Persistent scope memory and many-to-many reconciliation are more interesting than reproducing the proprietary system. A local POC should report omission recall separately from quantity accuracy and include labor/accessory exclusions explicitly.

#### LED-BENCH: whole-sheet relation understanding is a separate problem from reading labels

**Who:** Ke Li, Tianyi Wang, Enning You, Chaoqun Wan, Zhen Huang, Shuxian Liang and Xian-Sheng Hua, Tongji University's Institute of AI for Engineering. **Test:** 107 large-format drawings, 377 questions and 11 models across mechanical, architectural and transportation domains; only 21 sheets and 75 questions are architectural. Highest domain-average accuracy is 52.65%, architectural performance 48.89%. [Paper v2](https://arxiv.org/html/2610.19571v2).

**Useful intervention:** In a four-model supplementary experiment, overall whole-sheet performance rises from 36.38 to 49.34 with fixed crops and 49.74 with search/reread. Fixed crops use one call; search/reread three. Project-page architectural scores are 31.03 whole-sheet, 44.83 fixed crops and 53.45 search/reread. Mechanical locate/reread actually falls from 44.12 to 36.47. Relation reconstruction accounts for 47.3% of its coded error sample. More calls are not a universal fix. [Methods/results](https://arxiv.org/html/2610.19571v2), [project page](https://iaie-physicalai.github.io/LED-BENCH/).

**Limits/access:** Human auditing of 90 responses finds 95.6% agreement with its judging setup, but reference-based judging is not independent checking against every original drawing. Questions share sheets and educational-source exposure is possible. As checked, the project says **Dataset Coming Soon**: a code link is not proof of released evaluation data. [Project resources](https://iaie-physicalai.github.io/LED-BENCH/).

**Research value:** Preserve whole-sheet context plus controlled high-resolution views; test counting, annotations-to-object binding and cross-view relations separately. Do not interpret a good QA score as complete quantity takeoff.

#### DrawingVQA: domain priors can override visible evidence

**Who:** Yoonhwa Jung at LSU, Junryu Fu independently and Mani Golparvar-Fard at UIUC; Jung's work was conducted at UIUC. **Test:** 92 expert questions on 33 structural issued-for-construction sheets from six campus projects; 90 multiple-choice questions and two open responses. In this work, “IFC drawing” means **issued for construction**, not an Industry Foundation Classes model. [Paper](https://arxiv.org/html/2607.15418v1).

**Evidence:** Gemini-2.5-Pro scores 71.7%, versus 37.0 without images and random-choice reference 27.2. Vector-PDF input is not uniformly better: Gemini Flash drops from 66.3 to 51.1 in the reported comparison. Adversarial removal of a weld symbol still elicits the conventional all-around-weld interpretation, illustrating prior-driven hallucination. The live project page also lists a newer Gemini-3-Pro-preview score of 77.2; do not mix that rolling leaderboard with the fixed arXiv comparison. [Paper](https://arxiv.org/html/2607.15418v1), [project page](https://joonv2.github.io/DrawingVQA/).

**Access/limits:** Original drawing images are not fully public because of privacy; question text is CC BY-NC-SA 4.0 and leaderboard access is described as forthcoming. This limits reproducibility and commercial reuse. Six projects and largely MCQ evaluation are weak evidence for open-ended takeoff or omission discovery. [Access notice](https://joonv2.github.io/DrawingVQA/).

### C. Adjacent multimodal documents and tables

#### ViDoRe V3: useful retrieval engineering, but retrieval and grounded correctness remain different

**Who:** António Loison, Quentin Macé, Antoine Edy, Victor Xing, Tom Balough, Gabriel Moreira, Bo Liu, Manuel Faysse, Céline Hudelot and Gautier Viaud; includes the ILLUIN Technology–CentraleSupélec MICS LIAGORA collaboration. **Test:** About 26,000 pages in ten professional-domain datasets, 3,099 human-verified queries in six languages, page relevance, answer references and bounding boxes; two datasets held private against benchmark overfitting. Construction is not one of its tested domains. [Full text v2](https://arxiv.org/html/2601.08620v2).

**Results:** ColEmbed-3B-v2 visual retrieval averages 59.8 NDCG@10 versus Qwen3-8B text 51.0 and BM25S 20.3. However, Jina-v4 text plus zerank-2 reaches 63.6, up from 50.4; “visual always wins” is too simple. On hard answer questions with Gemini 3 Pro, hybrid context gives 54.7% versus visual 54.5 and textual 52.1; image-oracle context still reaches only 64.7. The hybrid's 0.2-pp advantage over visual alone is modest and not evidence of a decisive general gain. [Tables 1–3](https://arxiv.org/html/2601.08620v2).

**Failure/access:** Visual grounding F1 on the full set is 0.089 for Qwen and 0.065 for Gemini; even human box agreement is imperfect, so these are not straightforward answer-accuracy scores. Queries include synthetic generation followed by human verification; final references are model-merged and answers LLM-judged. Source-publication exposure and judge effects remain possible. A commercially permissive benchmark release is advertised at [Hugging Face](https://hf.co/vidore); individual assets/licenses still need checking before reuse. [Methods and appendices](https://arxiv.org/html/2601.08620v2).

**Research value:** Compare strong text reranking with visual page retrieval before committing to either. Measure whether a cited region actually supports an extracted fact, not just whether the correct page was retrieved.

#### WildTableBench: dense-table reading is a bottleneck before reasoning begins

**Who:** Junzhe Huang and collaborators across Queensland, Stanford, ANU, Zhejiang, Murdoch and Adelaide, including Xiaoxiao Sun, Serena Yeung-Levy and Xin Yu. **Test:** 928 questions over 402 real-world table images; 21 models across cell lookup, numerical reasoning, verification, hypothetical reasoning and color. Additional positional test uses 2,489 retrieval needles from 50 spreadsheet images. [Paper v2](https://arxiv.org/html/2605.01018v2), [authors/date](https://arxiv.org/abs/2605.01018).

**Results:** Gemini-3-Pro 67.9% overall; Kimi-K2.5 49.9%, GPT-5.2 46.6. Accuracy weakens deeper into rows/columns. Gemini's cell-access-depth scores fall from 83.7% for one-cell questions to 57.3% above 30 cells; question bins are not a controlled causal experiment, but they flag aggregation risk. Locating/recognizing the correct evidence accounts for much of the reported error. [Tables and error analysis](https://arxiv.org/html/2605.01018v2).

**Access/limits:** [Evaluation scripts](https://github.com/hjzhe/WildTableBench) and a linked [dataset](https://huggingface.co/datasets/jzhuang/WildTableBench) are public; no local rerun was done. The visible runner defaults to an LLM judge, which introduces grading dependency. Public web tables may have training exposure; 928 correlated questions are not 928 independent unseen documents. Spreadsheet-image performance is not a reason to rasterize a native BoQ spreadsheet: parse cells and formulas deterministically when available.

**Research value:** Stress-test merged headers, carried units, subtotal rows, negative adjustments and scattered split quantities. The promising direction is structure-preserving extraction plus executable aggregation, not asking a VLM to sum a huge screenshot.

### D. Commercial matching, uncertainty and bid evaluation

#### Al-Derham / Chaudhari / Gao / Senouci: assembly-aware cost selection

**Who:** Hassan Al-Derham, Qatar University; Ruchika Jagannath Chaudhari, Lu Gao and Ahmed Senouci, University of Houston. **POC:** Model content is standardized into estimator-readable descriptions, cost candidates retrieved, then checked for unit, material, thickness, finish and fire-rating compatibility. The cost database remains the source of unit prices, rather than an LLM inventing prices. [Original abstract, published 25 May 2026](https://www.mdpi.com/2075-5309/16/11/2103).

**Evidence boundary:** One BIM example with 7,374 elements but **21 types**, against about 11,500 pricing records. The abstract reports better coverage and technical appropriateness than direct retrieval, but supplies no exact decisive performance table. Full PDF retrieval returned 403, so exact gains, labeling, split protocol and public code/data could not be verified. Treat as an implemented/evaluated POC described by its authors, not a quantitatively confirmed advantage here. [Abstract and PDF link](https://www.mdpi.com/2075-5309/16/11/2103).

**Research value:** This is the right commercial boundary to explore: candidate retrieval plus construction-compatibility filters and explicit abstention. High instance count does not compensate for only 21 distinct matching decisions.

#### RIXBUILD: directly relevant Latvian estimating, weak evaluation disclosure

**Who:** Bagants at BIKUS, Raita Rollande and Juris Klonovs at Ventspils-linked institutions, with Klonovs also associated with BirgerMind. **POC:** Semantic reuse of historical spreadsheet-estimate positions to prefill new estimates, based on about 100 proprietary estimates. [Full journal PDF](https://baltijapublishing.lv/index.php/issue/article/download/4933/4816).

**Claims:** More than 85% semantic matching, 50–70% prefilling and about 70% manual-effort reduction. The article does not provide sufficient model/checkpoint, split, denominator, comparator, timing protocol or uncertainty detail to substantiate these as transferable performance estimates. Training/evaluation separation on the approximately 100 estimates is unclear. No public code or dataset was verified. Its semantic examples grouping different kinds of gates illustrate why lexical/semantic similarity is not necessarily price substitutability. [Methods/examples/results](https://baltijapublishing.lv/index.php/issue/article/download/4933/4816).

**Research value:** Potentially valuable regional collaborator or source of estimator workflow insight. Before relying on the headline, request a blinded project-held-out matching set, incompatible-candidate examples and an actual time study with corrections counted.

#### Fragmented-BIM probabilistic costing: an attractive architecture with fragile calibration evidence

**Who:** Liupengfei Wu, Ruiying Xu and Yiran Zhang at Lingnan; Qian Zhang at Durham; Frank Ato Ghansah at London South Bank; Xichen Chen at Auckland University of Technology. **POC:** GPT-4 Turbo/AutoGen agents reconcile IFC, spreadsheets, quotations and text; a NumPy/SciPy engine runs 10,000 Monte Carlo samples. Three real building cases contain 247, 98 and 386 cost elements. [Full article](https://www.mdpi.com/3042-4720/2/3/8).

**Results:** Entity-resolution accuracy 86.5% versus roughly 46–62% for manual/deterministic/concatenated-LLM baselines; 86.0% empirical coverage for nominal 90% intervals and normalized width 0.28. It reports 4.2 minutes versus 18.5–68.0 in summarized comparisons. But the baseline section separately describes manual probabilistic work averaging 14.3 hours per project, so end-to-end timing denominators are not sufficiently comparable to convert these figures into a productivity promise. Three repetitions do not create additional independent projects. [Methods/results](https://www.mdpi.com/3042-4720/2/3/8).

**What can fail:** Distributions are assigned from three-point/expert ranges or skew assumptions; unresolved cases can receive a default lognormal. Correlations are inferred from historical patterns, with more rigorous copula/Bayesian handling left for future work. Complete project documentation and final actual costs support retrospective testing, but a prospective information cut-off and untouched calibration/test separation were not established in the material inspected. Coverage across elements/repetitions is not proof of total-project calibration on future jobs. Numeric component ablations are limited. Industry data are on request and confidential; a runnable public repository was not verified. [Failure cases, discussion and data statement](https://www.mdpi.com/3042-4720/2/3/8).

**Research value:** Keep deterministic simulation and explicit assumptions; do not infer that LLM-selected distributions are calibrated probabilities. This is worth a small retrospective test only if dated supplier quotes and realized quantities/costs are available.

#### BIM–MCP estimating: automation benchmark, not market-price validation

**Who:** Abdelsalam at Egypt's Housing and Building National Research Center, Ashmawi and Phuong H. D. Nguyen at South Dakota State. **POC:** Revit/MCP and Craftsman-based estimating, with one electrical case of 187 elements in three groups. The abstract reports warm-run 42.3 ± 3.7 seconds over five runs versus 2.5–3.5 hours manually, and a 5.1% difference in total cost. [Publisher abstract, 24 Jan 2026](https://www.mdpi.com/2075-5309/16/3/485).

**Evidence limit:** A cost difference is not automatically an accuracy improvement, and a near-correct total can hide offsetting line errors. Warm-run setup/integration costs and the authority of the manual reference matter. The PDF fetch was blocked, so full baseline protocol, exact code/data access and detailed errors remain unverified. Use this as an integration lead rather than evidence of reliable autonomous estimating.

#### Technical-bid evaluation: criterion-aware retrieval outperforms generic chunks in one small corpus

**Who:** Guozong Zhang, Hongli Zhang and Qianmai Luo, Beijing University of Civil Engineering and Architecture. **Test:** 37 technical bids, five-expert averaged reference scores; DeepSeek-V4-Pro and Qwen3.7-Max; compares criterion/chapter-aware RAG against direct prompting, fixed chunks, TF-IDF, hybrid and semantic alternatives. This evaluates **technical-quality scoring**, not bid profitability or unit-price correctness. [Full article, 8 Oct 2026](https://www.mdpi.com/2075-5309/16/19/3968).

**Results:** DeepSeek score MAE 1.478 versus TF-IDF 6.021; concordance correlation 0.963; reported criterion agreement above 94%. Removing structured chunks yields MAE 10.454 and concordance 0.433. Ranking differences are not statistically significant, despite score gains. Approximately 54–60% of categorized errors involve multimodal information loss in its text-oriented pipeline. [Results/ablation/error analysis](https://www.mdpi.com/2075-5309/16/19/3968).

**Limits/access:** Only 37 bids; threshold selection and independently held-out projects are insufficiently clear to claim generalization. Expert-score reproduction is not outcome utility. Public bid corpus/code not verified; availability points to material in the article or author inquiry. Adapt chapter/criterion structure, but validate ranking with unseen tender families and blind reviewers.

### E. Selective review, latent obligations and future claims

#### Florida contract prioritization: closest research analogue for attention allocation

**Who:** Erfan Moayyed and Chimay Anumba, University of Florida. **POC:** Clause extraction/classification, cost/schedule/cash-flow/dispute weighting, standards alignment, omission checks and constrained contract synthesis. **Test:** 588 clauses from five executed contracts of one public owner; balanced validation subset of 141. [Publisher summary](https://www.itcon.org/paper/2026/46), [full PDF](https://www.itcon.org/papers/2026_46-ITcon-Moayyed.pdf).

**Evidence:** Domain-calibrated classifier macro-F1 0.718 on the balanced subset versus CoT-LLM 0.483; full-corpus F1 falls to 0.572. Annotator agreement κ=0.52. Rankings remain highly stable under weight changes, Spearman >0.98, but the paper explicitly calls the KPI mapping a **heuristic, not an empirically validated predictive model**. A strict missing-provision audit yields 345 flags: 19 confirmed missing, 98 possibly relocated and 228 uncertain. A clause-local failure to find a provision does not establish contract-wide absence. [Evaluation and diagnostic tables](https://www.itcon.org/papers/2026_46-ITcon-Moayyed.pdf).

**Limits/access:** Five contracts from one owner, moderate subjective labels, different reported evaluation subsets and no prospective cost/schedule outcomes. Smart-contract template scores improve 0.8 to 3.6/4 on ten internal pairs, not live deployment. Public corpus/repository not verified. The useful transfer is selective review and whole-document evidence closure, not autonomous contractual execution.

#### Zagreb tender-to-process maps: a fresh way to ask what work the BoQ implies

**Who:** Matej Mihić and Kristijan Vilibić, University of Zagreb Faculty of Civil Engineering. **Test:** Ten Croatian road tenders from one public client, three input variants (documentation, BoQ, both), three runs each: 90 zero-shot process maps with Claude Opus 5.5. Supplementary prompts, maps, validation sheets and scripts are described in the paper. [Full article, 16 Nov 2026](https://www.mdpi.com/2075-5309/16/22/4570).

**Finding:** BoQ inputs produce materially larger maps; adding documentation to the BoQ gives a small admixture, not a complete synthesis. Repeat generations share roughly three quarters of steps but only one third of predecessor relations. All 90 maps render, yet some contain genuine circular dependencies. A SOURCE field makes a claim inspectable; it does not show the source supports that claim. [Results and discussion](https://www.mdpi.com/2075-5309/16/22/4570).

**Important boundary:** All main measures are structural, not correctness; domain-expert validation of generated tasks/sequences is future work. Drawings were excluded from model input, so documentation-only was disadvantaged; input documents were not audited for mutual consistency. Consumer-app model access limits version reproducibility. Single-client Croatian roads and one model restrict transfer. The manual check validates map-to-map semantic matching, not process correctness. [Limitations](https://www.mdpi.com/2075-5309/16/22/4570).

**Research value:** Use a proposed work sequence to ask targeted questions about excavation support, transport, inspections, temporary access and handover. Every inferred task needs separate adjudication: already included, separately measured, genuine omission, or merely a plausible construction method.

#### C2M: retrieve lessons from claims, do not confuse them with prediction

**Who:** Gongfan Chen, UNC Charlotte; Edward Jaselskis, NC State; Alyson Tamer and Andrew Folz, NCDOT. **POC:** BERTopic clusters historical claims/supplemental agreements; an LLM refines topics; multimodal RAG retrieves mitigation guidance from transportation risk/best-practice/lessons databases. Pilot is NCDOT bridge replacement work. Online 25 Nov 2025 qualifies even though acceptance was Aug 2025 and print is Mar 2026. [Original ASCE page](https://ascelibrary.org/doi/10.1061/JCCEE5.CPENG-6754).

**Accessible evidence:** The abstract reports utility relocation, plan/design/method problems, pavement and underground utilities as recurring themes and says timely multimodal mitigations were validated. It does **not** provide a decisive quantitative comparator, sample size or predictive-performance metric. Full text is paywalled; data/models/code are on reasonable request. No stronger result is inferred here. [Abstract/history/data statement](https://ascelibrary.org/doi/10.1061/JCCEE5.CPENG-6754).

**Research value:** Retrieve a similar past failure together with its trigger conditions and the exact tender evidence. Similar historical claims can motivate a reviewer question, not establish causation or the probability of a new claim.

#### Oh–Ashuri change-order impact profiling: strong reported scores on the wrong information horizon for prebid use

**Who:** Jeongyoon Oh and Baabak Ashuri. **Test:** 1,271 change orders from 72 transportation projects, starts 2010–2023 and completion through 2025; models predict whether and how much an issued change order affects cost/schedule. Variables include construction progress, change sequence, reason, season, original contract features and highway cost index. [Full ESWA article](https://www.sciencedirect.com/science/article/pii/S0957417426009437).

**Results:** Random forest schedule F1 0.905/AUC 0.997; cost F1 0.960/AUC 0.960, outperforming logistic regression, SVM and competitive XGBoost. These are impact classifications conditioned on known change information, not forecasts of unseen change orders from a prebid BoQ. The raw data are highly imbalanced: 86.8% of changes have no schedule impact. [Methods/results](https://www.sciencedirect.com/science/article/pii/S0957417426009437).

**Concerns:** Five-fold CV and preprocessing with bootstrapping/SMOTE are described; project-grouped validation and fold-local resampling could not be established. This is a leakage **risk**, not a proven error. Repeated records share project context; a documented reason may partly encode the outcome. SHAP explains model association, not causal mechanisms. Data are on request. Exact first-online date and institutional affiliations were not independently resolved. [Methods/data statement](https://www.sciencedirect.com/science/article/pii/S0957417426009437).

**Research value:** A possible later-stage change-control assistant. For bidding, strip every post-award variable, split by entire project and time, and expect the headline performance to drop.

## Older foundations and recent republications

These inform the research direction but should not be sold as discoveries originating inside the requested window.

- **MMTabReal**, Prasham Titiya, Jainil Trivedi, Chitta Baral and Vivek Gupta, ASU CoRAL: first preprint **27 May 2025**, updated **23 May 2026**, peer-reviewed ACL Findings **July 2026**. 500 real multimodal tables/4,021 QA, with missing-image, entity-replaced, caption, whole-image and interleaved baselines. For GPT-4o-mini, visual-question EM is 38.56% whole-image and 40.39% interleaved, versus a human-subset 79.9%; human subset is not a directly matched full-dataset ceiling. The entity-replaced baseline tests the cost of visual recognition rather than real deployment. Useful stress tests for icons, colors and structure; dated model mix is not today's frontier. Evaluation-only release is stated; check licensing and avoid training on its evaluation set. [Date history](https://arxiv.org/abs/2505.21771), [paper v2](https://arxiv.org/html/2505.21771v2), [ACL](https://aclanthology.org/2026.findings-acl.2047/), [project/code](https://coral-lab-asu.github.io/mmtabreal/).
- **CEQuest**, Yanzhao Wu, Lufan Wang and Rui Liu: first preprint **22 Aug 2025**. Construction drawing/estimation QA comparing five LLMs, not a new 2026 autonomous estimator. The original abstract promises an open release; release was not independently verified in this research. Retain as a domain-QA foundation, not evidence for complete estimating. [Original abstract/history](https://arxiv.org/abs/2508.16081).
- **Blueprint-Bench**, Lukas Petersson, Axel Backlund, Axel Wennstöm, Hanna Petersson, Callum Sharrock and Arash Dabiri: first preprint **24 Sep 2025**. Fifty apartments, about 20 photographs each, photo-to-floorplan reconstruction scored on connectivity and room-size ranking. The abstract reports most models at/below random and no meaningful iterative-agent gain. This is not parsing existing construction drawings, and “submitted to ICLR 2026” is not verified acceptance. Useful as a warning against assuming spatial reconstruction follows from fluent text reasoning. [Original abstract/history](https://arxiv.org/abs/2509.25229).

## Experiments worth trying, in priority order

These are **proposed experiments**, not capabilities established by the papers. Effort estimates assume one engineer, existing document extraction/API access and part-time estimator involvement; procurement, licensed cost data and expert labeling can dominate elapsed time. They are not production-delivery estimates. Freeze evaluation projects before prompt/rule tuning. Report clustered uncertainty by project, not by treating every row as independent.

### 1. Evidence-backed discrepancy queue with explicit abstention

**Question:** Can a reviewer find more genuine high-impact errors in the same review time than with arithmetic/unit checks and keyword search?

Use public or permissioned BoQ + specs + drawing packs. Include natural defects, clean controls and separately labeled injected defects. Extract candidate inconsistencies; require two-sided evidence for contradictions and document-wide search coverage before alleging absence. Preserve Confirmed issue / Consistent / Insufficient evidence / Needs interpretation states. Arithmetic and unit conversions run deterministically. Motivated by [AEC-Bench](https://arxiv.org/html/2603.29199) and [constraint-checking failures](https://arxiv.org/html/2607.29058v1).

**Baselines:** deterministic checks; BM25 plus reviewer; single-pass LLM; evidence-contract variant with the same model and budget. **Measure:** adjudicated precision, issue recall, false reassurance on clean/unknown cases, supported citations and reviewer minutes. **Kill criterion:** the sophisticated variant cannot beat the strongest simple baseline under equal review time, or frequently declares “safe” without evidence. **Effort estimate:** 1–2 weeks for a narrow trade POC; longer for credible labels.

### 2. Many-to-many quantity reconciliation, with construction boundaries preserved

**Question:** Can split quantities be combined without merging incompatible assemblies or double counting?

Build a small adjudicated set of one-to-many and many-to-many groups: repeated floor/zone lines, separate supply/install items, accessories already included in a rate, alternative specifications, provisional sums, credits and revised quantities. Represent unit basis, assembly/specification, location, phase and inclusion/exclusion separately. Use an LLM for proposed links, executable unit-aware sums and conservation checks for totals, and explicit unresolved groups. Motivated by [Handoff's reconciliation](https://arxiv.org/html/2608.15032) and [assembly-aware costing](https://www.mdpi.com/2075-5309/16/11/2103).

**Baselines:** exact codes; normalized descriptions plus units; embedding clustering; guarded linking. **Measure:** group precision/recall, total-quantity error, double-count rate and human correction effort. Score supply-only versus installed assemblies as adversarial negatives. **Kill criterion:** gains in recall come from dangerous false merges. **Effort estimate:** 1–2 weeks with 100–200 carefully labeled groups. This is a research target; the reviewed literature does not establish robust multilingual split-BoQ aggregation.

### 3. Reviewer-budget ranking, including vague low-price scope

**Question:** Which 20 items should a person inspect first among thousands?

Compare sorting by extended price, generic anomaly score, rules and learned/pairwise rankers. Include uncertainty, cross-document disagreement, dependency reach and scope vagueness, but do not assume their weights are validated. Add diversity so the queue is not 20 variants of the same issue. Give hidden/unknown-price scope its own route rather than treating zero price as zero impact. Motivated by the [Florida heuristic](https://www.itcon.org/paper/2026/46), which does not yet demonstrate attention-allocation utility.

**Measure:** recall of adjudicated important issues at top 10/20/50, cost-weighted recall using independently adjudicated ranges, duplicate burden, reviewer time and accepted/rejected reasons. Randomize/counterbalance reviewer order to reduce anchoring. **Kill criterion:** rank stability improves but important-issue recall does not beat simple price/rule ordering. **Effort estimate:** 2–3 weeks, largely annotation. High-risk extension: learn preferences across estimators; it may fail because commercial priorities differ by trade and contract strategy.

### 4. Equal-budget evidence breadth versus resolution

**Question:** Do whole pages, fixed crops, search/reread or hybrid text/image retrieval win on unseen projects?

Use identical tasks/models and cap image count, pixels/tokens, calls and money. Include cross-sheet references where cropping may hide the governing note, and dense schedules where full-sheet downsampling loses values. Include native table extraction as a control. Compare text retrieval with reranking, visual retrieval and combined context; rerun at least a sample to expose stochastic variance. Motivated by [LED-BENCH](https://arxiv.org/html/2610.19571v2), [ViDoRe](https://arxiv.org/html/2601.08620v2) and the [failed breadth transfer](https://arxiv.org/html/2607.29058v1).

**Measure:** relevant-evidence recall, grounded final accuracy, supported-region correctness and cost/latency, all on project-held-out data. **Kill criterion:** crop/search advantage vanishes after equal budget or whole-project holdout. **Effort estimate:** 3–5 days once documents and labels exist. This is an inexpensive experiment with high architectural leverage.

### 5. Claims-to-scope retrieval instead of unsupported claim probabilities

**Question:** Can past claims identify useful questions about today's vague scope?

Retrieve historical cases with analogous triggers: utility interfaces, temporary works, testing, access restrictions or approvals. Output the past trigger, its differences from the current job, present tender evidence, missing information and a reviewer question. Separate cause, observed claim, mitigation and contractual entitlement. Motivated by [C2M](https://ascelibrary.org/doi/10.1061/JCCEE5.CPENG-6754).

**Baselines:** risk checklist; keyword search; retrieval without generation. **Measure:** blind estimator usefulness, novel actionable questions, citation support and false equivalences. Avoid outcome descriptions as predictive inputs. **Kill criterion:** generated questions are generic checklist restatements or misapply another jurisdiction's entitlement. **Effort estimate:** 1–2 weeks if a usable public/permissioned case corpus exists; data access is the main risk.

### 6. Reverse scope audit from construction process and obligations

**High-risk idea:** Generate plausible operations/obligations from specs and drawings **without first seeing the BoQ**, then reconcile them to BoQ items. This may expose scope hidden by a BoQ-led reading order. It can also hallucinate an entire construction method. [Zagreb's input-dominance findings](https://www.mdpi.com/2075-5309/16/22/4570) motivate testing this rather than assuming a combined-input prompt synthesizes everything.

Compare BoQ-first, spec-first and independently generated obligations with an estimator checklist. Require every candidate to be tagged explicit requirement, method-dependent inference or unsupported. Review whether it is already included in another rate before calling it omitted. **Measure:** confirmed missing obligations/scope, unsupported additions, duplicate/included-rate flags and time per true discovery. **Kill criterion:** most “missing” work is already included or merely an optional method. **Effort estimate:** 1–2 weeks for one road or renovation trade; credible correctness requires domain experts.

### 7. Price-compatible retrieval and calibrated what-if, not generated prices

Normalize compatible assemblies and retrieve dated regional supplier/rate evidence. Keep quantity uncertainty, scope uncertainty, price uncertainty and productivity assumptions separate. Start with simple historical ranges and deterministic scenario calculations before adding LLM-selected distributions. Compare embedding-only matching against assembly/unit filters and against an estimator. Motivated by [Houston/Qatar](https://www.mdpi.com/2075-5309/16/11/2103) and the [fragmented-BIM POC](https://www.mdpi.com/3042-4720/2/3/8).

**Measure:** incompatible-match frequency, accepted candidate recall, line-level error and total bias; evaluate intervals on future dated jobs with coverage **and** width/proper scoring, including shared escalation/currency factors. **Kill criterion:** attractive totals conceal offsetting line errors, or nominal intervals under-cover held-out projects. **Effort estimate:** 2–4 weeks if licensed historical evidence is ready; otherwise not a quick POC. Never call semantic match rate price accuracy.

### 8. A minimal graph for one latent dependency

**High-risk idea:** Test one dependency chain such as room use → fire/acoustic requirement → compatible partition assembly → linked BoQ quantities, including exceptions and missing attributes. Use typed edges with source/revision provenance and deterministic quantity checks. Compare a graph-backed system to a single agent with the same retrieval/IFC tools and to a small hand-authored rule set. [SGR-BIM](https://www.sciencedirect.com/science/article/pii/S0926580526002797) supports testing structured alignment, not building a universal construction ontology first.

**Measure:** held-out dependency decisions, missed exceptions, unjustified joins, trace support and maintenance effort. **Kill criterion:** manual graph maintenance exceeds review savings or its gains disappear against a well-equipped single agent. **Effort estimate:** 2–4 weeks for a narrow chain; a cross-trade ontology is a substantially larger program.

## What would make the next result believable

- **Independent units:** Hold out whole projects, owners and document templates; later test another language/jurisdiction. Thousands of lines from one model are not thousands of independent jobs. This concern is concrete in Handoff's ten projects, Florida's five contracts and Houston's 21 types.
- **Information timing:** For risk/price prediction, freeze what was known at bid date. Actual final costs, issued change reasons, later RFIs and construction progress cannot silently enter a prebid feature set. The Oh–Ashuri task explicitly operates after change information exists.
- **Natural prevalence:** Separate clean documents, real defects and seeded defects. Report precision at natural prevalence and keep an “unresolved” state; synthetic benchmark gains alone cannot establish commercial review utility.
- **Gold quality:** Use independent estimators and adjudication, with disagreement retained. Florida's κ=0.52 illustrates genuine interpretation uncertainty. An LLM judge or stable repeated answer is not equivalent to an expert-verified obligation or quantity.
- **Cost of correction:** Count setup, source normalization, user correction and evidence checking, not just warm inference. Record API/version/budget and rerun a sample. A faster first draft may take longer to audit.
- **No hiding behind totals:** Report missed scope, wrong quantities, incompatible rates and unsupported judgments separately. Handoff's composite and the BIM–MCP total difference answer narrower questions than “is the estimate correct?”
- **Commercial outcome:** Until prospective validation exists, evaluate accepted issues, time saved and documented decisions. Do not label a risk score expected loss, or infer that an error flag prevents a claim.

## Evidence gaps and inaccessible material

**Most consequential gap:** Among the sources inspected, no publicly reproducible system demonstrates generalizable end-to-end detection of natural BoQ errors, vague costly omissions, cross-item aggregation and profitable commercial bidding across independent project types. This is a statement about this research set, not proof that no such work exists anywhere.

**Access gaps:** Handoff's gold plans/takeoffs are request-only; DrawingVQA withholds original drawing imagery; LED-BENCH says dataset forthcoming. C2M substantive full text is paywalled. The two Buildings cost-estimating PDFs (16/3/485 and 16/11/2103) returned 403, limiting them to publisher-abstract evidence. SGR-BIM source/data and several project-specific commercial/contract datasets require author requests. A public project page or repository does not establish reproducibility of the reported experiment.

**Verification gaps:** No local reproduction, code execution, dataset download or license audit was performed. Some full-text HTML responses were long/truncated; targeted methods/results/limitations sections were then retrieved, rather than assuming an omitted section supported a claim. Exact first-online dates for SGR-BIM and Oh–Ashuri, independent proceedings confirmation for DrawingVQA and some institutional affiliations remain unresolved. Code/data release claims are distinguished from resources actually inspected. No paid access or author contact was used.

**Coverage gaps:** Robust semantic aggregation of split BoQ lines, human-in-the-loop top-k ranking, bidder-specific margin/strategy and naturally vague expensive scope remain less directly evaluated than document QA or clause classification. The report deliberately gives them experiment proposals rather than filling the gap with unrelated model metrics. Likewise, claims-derived retrieval is better supported here than prebid causal change-order prediction.

**Bottom line:** The research opportunity is a reviewer who can efficiently inspect evidence across documents, preserve assembly and quantity boundaries, and decide what deserves attention. The highest-risk leap is converting fluent reconciliation or a plausible process map into a confident statement that all scope, prices or future risks are covered.
