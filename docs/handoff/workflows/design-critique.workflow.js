export const meta = {
  name: 'phase1-design-critique',
  description: 'Independent critique of the Phase 1 core contracts (data model, detector contract, pipeline, profiles) through five lenses',
  phases: [{ title: 'Critique', detail: 'five independent reviewers, read-only' }],
}

const ROOT = '/home/user/tabular-integrity-workbench'
const COMMON = `You are reviewing the FOUNDATION of a hackathon app (Tabular Integrity Workbench) before eight engineers build on it in parallel. Repository: ${ROOT}. Read the requirements in ${ROOT}/docs/product/brief.md first.

The foundation (already written, tests pass) is:
- backend/app/models/*.py (canonical model: values, source, dataset, document, issue, plan, run, audit, profile)
- backend/app/validation/contracts/*.py (detector contract, ValidationContext, IssueFactory with evidence downgrade policy, decimal_math with RoundingSpec/TolerancePolicy)
- backend/app/validation/registry/*.py, plan_validation.py, planner.py (baseline planner), pipeline.py
- backend/app/profiles/*.py and *.yaml (domain profile loader, unit catalog, currency resolver, generic + BoQ profiles)
- backend/app/ingestion/base.py (raw extraction types), backend/app/ingestion/security.py, registry.py, backend/app/storage/file_store.py, backend/app/normalization/builder.py (these four are CONTRACT STUBS with docstrings; implementation comes later)
- backend/app/repositories/base.py (persistence protocols)
- backend/tests/support/builders.py and backend/tests/unit/** (tests)

Planned next: XLSX+CSV ingestion, normalization (header detection, locale-aware number parsing that abstains on ambiguity, column mapping by profile synonyms, unit normalization, row classification into item/section/subtotal/grand_total/tax/gross_total/text/blank), 12-13 deterministic detectors (required values, data types, numeric validity, field constraints, exact duplicates, extraction uncertainty, line total qty x price, subtotal, grand total, currency consistency, spreadsheet formula errors, reference integrity, unit vocabulary, unit compatibility), SQLite persistence, FastAPI REST API, React shell.

RULES: This is a READ-ONLY review. Do NOT modify, create or delete any file. You may run read-only commands (cat, grep, python -c snippets that only import and inspect, and the test suite: cd ${ROOT}/backend && .venv/bin/python -m pytest -q).

Report only findings that would cause real problems (wrong results, violated requirements from the brief, security holes, designs that will force rewrites in later phases, or contracts that parallel implementers will misread). Skip style nits. For each finding give the concrete file/symbol, what goes wrong (a concrete scenario), and a specific fix. Rank by severity. Be precise and skeptical; do not pad the list.`

const LENSES = [
  { key: 'adaptability', prompt: `LENS: adaptability and extensibility. Will this foundation survive (a) a completely different tabular challenge revealed later (not BoQ), (b) statistical/ML/semantic detectors with grouping and anomaly scores, (c) an LLM planner doing multi-pass adaptive validation with strict limits, (d) PDF/OCR ingestion with bounding boxes and confidence, (e) user corrections creating dataset revisions and schema-review changes (header row choice, manual column mapping, row exclusion), (f) research-paper algorithms plugged in via the registry, (g) export adapters? Identify contract gaps that would force changes to core models, pipeline or database later.` },
  { key: 'numerics-evidence', prompt: `LENS: numerical correctness and evidence semantics. Check Decimal handling end to end (contexts, quantize, JSON round trip, float leakage, percent handling, currency), the TolerancePolicy and RoundingSpec semantics for line totals, subtotals (sums of rounded values) and grand totals, the power-of-ten heuristic, the IssueFactory evidence downgrade rule, fingerprint stability, the ParseStatus/extraction_confidence semantics (no invented confidence numbers), and whether the issue/evidence model can express calculations, related rows and financial impact honestly. Look for any path where a statistical score could be shown as a probability or an unverified value could become a confirmed violation.` },
  { key: 'boq-domain', prompt: `LENS: construction BoQ domain realism, for German Leistungsverzeichnis (GAEB, OZ hierarchy such as 01.02.0030, Kurztext/Langtext, Menge/ME/EP/GP, Titel/Los/Summe Titel, Übertrag, Bedarfs-/Eventual-/Alternativpositionen that are typically excluded from totals, Pauschal/psch, Stundenlohnarbeiten) and UK/international BoQs (NRM/SMM, Item/Description/Qty/Unit/Rate/Amount, collections and summaries, provisional sums, prime cost sums, daywork, carried forward/brought forward, page totals). Review backend/app/profiles/boq.yaml (header synonyms, row classification patterns and their order, units and aliases, detector defaults) and the row/section model in models/dataset.py. Which realistic BoQ layouts would be misclassified or produce false positives (e.g. optional items counted in totals, multi-row headers, long-text continuation lines, nested subtotals, VAT lines, lump-sum rows with qty 1), and what profile or model changes fix them without hardcoding construction terms in the core?` },
  { key: 'security-robustness', prompt: `LENS: security and robustness. Review the ingestion/storage/security contracts (docstrings in ingestion/security.py, storage/file_store.py, ingestion/base.py), config limits in core/config.py, profile loading (yaml.safe_load), regex patterns applied to untrusted cell text (catastrophic backtracking/ReDoS), the pipeline isolation boundary and error messages (information leakage), prompt-injection exposure for the future LLM planner (cell text reaching prompts), path traversal, zip bombs, XML attacks (openpyxl + defusedxml), CSV formula injection on export, denial of service via huge sheets/rows/columns/cells, and cross-document access once auth exists. Flag gaps in the contracts that implementers would likely get wrong.` },
  { key: 'maintainability', prompt: `LENS: maintainability and clean architecture for 8 parallel implementers. Check layering (models must not depend on validation/ingestion/api; services depend on repository protocols), dependency injection seams (ids, clock, settings), naming consistency, whether the contracts and docstrings are unambiguous enough that independent implementers of ingestion, normalization, 3 detector groups, persistence+API and frontend will produce compatible code, test-helper realism (does tests/support/builders.py produce datasets that match what normalization will produce, e.g. unit normalized_value, text normalization, section_row_id, parse statuses?), and duplicated logic risks. Also check the repository protocol for issues needed by the review workflow (versioned issue updates, audit trail) and dataset revisions.` },
]

const SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          severity: { type: 'string', enum: ['critical', 'high', 'medium', 'low'] },
          location: { type: 'string', description: 'file path and symbol' },
          problem: { type: 'string', description: 'what goes wrong, with a concrete scenario' },
          fix: { type: 'string', description: 'specific recommended change' },
        },
        required: ['severity', 'location', 'problem', 'fix'],
      },
    },
    overall: { type: 'string', description: 'two or three sentences: is the foundation sound for this lens?' },
  },
  required: ['findings', 'overall'],
}

phase('Critique')
const results = await parallel(LENSES.map(l => () =>
  agent(`${COMMON}\n\n${l.prompt}`, { label: `critique:${l.key}`, phase: 'Critique', schema: SCHEMA })
    .then(r => ({ lens: l.key, ...r }))
))
return results.filter(Boolean)
