# BoQ competitor landscape

**The opportunity is a trustworthy, materiality-ranked review of tender scope and quantities inside the estimator’s existing workflow; generic “AI that finds LV errors” is already a crowded proposition.**

Research date: **20 November 2026**. German-first, with Austrian, Swiss and international comparisons. Prepared for an AI Estimation and Bidding Assistant for Bills of Quantities: error detection first, then scope/quantity risk and change orders, with pricing and what-if analysis optional. This is a useful landscape, not an exhaustive market census or procurement recommendation.

## Executive synthesis

**The closest competitors are not the two starting examples alone.** Kuro, Tenderhub/revitalyze, Arctis AI, SCAIT, baugenic and BAUIGEL directly address tender risk, missing scope or quantity relationships. Reiner AI and BauGPT offer broader construction-specific AI workplaces that can absorb the same use case. Cosuno combines procurement distribution, LV risk and pricing. Phase0, SIDOUN and NOVA put AI directly inside AVA workflows. Internationally, Provision, Document Crunch and Trunk Tools increasingly connect scope, documents, revisions and commercial risk.

**Comstruct is primarily an adjacent procurement and execution-data business.** Its current site explicitly says the contractor retains cost calculation as its competitive advantage, while agents handle downstream work. Its supplier connectivity, delivery notes and invoice reconciliation are more relevant as lessons in integration and potential actual-cost feedback than as proof of a competing engineering checker.

**The most important distinction is who makes which decision.** A contractor deciding whether and how to bid, a client checking incoming offers, a manufacturer matching products to specified positions, and an estimator measuring drawings may process the same LV but have different objectives and budgets. Calling all of them “BoQ AI competitors” obscures real competition. The profiles below distinguish these buying situations.

**Several proposed differentiators already have public precedents.** Tenderhub explicitly advertises aggregating dispersed concrete quantities; SCAIT describes mass balances and concrete/rebar ratios; Kuro describes company-specific cross-document checking; Provision addresses inferred and cross-trade scope; NOVA demonstrates grouping quantities from CAD lists. The open opportunity is demonstrated quality, commercial prioritization, bounded coverage and low review burden, rather than claiming nobody handles relationships between positions.

**The strongest plausible moats sit around workflows and validated decisions.** Company rulebooks, product configuration knowledge, historical bid/award records, supplier connectivity, integration depth and accepted issue resolutions can compound. Merely using a construction-tuned language model or possessing customer documents is weaker evidence of defensibility. Data ownership, licensing and no-cross-customer-training commitments limit simplistic “every upload improves our global model” stories.

**Recommended prototype direction:** an independent tender-review layer for a clearly defined contractor segment, initially one or two trades. Deliver a short, ranked issue queue with exact position/document references, reproducible quantity reasoning, explicit assumptions, an exposure range where justified, and the next action: clarify, reserve, price, investigate or monitor. Preserve GAEB identity and make Excel/PDF export useful before attempting to replace AVA/ERP. Treat this recommendation as a hypothesis to test with buyers, not a proven unoccupied niche.

## How to read the evidence

- **Documented capability** means a current primary product page, help document, named customer case or public demonstration describes it. It does **not** mean this research executed the software or validated accuracy.
- **Vendor/customer claim** identifies claimed results, adoption, accuracy, security or scale. A customer quote hosted by the vendor is stronger than an anonymous slogan but is not an independent benchmark.
- **Independent evidence** includes reporting by TechCrunch, Tech.eu, ENR and trade press; financing coverage corroborates a transaction, not product quality. Investor material is identified as such. A regulatory filing is strong evidence for an acquisition.
- **Moat inference** and **structural limitation** are analysis. They are not allegations of private technical failures, churn, financial distress or internal struggles.
- **Not verified** means not established in the reviewed sources, not proof the feature does not exist. Logo walls do not establish deployment size, paid usage or the scope of a customer’s use.

Live product pages were checked during this research on 20 November 2026. Dated sources retain their original date; undated pages are a snapshot, not evidence of when a feature launched. No confidential project material, local project checkout or private customer data was used. No product was benchmarked hands-on.

## Where companies actually compete

| Buying situation | Relevant companies | Competition with the proposed assistant |
| --- | --- | --- |
| Contractor reviews tender documents before committing price and scope | Kuro, Tenderhub, Arctis, SCAIT, baugenic, BAUIGEL; international Provision | Closest overlap: identify omissions, contradictions, obligations and quantity/scope risks |
| Construction-specific AI workplace | Reiner AI, BauGPT | Competes for the same user’s attention and AI budget; depth of each check needs testing |
| Client/planner authors LVs and evaluates offers | Klava, Phase0, SIDOUN, NOVA; established RIB/ORCA ecosystem | Some same checks, but buyer-side completeness, compliant award and authoring differ from contractor margin protection |
| Contractor sources and compares subcontractors | Cosuno, Arctis; TrunkBid internationally | Strong overlap when risk becomes package coverage, exclusions and bid leveling |
| Manufacturer/dealer produces a compliant product offer | Scalera, kinisto, Tendos, Workist | Competes on LV extraction and matching, usually not whole-project engineering risk or contractor entitlement |
| Estimator measures drawings and assembles estimates | Kreo, Togal, Beam AI; ConCntric for cost planning | Quantity and estimate inputs; not interchangeable with contractual scope checking |
| Procurement, delivery, invoices and actuals | Comstruct, VESTIGAS, Kojo, Qflow; Alasco on owner finances | Adjacent systems, possible data/integration partners, with expansion risk into reconciliation |

The dividing line is not permanent. Cosuno and Arctis already span several rows; Trunk Tools has moved into preconstruction; AI inside AVA reduces the room for a standalone assistant to charge for basic checking.

## German-first tender and risk specialists

### Kuro — the clearest enterprise general-contractor benchmark

**Buyer/workflow.** German general contractors and their estimating/preconstruction teams. The [product site](https://www.kuro.technology/) describes contradictions across plans, specifications and LVs; company rules and a context graph; cited findings; version handling; room-book/Revit workflows; and converting PDF offers to GAEB while identifying deviations.

**Why interesting.** The [Köster case](https://www.kuro.technology/referenzen/koester) describes configuring more than 1,000 questions across over 40 trades with experts, a Revit interface and testing on historical projects. It reports about six hours saved per estimator per week in a survey. This is evidence of detailed implementation work and named adoption, not a measured recall rate for hidden scope.

**Traction/freshness.** [UVC Partners, 30 September 2026](https://www.uvcpartners.com/blog/eu10-million-for-kuro-germanys-largest-general-contractors-bet-on-this-berlin-based-ai-company-) announced €10 million and reported 12 customers including six of Germany’s top 20 general contractors. UVC is an investor, so its time-saving and discovery statistics remain interested-party claims. [Startbase’s dated reporting](https://www.startbase.de/news/10-millionen-euro-finanzierungsrunde-fuer-kuro) provides a separate financing report.

**Moat inference / limits.** Expert-configured rulebooks, accumulated accepted findings and embedded project/BIM context could be durable. The same customization can create onboarding and maintenance work. Exact GAEB generations/versions, preservation fidelity and performance on unseen trades were not established. **Prototype lesson:** firm-specific rules and evidence-linked review are a competitive baseline, not a unique pitch.

### Tenderhub / revitalyze — unusually close to the proposed quantity-and-scope lens

**Buyer/workflow.** Austrian/DACH contractors and tender teams. The current [Tenderhub site](https://tenderhub.tech/), reached through [revitalyze](https://revitalyze.io/), describes reviewing tender packages for contradictions and missing LV scope, identifying change opportunities, generating GAEB and exporting comparisons/scope matrices. It explicitly advertises aggregating quantities across positions, including concrete types. PlanReader adds PDF counting/measurement and DIN 276 outputs.

**What is good.** The presentation connects extraction to an economically useful question rather than stopping at document search. This is one of the closest public precedents for dispersed related quantities.

**Claims / limits.** The site claims 300+ projects and €2 billion reviewed. Its anonymous 620-page electrical example attributes a €71,000 submitted change to a KNX mismatch; submission is not award or cash recovery. Public pricing is €0.40 per page net, with an initial free allowance and custom annual arrangements. These are a dated site snapshot, not a guaranteed quotation. Exact GAEB versions and deep integration behavior were not established.

**Moat inference.** Trade-specific checks and labeled outcomes could compound. Page-based economics and dense tender appendices could create cost/usage friction, but no customer dissatisfaction was established. **Prototype lesson:** compare against its quantity aggregation and action-oriented findings, not just chat quality.

### Arctis AI — risk review connected to sourcing and bid leveling

**Buyer/workflow.** Contractor commercial, estimating and procurement teams. The [German product site](https://arctisai.com/de) and [Tender page](https://arctisai.com/de/tender) describe review against VOB and company standards, risks and questions, LV-to-package preparation, sourcing, and evaluation of offers for missing or excluded scope. Historical pricing and spreadsheet-oriented outputs extend it beyond contract chat.

**Why interesting.** A risk matters more when it changes the package sent to subcontractors or the decision made in a comparison. Arctis aims to own that chain. SAP, SharePoint, Procore and other integrations appear in marketing; the exact connector operations and write-back were not tested.

**Independent context.** [Tech.eu, 27 January 2026](https://tech.eu/2026/01/27/1m-raise-for-arctis-ai-the-construction-focused-ai-startup-led-by-former-fencing-champion-dila-ekrem) reported a $1 million-plus PT1-led round. That article’s contract-risk positioning is narrower than the current product suite; it should not define the November product boundary.

**Moat inference / limits.** Historical comparisons and integrated sourcing may produce stronger decision data than isolated flags. Breadth also creates implementation complexity. German GAEB versions, independently measured issue precision and current paying-customer scale remain unverified. **Prototype lesson:** make findings flow into bid preparation and scope comparison without needing to build a complete sourcing suite.

### SCAIT — the strongest explicit quantitative-checking reference, with Swiss boundaries

**Buyer/workflow.** Swiss construction companies reviewing submissions, quantities and contractual terms. [SCAIT](https://www.scait.ch/) and its [LV-specific page](https://www.scait.ch/leistungsverzeichnis) describe mass balances, concrete/reinforcement ratios, trade-specific review and hidden contractual conditions within positions, with references. SIMAP ingestion and knowledge/task workflows broaden the offering.

**What is good.** It translates “plausibility” into concrete relationships and review rules. This is more relevant to engineering checks than general claims of construction AI expertise.

**Documented limitation.** The LV page says quantity checks require a file following Swiss norms; text/functional specifications need case-by-case assessment. Ratios still require professional interpretation. Swiss NPK/SIA familiarity must not be treated as evidence of German GAEB/VOB readiness.

**Claims / moat inference.** SCAIT describes an SBV/Construix relationship in [an April 2026 announcement](https://www.scait.ch/post/scait-sbv-vertragsanalyse-jetzt-in-construix); independent confirmation of the commercial scope was not established here. Association distribution and expert rules could be valuable. **Prototype lesson:** explicit coverage boundaries can strengthen trust; do not silently apply one trade or country’s ratios to another.

### baugenic — trade-specific risk and the route from finding to correspondence

**Buyer/workflow.** Contractors and site/commercial managers. The [product site](https://baugenic.de/) describes LV/contract risk reports with severity and references, cross-position material incompatibilities, hidden contaminated-soil disposal exposure and preparation of relevant correspondence. Its Boden & RC specialization invokes EBV/BBodSchV requirements.

**What is good.** It frames risks as concrete construction and commercial decisions rather than legal summarization alone. Soil classification, reuse and disposal are promising examples because expensive scope can be distributed across positions, preliminary clauses and technical reports.

**Limits.** Public examples are illustrations, not validated engineering findings. Whether a recycled material is actually prohibited depends on the specification, classifications and applicable facts. No independent detection benchmark, precise GAEB support matrix or integration specifications were found. The site advertises a trial, quote-based pricing and an enterprise on-premise option; availability and deployment conditions were not tested.

**Moat inference.** Maintained trade rules and professional credibility could matter more than the base model. Regulatory upkeep and false-positive control are structural burdens, not demonstrated company failures. **Prototype lesson:** narrow expertise plus a practical next-action draft may be more persuasive than broad coverage promises.

### BAUIGEL — a human-reviewed service, not merely another SaaS checker

**Buyer/workflow.** Contractors seeking prioritized LV risk/change-order analysis. [BAUIGEL](https://bauigel.com/) offers AI plus engineering review, a report within ten working days, exclusivity to one party per LV and a no-findings/no-invoice proposition.

**Why interesting.** Human review and exclusivity address trust and conflicts directly. An anonymized historical **2012** example describes 68 documents and 828 items: approximately 3,400 m³ excavation minus 500 m³ reuse leaves roughly 2,900 m³ to account for in disposal, with an estimated minimum €14,000 exposure. That is a useful problem archetype; it is not evidence of a 2026 project or collected recovery.

**Claims / limits.** Historical change-detection comparisons are internal claims with no independently validated denominator or holdout set. Ten-day service delivery is different from instant bid-day interaction.

**Moat inference.** Expert adjudication and completed review cases could create a high-quality learning corpus, subject to rights. Human cost and latency constrain scaling. **Prototype lesson:** a reviewed pilot service may establish value before fully automated SaaS; report potential exposure separately from legally recoverable entitlement.

## Broad construction AI and AVA platforms

### Reiner AI — a domain workplace with LV checking inside a larger engineering job

**Buyer/workflow.** Planning and engineering offices. The [current site](https://www.reiner.ai/) describes checking/pricing LVs, offer comparison, VOB-related changes and final invoices, reports and support involving DIN, DWA and HOAI. It advertises source-backed specialist knowledge, multiple model providers and enterprise document sources including SharePoint/Drive/uploads.

**What makes it good.** Distribution through everyday technical knowledge work can make an LV checker feel like an incremental use case, not a new system. The named Siekmann + Partner testimonial describes a 70-page report reduced from about 30 hours to three, with further editing. That is report-production evidence; it says nothing directly about LV error recall.

**Moat inference / limits.** Domain content, customer context and adoption could be defensible. The corpus’s exclusivity, licensing breadth and performance relative to generic retrieval were not independently established. Frankfurt hosting/no-training statements are vendor commitments, not a completed security audit. Exact GAEB versions and lossless LV round trips were not verified. A recent page date must not be read as a product launch date. **Prototype lesson:** buyers may already have a construction assistant; demonstrate why the specialist review finds important issues reliably enough to deserve separate use.

### BauGPT / Crafthunt — practical GAEB workflows and a fresh quantity-checking signal

**Buyer/workflow.** Construction firms using AI across office and site tasks. The [use-case pages](https://baugpt.com/pro/use-cases) and [LV documentation](https://docs.baugpt.com/docs/anleitungen/leistungsverzeichnisse) describe reading LVs, risk/questions, pricing/export and GAEB workflows. The help documentation explicitly names X81/X83/X84 and D81/D83/D84; other feature material advertises additional formats. SharePoint, Google Drive, Microsoft Entra and PlanRadar are listed in the broader ecosystem.

**Freshness.** [BAU trade press, 13 November 2026](https://bau.bi/baumagazin/betriebsfuehrung/bau-2027-mengenpruefung-per-ki-baugpt-gleicht-aufmass-und-gaeb-dateien-ab-b22705), describes quantity reconciliation between measurement and GAEB files for a planned **11–15 January 2027** BAU presentation. This is a future demonstration as of this report, not a completed event. [Baulinks, 2 July 2026](https://www.baulinks.de/webplugin/2026/0937.php4), reports X83 export.

**Moat inference / limits.** Construction distribution, practical file handling and usage context could matter. Registered-user totals and illustrative discrepancy examples are not paid adoption or accuracy benchmarks. Export availability does not establish all-format preservation. **Prototype lesson:** GAEB support alone is not differentiation; compare review quality and quantity reconciliation directly.

### Cosuno — procurement distribution plus risk and pricing, not just a marketplace

**Buyer/workflow.** General contractors and owners organizing subcontractor procurement. The [current German site](https://www.cosuno.com/web/de) includes LV risk analysis, supplier sourcing, offer comparison, pricing assistance and subcontract/change workflows. Its [AI page](https://www.cosuno.com/web/de/cosuno-ki) claims access to seven million price data points. RIB iTWO, SAP, NEVARIS and BRZ appear among integration claims.

**Why interesting.** A platform through which tender packages and responses already flow can put checking at the decision point and gather comparable offer history. Vendor-hosted ALDI Süd/Haas references support named use, not an independently measured detection advantage.

**Moat inference / limits.** Network distribution and bid/price history are more substantial potential moats than generic AI. Counts of positions or prices do not establish normalized scope, geographical coverage or relevance to a specific trade. Current public bidder totals differ between site variants, so no precise present network count is asserted here. Linked historical GAEB certificates should be checked for their exact software version and certified scope. **Prototype lesson:** avoid competing on generic price lookup or supplier discovery first; integrate or export into procurement decisions.

### Klava — offer and award checking from the client side

**Buyer/workflow.** Planners, clients and project managers evaluating tenders. [Klava](https://www.klavaai.com/) describes checking alignment of preliminary clauses and positions, missing offer items, lump-sum scope, price outliers using MAD, EFB 221/222/223 forms and a documented decision/award record.

**What is good.** The output fits an accountable award process rather than an open-ended chat. The site explicitly states **GAEB DA XML 3.2/3.3, X83/X84**, unusually specific public compatibility information for an early product.

**Maturity limitation.** Starter/demo access is presented, while Professional/Enterprise are waitlisted. Position drafting is marked forthcoming; API/SSO and a unit-price database appear in future-facing material. Do not convert the broad full-AVA positioning into proof every module is generally available. Hosting-provider ISO certification is not automatically certification of Klava itself.

**Moat inference.** An accepted audit/disposition workflow could create retention. Independent adoption and actual check performance remain unverified. **Prototype lesson:** keep a decision log and exportable reasons; contractor-side risk analysis and public/client-side award compliance need different language and success measures.

### Phase0 — a very recent integrated LV agent with actual bid-price provenance

**Buyer/workflow.** Small and medium architecture/engineering offices. The primary [9 November 2026 announcement](https://www.phase0.com/presse/ki-agent-leistungsverzeichnisse-ava-software) says beta has ended and an agent is integrated into its cloud AVA software for LV drafting, checking and pricing. It describes GAEB import, PDF tables/lists including quantities, targeted questions for missing information, VOB/norm checks, direct table editing and version history.

**What is good.** It combines firm history, project context and price provenance. Price suggestions use medians from comparable offered positions and show their source. The vendor reports approximately **5,000 LVs / 230,000 positions** in its database and more than 1,000 offices using the overall platform. Those are vendor counts, not an audit of usable comparable samples or paid AI adoption.

**Moat inference / limits.** Workflow distribution and real tender returns could compound. Price comparability still depends on technical scope, date, location and procurement conditions. Detailed GAEB generation coverage and AI error rates were not established. **Prototype lesson:** provenance and clarification are already in-market features; generic price suggestions face an installed-workflow competitor with transaction-derived data.

### SIDOUN KIAVA and NOVA NEO — incumbent workflows are becoming active competitors

**SIDOUN.** The [KI assistance page](https://sidoun.de/loesungen/kiava/ki-assistenz/) describes IILSE domain/company knowledge, DAss multi-source position search, text creation, translation and LV checks for ambiguities, contradictions, risks and change traps, with human control. SIDOUN also describes setting up a company knowledge space and training the customer to maintain it. **Moat inference:** installed AVA context, internal knowledge and low workflow switching. **Limit:** public descriptions do not independently prove detection quality or seconds-to-completion on large projects.

**NOVA.** The [NEO page](https://nova-ava.de/neo-baukosten-ki/) labels the assistant **beta**. It describes VOB/A/B/C checking, PDF-to-LV conversion, grouping CAD component lists by attributes and quantities, DIN 276 assignment and direct project actions. MCP/OAuth is offered for external AI access; NEO is said to be included in NOVA packages, with the MCP add-on free during beta. The [main platform](https://nova-ava.de/) already includes GAEB/ÖNORM import, BIM and the SmartPool of previously commissioned positions. **Moat inference:** transaction context and bundling put pressure on standalone basic checking. **Limit:** beta status matters, and product-page demonstrations are not evaluated engineering accuracy. Advertised BIM World **24–25 November 2026** and BAU January 2027 appearances are future events at the research cutoff.

**Other established boundaries.** [RIB’s data-library page](https://www.rib-software.com/de/rib-itwo/ava-software/datenbibliothek) documents BKI, DBD, STLB-Bau and sirAdos connections. [ORCA’s AVA comparison](https://www.orca-software.com/ava-software-vergleich) illustrates established GAEB/IFC-centered workflows. Licensed specification/cost libraries, long-lived project data and trust are relevant competitive assets. This report does not claim that every incumbent has the same AI features, or that any is an AI-free legacy product.

## Manufacturer and supplier quoting: similar inputs, different competition

### Scalera — LV-to-product matching with enterprise integration

The Swiss [Scalera site](https://www.scalera.ai/) targets manufacturers and suppliers, turning GAEB, PDF/scans, Excel and other inquiries into relevant product suggestions and offers. It documents SAP IDoc/REST, ERP/CRM/PIM integration and a **2–12 week rollout**; named references include ACO, Frauenthal, JMS and dormakaba. Its 150+ customer count and matching/efficiency results are vendor claims, and metrics from different catalogs should not be combined into a universal accuracy score.

**Why good / moat inference.** A catalog plus compatibility rules, accepted substitutions and salesperson corrections can form useful proprietary structured knowledge. Integration directly into the quote queue makes value measurable. **Limitation:** catalog hygiene, long-tail configuration and technical exceptions remain onboarding burdens. **Prototype relevance:** learn classification, provenance and structured feedback; do not confuse finding a matching drain with verifying whole-project drainage quantities or contractual completeness.

### kinisto — a particularly useful cold-start disclosure

[kinisto](https://www.kinisto.com/) prioritizes inquiries, extracts relevant LV positions, suggests products and connects through APIs/webhooks for manufacturers and dealers. Its [FAQ](https://www.kinisto.com/ressourcen/faq) recommends around **50–150 completed offers** for good matching. Its [Hekatron case](https://www.kinisto.com/referenzen/case-study-hekatron) reports about **80% correct suggestions after four weeks**; that case should not be replaced by a generic “up to 95%” headline.

**Why good / moat inference.** The explicit warm-up requirement is more informative than claims of effortless AI adoption. Historical quote choices and catalog-specific configuration can compound. **Limit:** the required history and curation create real cold-start friction; neither case metrics nor advertised customer/user counts are independent benchmarks. **Prototype relevance:** collect reviewed cases and distinguish first-day generic capability from performance after company-specific configuration.

### Tendos — product configuration and full-LV context

[Tendos](https://tendos.ai/) describes using the full LV rather than only reduced product files, checking contradictions before selection, configuring products/accessories, recognizing repeated inquiries on the same project, and **GAEB X84 export**. Salesforce, SAP S/4/C4C, Dynamics, Outlook and REST are advertised. The [Spelsberg case](https://www.tendos.ai/kunden/spelsberg) claims over 90% matching after one month and a four-week Salesforce integration.

**Moat inference.** Valid product combinations and accessory/configuration rules are more defensible than similarity search alone. **Limits:** the matching denominator, exception handling and transferability to another manufacturer are unverified. Weeks of onboarding are materially different from a self-serve upload tool. **Prototype lesson:** preliminary notes and related positions can alter the interpretation of an individual item; preserve full context, but make it reviewable rather than merely feeding more text into a model.

### Workist — strong evidence that organizational preparation dominates deployment

The [ACO LV case, 31 August 2026](https://www.workist.com/blog/leistungsverzeichnisse-mit-ki-bearbeiten-praxisbericht-aco), describes extracting relevant LV scope, passing it into SAP for pricing and producing GAEB offers. ACO attributes roughly **90% of implementation work to its own organization/master data**, with about six weeks of rollout. This is a named vendor-hosted customer account, not a market-wide statistic.

**Why good / moat inference.** Workist’s broader document/ERP automation experience and integration can be a distribution advantage. **Limits:** quoted order-processing automation rates from its [separate ACO story](https://www.workist.com/success-stories/aco) must not be relabeled as LV matching accuracy. **Prototype lesson:** budget for document naming, item master quality, permissions and ownership of corrections. A tool’s impressive extraction does not eliminate organizational readiness work.

These four companies are most direct competitors when the prototype helps a supplier answer a specification. They are less direct when the job is a contractor deciding which unpriced obligations threaten the overall bid. They may also be partners supplying structured offer data.

## Comstruct and execution-data adjacencies

### Comstruct — connectivity and actuals, rather than outsourced contractor calculation

The [current product site](https://comstruct.com/) explicitly says, “Your cost calculation remains your competitive advantage,” while agents handle subsequent work. It describes turning BoQ requirements into supplier RFQs, comparison/negotiation, framework releases, delivery notes, invoice matching and ESG information. Named testimonials include HOCHTIEF, ERNE and Implenia. The [integration page](https://comstruct.com/en-eu/integrationen) lists RIB, BRZ, Sorba, Abacus, SAP, SharePoint, DocuWare, d.velop and Power BI.

**Independent context.** [TechCrunch, 6 February 2025](https://techcrunch.com/2025/02/06/comstruct-a-platform-to-digitize-the-construction-industry-raises-135-million/), reported a €12.5 million round led by GV and 20VC. It described obtaining data through EDI, email and supplier portals and quoted the CEO saying 800 suppliers had been integrated. **That is a February 2025 reported figure, not a verified November 2026 network size.** The article’s per-document pricing is historical, not an assumed current contract.

**Why good / moat inference.** Normalizing many suppliers and connecting orders, deliveries and invoices can create operational switching costs and a useful actual-cost/material history. It addresses a recurrent transaction process rather than occasional document chat.

**Limits / opportunity.** Supplier connectivity does not itself prove engineering risk detection, correct scope normalization or price comparability. Maintaining heterogeneous connections is a structural cost. For the prototype, Comstruct suggests a later feedback path from bid assumption to ordered/delivered quantity, not a reason to build procurement first.

### Other adjacent businesses worth understanding

- **VESTIGAS:** [product/integrations](https://vestigas.com/produkt/integrationen) describe order/call-off, delivery and invoice reconciliation, with BRZ, RIB, NEVARIS, DocuWare and Capmo connectivity plus APIs/webhooks. Closer to Comstruct than to a semantic tender checker. Potential advantage: durable execution records; uncertainty: mapping them back to exact bid obligations.
- **Kojo:** [its integration ecosystem](https://www.usekojo.com/integrations) targets US trade-contractor material procurement and ERP/supplier connectivity. Useful procurement/three-way-matching reference, not evidence of German LV engineering support. Integration/network totals are vendor counts.
- **Qflow:** [current product positioning](https://www.qualisflow.com/) extends delivery/waste/carbon capture into material verification and reconciliation. Do not freeze its positioning at an older “waste-only” description. Potential input for planned-versus-delivered checks; German GAEB readiness was not established.
- **Alasco:** [current platform](https://www.alasco.com/) concerns owner/developer financial management, forecasts, invoices and cash flow. It can share project data and budgets without being the same buyer or core job as bidder-side risk review.

The adjacent moat is the transaction trail and embedded operations. A cross-position LV checker needs an explicit mapping from that trail to scope and quantity; the existence of invoices alone does not provide labeled tender errors.

## International companies with transferable ideas

### Provision — inferred scope, cross-trade gaps and traceable action

[Risk Review](https://provision.com/risk-review) covers commercial clauses and project documents; [Scope Agent](https://provision.com/scope-agent) describes trade-organized scope packages from drawings, specs and tables, inferred necessary work and coordination between trades. Outputs include referenced Word/Excel/PDF scopes; SharePoint/file ingestion and addendum reruns fit existing estimator tools. The product is aimed at general-contractor/preconstruction decisions, making it conceptually close despite no verified German GAEB/VOB support.

**Why interesting.** It distinguishes drawn, specified, inferred and coordination scope. Its page explicitly says its Q3 2026 Scope Gap Index contains **model flags, not confirmed omissions**. That is an important evidence distinction to copy.

**Claims / limits.** The page reports 97% extraction match accuracy on an internal dataset. It is not 97% recall of commercially material omissions; Risk Review’s separate accuracy headline is another task again. Its own comparison tables do not establish what generic AI or other vendors cannot do. No independent cross-project risk benchmark was found.

**Moat inference / lesson.** Standard scope templates, expert review and resolved trade boundaries could compound. Copy the explicit source classification and coordination logic, not an unqualified accuracy headline.

### Document Crunch — now Trimble, and no longer accurately described as contract-only

**Ownership is confirmed, not merely announced.** [Trimble’s SEC filing, Note 3](https://www.sec.gov/Archives/edgar/data/864749/000086474926000108/trmb-20260703.htm), states the acquisition completed **4 April 2026**, for **$246.4 million** consideration. It is therefore an incumbent-owned business at this research date, not an independent startup awaiting acquisition.

The [9 June 2026 product announcement](https://www.documentcrunch.com/news/document-crunch-launches-constructions-first-project-level-ai-risk-intelligence-platform) describes project-level risk across documents, addenda, flow-downs, scope gaps and notices, available in the US and Canada. Its project-volume and market-first language remain vendor claims.

**Moat inference / limits.** Construction-specific review history and Trimble’s distribution/integration ecosystem could be strong. Neither the acquisition price nor the announcement demonstrates German-law expertise, GAEB coverage or accurate quantitative reconciliation. **Prototype lesson:** multi-document commercial risk is an expanding platform category. Do not rely on stale competitor tables describing Document Crunch as only single-contract summarization.

### Trunk Tools / TrunkBid — document intelligence extending into preconstruction

[Trunk Tools](https://trunktools.com/) describes construction document intelligence, drawing/version context and integrations including Procore, Autodesk, SharePoint, Box, Egnyte and Dropbox. It claims a large expert-labeled drawing corpus; exclusivity, label quality and transfer to German tenders were not independently established.

[TrunkBid](https://trunktools.com/tools/trunkbid) maps bid inclusions, exclusions, alternates and silence against scope, with spreadsheet outputs. The [26 March 2026 launch article](https://trunktools.com/resources/product-updates/trunk-tools-enters-preconstruction-launch-trunkbid) describes a selective beta at launch; a later general-availability milestone was not verified. [ENR’s July 2025 reporting](https://www.enr.com/articles/61084-trunk-tools-nets-40m-in-funding-round-led-by-insight-partners-tech-firm-ceo-said) reported a $40 million funding round, not a product-quality validation.

**Moat inference / limits.** Long-lived project context plus document/field integrations can create useful continuity. Bid leveling must distinguish an explicit exclusion from silence and from an item included elsewhere; public pages do not prove that distinction works on every package. **Prototype lesson:** “not mentioned” is its own state, not automatically “excluded” or “covered.”

### Kreo — scope-aware takeoff and estimating, not just automated counting

The [current Kreo product](https://www.kreo.net/) combines AI takeoff, Caddie scope/assembly assistance, cross-sheet references, estimates and Excel outputs, with IFC/API capabilities in relevant offerings. An AI database is marked coming soon; it should not be counted as a released advantage.

**What is good / moat inference.** Bringing measurements, assemblies and estimates together gives useful live cost consequences for quantity changes. Saved assemblies and corrections may create switching costs. **Limits:** its published automation metrics describe particular measurement tasks, not BoQ commercial-risk accuracy. Setup/support complaints in [G2 reviews](https://www.g2.com/products/kreo/reviews) are individual anecdotes, not established company-wide struggles. German native GAEB/VOB review was not verified. **Prototype lesson:** separate measured quantity, scope assumption and assembly cost so a what-if change has an explainable effect.

### Togal and Beam AI — two different ways to reduce takeoff labor

**Togal:** the [product site](https://www.togal.ai/) describes plan measurement, counting/classification, drawing revisions and downstream estimate integrations. Its strength is turning drawings into quantities, not demonstrated German tender-law interpretation. **Moat inference:** measurement corrections and estimator workflow. **Limit:** plan completeness and professional review remain material; native GAEB support was not verified.

**Beam AI:** [ibeam.ai](https://www.ibeam.ai/) offers done-for-you takeoffs with human quality assurance and **24–72 hour** delivery for relevant trades, alongside estimating/bid-management capabilities. A 99%+ accuracy claim incorporates a service process, not necessarily raw model performance. **Moat inference:** operational trade expertise and reviewed output. **Limit:** human cost and turnaround differ from an instant interactive checker. **Prototype lesson:** compare total user labor and delivery time, not AI speed alone; human review can be a legitimate product choice if made explicit.

### ConCntric — a useful what-if and historical-cost reference

[ConCntric for estimators](https://concntric.com/solutions/for-estimators/) describes historical cost reuse with location/escalation context, estimate development, value engineering, scenarios, risk tracking and buyout visibility. It complements rather than simply replaces estimating tools.

**Moat inference.** Structured estimate history and a shared preconstruction decision process could create retention. **Limits:** historical cost relevance depends on normalization and project similarity; German GAEB and technical error detection were not established. **Prototype lesson:** optional what-if analysis should keep scope, quantities, assumptions and price basis separate rather than presenting a single unexplained “AI estimate.”

## GAEB and German workflow readiness

**GAEB support is a matrix, not a checkbox.** The [GAEB download authority](https://www.gaeb.de/de/service/downloads/gaeb-datenaustausch) identifies DA XML **3.3, edition 2023-01**, as the current released line reviewed here; **3.4, March 2026, is beta**, not a released replacement. The [official FAQ](https://www.gaeb.de/de/service/faq/gaeb-datenaustausch-faq) and [3.3 phase documentation](https://www.gaeb.de/de/produkte/gaeb-datenaustausch/versionen/gaeb-da-xml-version-3-3-stand-2023-01) distinguish exchange phases: X83 invitation to bid and X84 bid submission, for example. D/P/X generations and phase/version support must be specified separately.

The official XML checker validates structure/schema, not whether quantities are plausible, scope is missing or a construction obligation is legally allocated. That leaves substantive analysis beyond compliance, but file integrity is still table stakes.

| Company/group | Public support established in this research | What still needs verification |
| --- | --- | --- |
| Klava | Explicit DA XML 3.2/3.3, X83/X84 | Production access, round-trip fidelity and release-tier availability |
| BauGPT | Help docs name X81/83/84 and D81/83/84; export reported in trade press | Full format/version matrix, P-format details and preservation of special structures |
| Tendos | Explicit X84 quote export | Import variants and preservation of nonstandard/conditional product cases |
| Kuro | GAEB-related offer conversion advertised | Exact generations, versions, phases and identities preserved |
| Tenderhub | GAEB generation advertised | Version/phase coverage and export validation |
| Scalera, kinisto, Workist | GAEB supplier-inquiry/offer workflows documented | Per-product version matrix and ERP round-trip details |
| Phase0, NOVA, SIDOUN, Cosuno | GAEB inside wider AVA/procurement workflows; some certification claims/material | Exact current certified product/version/phase scope, not just a historical badge |
| Reiner, Arctis, baugenic, BAUIGEL | LV review documented | Native GAEB versions and bidirectional handling not established |
| SCAIT | Swiss-norm LV quantity checks documented | German GAEB/VOB behavior must not be inferred from Swiss support |
| International profiles | Drawing/specification/estimate workflows documented | No native German GAEB readiness established by this review |

A prototype validation should test identifiers, hierarchy, long/short texts, units, quantities, preliminary clauses, alternatives, optional/demand items, bidder supplements, attachments and version changes. Not every item applies to every exchange phase; the point is to test relevant semantics rather than merely obtain valid XML. Start with read-only review plus issue export if bid submission is not required; do not claim lossless X84 authoring until demonstrated.

## What appears defensible, and where adoption gets difficult

### Defensibility: separate assets from slogans

**Workflow access and distribution.** Cosuno, Phase0, NOVA, SIDOUN and Trimble can surface AI where a user already edits, compares or approves. A standalone checker must overcome switching and duplicate work. This is a structural advantage, not proof every incumbent check is good.

**Rules, configuration and reviewed decisions.** Kuro’s expert questions, SCAIT’s trade logic and supplier configurators are plausible assets. The most useful data would connect the original evidence, finding, engineer disposition, priced response and eventual outcome. Raw documents and unreviewed flags are weaker labels.

**Commercial/transaction graphs.** Comstruct/VESTIGAS connectivity, Cosuno bid flow and Phase0 tender returns can support repeatable workflows and data products. A count of documents, positions or prices does not prove usable comparable data; duplication, scope changes, bundled items and contractual restrictions matter.

**Licensed domain knowledge and trust.** Standards/specification content can improve usefulness but requires rights, versioning and correct application. A citation does not establish that a clause applies. EU hosting, tenant isolation and no-training commitments can reduce adoption objections, while also limiting the assumed global training flywheel.

**Not a demonstrated moat:** choosing a model provider, adding chat, using retrieval, claiming construction expertise or having an impressive document count. Those may be useful components without proving differentiation.

### Adoption friction: observed disclosures versus inferred burdens

**Directly evidenced:** Workist’s ACO account emphasizes organizational/master-data preparation; kinisto recommends a body of completed offers; Kuro describes substantial expert rule configuration; Beam and BAUIGEL expose human-review turnaround. Klava, NOVA and TrunkBid show why release status must be checked, not assumed.

**Structural hypotheses to validate:** alert fatigue, confidentiality objections, liability concerns, reluctance to replace AVA/ERP, inconsistent tender versions, poor scans, heterogeneous units and resistance to sharing estimate history. These are plausible buying/implementation obstacles, not observed private struggles of a named firm.

**No unsupported distress narrative:** this research did not establish any company’s churn, runway problems, model failure rate, loss-making unit economics or inability to retain users. Funding, a waitlist or a thin public case library cannot establish those conclusions.

## Actionable differentiation for the prototype

### Lead with a bounded, commercial review promise

Proposed positioning hypothesis: **“Before you submit, see the few scope and quantity issues most likely to change your bid, with evidence and a decision-ready next step.”**

A suitable initial buyer to test is a contractor estimator/commercial lead handling repeated tenders in a defined trade or project type. Large GUs already have credible enterprise alternatives; small planning offices increasingly have bundled AVA AI. Which segment has urgent unresolved review work and accessible files needs interviews, not assumption.

A first domain such as earthworks/disposal or concrete/reinforcement is attractive because it supports cross-item checks with economically meaningful consequences. The landscape already contains examples in both, so the choice must be justified by access to experts, data and measurable quality, not claimed novelty.

### Make the review contract explicit

The following is a proposed product contract, not a claim about existing prototype capability:

1. **Read without destroying structure.** Ingest the target GAEB variants and supporting PDFs; retain source IDs, pages, revision and trade/location context. Show missing/unreadable inputs.
2. **Combine deterministic checks with semantic review.** Arithmetic, unit conversions and balances should be reproducible. Language models can identify candidate relationships, ambiguities and evidence, but should not silently invent measured quantities or legal precedence.
3. **Aggregate with boundaries.** Group related concrete, reinforcement or disposal positions only after distinguishing type, location, construction stage, base/alternative scope and overlap. Provide the membership list and exclusions. “Sum all concrete” is not engineering reasoning.
4. **Check hidden expensive scope.** Link preliminaries, long texts, technical reports and neighboring trades to the relevant priced positions. Separate a documented obligation from a likely necessary activity and from an unresolved question.
5. **Rank issues, not sentences.** Deduplicate one root cause across many positions. Combine justified impact range, likelihood/confidence and action urgency, with the components visible. Avoid a precise euro figure when no defensible cost basis exists.
6. **Close the decision.** Offer a Bieterfrage, assumption, reserve, required expert check or change-event watch item. Human approval remains required; a discrepancy is not automatic entitlement to a Nachtrag.
7. **Remember revisions and dispositions.** Show which findings are new, resolved, superseded or still open when an addendum arrives. Preserve why a reviewer dismissed an alert.

### Build an issue card that can survive expert scrutiny

Each issue should contain: a short commercial headline; source positions/pages; related quantities and calculation; classification as explicit conflict, inferred gap or missing evidence; impact basis and uncertainty; priority explanation; recommended action and owner; and a reviewer disposition.

The important interaction is not a long generated report. It is the estimator moving from a few thousand positions to a manageable set of decisions while being able to open the evidence immediately. Chat can support investigation, but should not hide coverage or become the only way to discover a risk.

### Keep pricing subordinate until the evidence supports it

Cosuno, Phase0, NOVA SmartPool and established licensed libraries make generic price suggestions a difficult initial moat. A useful early what-if feature is transparent sensitivity: changing a disputed quantity, disposal class or inclusion assumption changes an estimate range using a known user-provided or cited price basis.

If comparable historical prices are later added, retain date, region, quantity scale, technical scope, commercial conditions and provenance. Median prices are interpretable only after comparability is justified. Never imply a supplier material price is a complete installed contractor unit price.

### Create a measurable quality advantage rather than an accuracy slogan

Proposed evaluation, before any marketing percentage:

- Use legally accessible historical tenders, held out by project. Reconstruct only documents available **at bid time**; later change orders are outcome evidence, not input that leaks the answer.
- Have independent construction reviewers label issues, their evidence, materiality and acceptable actions. Distinguish disagreements and missing facts rather than forcing a fabricated gold answer.
- Measure precision among the top-ranked issues, materiality-weighted recall, review minutes, duplicate alerts, source correctness and quantity/unit correctness. Define denominators and severity conventions.
- Include clean controls and plausible near-misses: alternative positions that must not be summed; the same scope at two locations; disposal already included in a long text; revised quantities that supersede rather than add; explicit exclusion versus silence.
- Compare with the real current workflow and a competent generic AI baseline using the same available documents. Do not compare an expert-configured product with a deliberately weak one-prompt baseline.
- Evaluate an ablation without cross-position grouping. If the prototype’s central claim is relational review, that capability should produce useful additional findings rather than just more alerts.

These are recommended tests, not tests executed in this research. Success thresholds should be agreed with the initial buyer; no measured prototype performance is asserted.

### Build a feedback asset with consent

Capture accepted/rejected issues, reviewer reasons, clarified scope, revised quantities and eventually commercial outcomes, with explicit rights and tenant boundaries. A resolved discrepancy can teach more than another unlabeled PDF. Separate confirmed outcomes from submitted claims and estimated avoided cost. This is a plausible path to a defensible dataset, not proof that a cross-customer data moat is legally or commercially available.

## Evidence gaps and follow-up priorities

**Highest-value competitor demonstrations:** Kuro, Tenderhub, SCAIT and Arctis for a shared contractor tender case; Cosuno for procurement-connected risk; BauGPT/Reiner for specialist-workplace substitution; Phase0/NOVA/SIDOUN for bundled AVA checks; Provision for inferred/cross-trade scope. BAUIGEL/Beam are useful service-quality and turnaround references. Supplier platforms belong in the comparison only if supplier quoting becomes part of the target workflow.

Use the same authorized document set and ask each vendor to show: supported file versions; all positions actually reviewed; an asymmetric cross-item balance; alternatives not double-counted; a hidden obligation in preliminaries; source traceability; an addendum rerun; dismissed false positives; export into the existing tool; and pricing/implementation effort. Do not request confidential customer artifacts.

**Unresolved evidence:** no independently comparable LV risk benchmark; little public evidence of materiality-ranked recall on unseen projects; incomplete current GAEB/version matrices; uncertain API write-back scope; no audited estimate of paid AI adoption; and limited independent customer reporting for the youngest vendors. Security/data-residency statements were not audited. Public metrics often mix users, firms, projects, pages, flags and confirmed findings, making numerical rankings misleading.

**Additional watchlist, lower-confidence coverage:** [BAU AI](https://www.bauai.eu/) advertises GAEB and several agents, but its own beta/early-access and certification-in-preparation wording should constrain readiness claims. The [S-TEC Smart LV Assistant project](https://s-tec.de/projekte/smart-lv-assistant-ki-basierte-suche-und-kalkulation-in-leistungsverzeichnissen) is a 2026 research/pilot signal, not evidence of a shipping startup product. Smaller emerging names and additional countries remain outside the validated profile set; omission is not a judgment of quality.

**Bottom line:** validate a narrow, evidence-rich risk-review workflow that earns an estimator’s trust. The landscape supports demand and offers strong design references, but does not prove a vacant market. The credible differentiation is lower review burden and better consequential decisions on a defined class of tenders, demonstrated against existing tools and bundled AI—not simply more construction terminology, more flags or a broader agent menu.