# Known limitations (Phase 1)

What the workbench does not do yet, or does only in part. Work deferred on purpose is listed in
[ADR 0008](decisions/0008-deferred-to-phase-2.md) (no LLM planner, no user accounts, no
multi-user workflow controls, among others; its status note says what round 1 delivered since; one
statistical check, `statistical.peer_price`, has since been added and runs on every validation); this page
adds what a user or reviewer will notice.

## Editing cells

- **An edit changes the cell, not the structure.** Editing a cell in the workspace stores the
  table's next revision; the uploaded file is never changed. The new text is read like the
  column's other cells, but row classification (item, section, subtotal), sections, column
  profiles and the reading notes stay as the extraction decided them. Rows cannot be added or
  removed. A finding is not marked `corrected` by an edit; validate the table again to see
  which findings remain.

## Scope

- **XLSX, CSV, GAEB, Word and printed bills in PDF.** Image files (photos, TIFF) and legacy
  Word `.doc` files are not read (save a `.doc` as `.docx` or PDF); scanned PDFs are. GAEB files must be DA XML 3.1, 3.2 or 3.3 that passes its official
  schema, or GAEB 90, in the phases 81 (bill of quantities), 83 (call for bids), 84 (bid) or 86
  (contract award). GAEB 2000 (`.p83`), DA XML 3.0 and older, and other phases are rejected
  ([ADR 0009](decisions/0009-gaeb-import.md),
  [ADR 0010](decisions/0010-older-gaeb-formats.md)).
- **PDF bills are read by their layout.** Bill pages need a column header row (Menge,
  Einheitspreis/EP, Gesamtbetrag/GP); numbers are read in German notation (`1.655,000`);
  pages turned by 90° are not read. Items whose
  quantity line cannot be placed are reported for review, and a failed check on a PDF value asks
  to be verified against the page ([ADR 0011](decisions/0011-pdf-bills-and-excel-export.md)).
- **Scans are read by OCR, with less certainty.** Pages without a text layer are read by
  Tesseract (installed in the Docker image; elsewhere it must be installed for OCR). About one
  second per page. A value OCR cannot read whole is left empty and reported, a unit it cannot
  read (`m?`) is kept for the unit check, and the document is marked for review
  ([ADR 0012](decisions/0012-ocr-for-scanned-pdfs.md)). Handwriting and photos are not read.
- **Word documents are read from their tables and item paragraphs**
  ([ADR 0014](decisions/0014-word-documents.md)). Each Word table becomes a table of its own,
  so a bill split into several tables is checked table by table. A bill written as paragraphs
  needs item numbers with at least two parts (`2.3.10`) and a unit (`[m²]`, or a tab-separated
  column); its sections and long texts are inferred from the layout. Numbers that Word adds
  to numbered lists automatically, text boxes and images are not read.
- **GAEB 90 states less than DA XML.** Category labels may be cut at 40 characters, lump-sum
  items carry no flag, and unit-price components and contract terms are not shown.
- **STLB-Bau keys are not looked up.** A GAEB item's standard text keys are compared only with
  other items of the same file; the texts are not checked against the licensed DIN catalogue.
- **User accounts are simple** ([ADR 0015](decisions/0015-users-and-roles.md)). People sign in
  with a personal access token that an administrator issues; there are no passwords, no token
  expiry, no single sign-on, and roles (viewer, reviewer, administrator) apply to the whole
  installation, not per project. Sign-in is optional: without `TWB_AUTH__TOKENS` anyone who
  opens the server acts as the local administrator, so roles there only say who acts. Without
  tokens the API is meant for the reviewer's own machine; it only accepts the configured hosts
  and browser origins ([deployment](deployment.md#authentication)).
- **The interface is only partly in German.** The language switch (Settings, General) translates the navigation, the top bar, the user profile, Settings, sign-in and the
  page titles; the pages' own content, findings and reports are still in English.
- **The sheet on the Workspace page is not a full spreadsheet** (Part J). It shows 100 rows per
  page with sticky headers and row numbers, cell selection with the keyboard, and editing (each
  saved edit is a new revision of the dataset, see "Editing cells"). It has no sorting,
  filtering, search or column resizing. It marks the cells of the selected run's findings (up to
  2,000 findings; the Issues tab lists all). The web interface needs Node.js 22 or newer.
- **No AI planning and no AI explanations yet.** Every run runs every registered check; a
  reviewer cannot choose checks ([ADR 0010](decisions/0010-boq-anomaly-detection.md)).
  Brief Part B.4 asks for an optional local model (Ollama) behind a provider abstraction, with
  the application working without one. The language model settings (`TWB_LLM__*`) and the
  health status exist. The allow-list holds one model, `qwen2.5:7b-instruct`, added in `main`
  on 2026-11-21 while its answers are still being evaluated;
  [ADR 0010](decisions/0010-boq-anomaly-detection.md) lists a model only after that evaluation.
  Over HTTP only the risk discovery runs that a client starts call it
  ([ADR 0013](decisions/0013-risk-grading.md), proposed); their findings are open questions
  without money, never confirmed errors. No model explains a finding or plans a run; the LLM
  planner stays deferred ([plan](handoff/NEXT_STEPS.md)).
- **The Claude bill review is a suspicion, and only some of it is listed.** A reviewer can send
  one bill to Claude when the server has a key ([deployment](deployment.md#claude-bill-review)).
  Only the claims the model rates as certain are listed, as `semantic_warning` findings; the
  others are counted in the run's report. The same bill can get other claims when it is sent
  again. Its findings are listed like the checks' findings: the ordering by measured hit rate
  ([evaluation](evaluation/boq-practice-p1-model-review.md)) stays in the evaluation tool. After
  a correction, claims on unchanged positions stay until the review is started again.

## Detection

- **Only the error kinds the 23 deterministic and domain checks check**
  (see the [detector catalogue](architecture/detector-catalogue.md)): the 15 from before step
  B2 and the 7 that B2 adds (tender clauses, contingency and hourly positions, bid prices,
  companion work, missing attributes, the numbering hierarchy and unit price components), next
  to the signal checks: the four of the tender review (below: missing
  items, unclear descriptions, contradictions within an item, typing slips) and the two price
  context checks of `main`, and the six signal checks of step B3. B2's
  `domain.boq_separate_payment` runs on every validation as well. `statistical.peer_price` flags a unit price far from
  comparable positions of the same bill as a Risk signal, never as a confirmed error.
  `statistical.historical_price` first compares a priced position with similarly worded
  positions of the same unit in the three priced sample offers of other projects (issue #114)
  and reports only a price three or more times away from their median; it leaves out a
  project whose wording matches a fifth of the bill's rows almost exactly (the bill's own). On
  the real sample bills this compares no priced row: the priced bills are those offers
  themselves, and the other bills with a match are unpriced tenders. Every other position is
  compared only with the 30 synthetic projects, which the real sample bills do not resemble, so
  there it abstains. It dates a bill by its price-date column, else by the GAEB file's date, else
  compares undated with a wider interval (the real offers: with all of them). `statistical.open_price_reference` shows, as context, a unit price below the
  2025 average factory-gate value of its material in Eurostat PRODCOM (German, else EU-27). No
  open source publishes what a German position should cost installed (issue #23), so it never
  says that; it compares only a short list of materials in their own unit and found no matching
  row in the hackathon's priced bills. A wrong quantity whose total was computed consistently is not found, except a
  fraction in a whole-number unit or a lump sum with a quantity other than 1 or -1
  (`deterministic.unit_compatibility` warns). A wrong rate whose total was computed consistently
  is found only in these cases: a unit price of 0,00 on a position whose quantity is not 0, a
  token price of 0,01, or an hourly labour rate below the statutory minimum wage
  (`domain.boq_bid_prices`); a unit price that is not the sum of its components, where a
  reviewer maps the component columns (`deterministic.unit_price_components`; the GAEB import
  does not read the components yet); a unit price that differs from another row with the same
  STLB-Bau key, unit and currency (`domain.standard_text_keys` flags those rows as an
  Inconsistency, never as a confirmed error); and, when a run switches on
  `statistical.peer_price`, a unit price far from the median of at least three comparable
  positions (same unit and currency). A position whose text belongs in another section while
  its OZ fits the section, or missing scope other than the companion work B2's check knows, is
  not found.
- **The risk report repeats nothing the issue register finds** (owner's decision of
  2026-11-21): the risk rules that checked the same as a B2 check were removed or narrowed, so
  the register's checks now decide those conditions alone, as they were measured. The risk
  report therefore no longer asks for backfill when an excavation names no trench or pit
  (`domain.boq_companion_work` reads trenches and pits only), for a pressure test of a pressure
  or drinking-water pipe whose Kurztext names no laying, or about "nach Aufwand" in a large
  position that is not a lump sum. `domain.boq_required_attributes` takes any size in a pipe
  position's text, also the size of another component ("an den vorhandenen Schacht DN 1000
  anschließen"), which the removed rule A04 did not count, and it reads a waste class only in
  the position's own text, not in the notes of its section. A Stahlbeton or Transportbeton
  position whose Kurztext has no verb of placing ("Stahlbetonwand d = 24 cm") is no longer asked
  for a strength class, which A01 did; on the sample bills every such position A01 asked about
  read as work on concrete, but a bill that writes its concrete positions without a verb is not
  checked for the class. The tender review's wording is left to it in the same way: V01 no
  longer asks about "nach Absprache" or a decision of the site management or the architect, and
  V02 not about "komplett", "betriebsfertig", "u. dgl." or "usw.".
- **The bid risk report of a project shows money only where the bill has it**
  (`GET /projects/{project_id}/risk-report`, issue #112). A position has a line total and a
  share only in a priced bill, and a reminder has money only when a check computed it: tenders
  arrive unpriced, so on them both columns are mostly empty or "unknown" (on the saved
  development reports of 2026-11-21, every reminder's money was unknown and six of seven bills
  had no prices). Positions added for their size are listed for their line totals alone: nothing
  beyond the risk report was checked about them. A reminder about more than three positions is
  listed once below the rows, not on each position, so a large position may sit outside the rows
  while such a reminder names it. The rows go by the position's size before the reminders'
  tier, so a high reminder on a small position can fall below the cut (it stays in its run's
  risk list), and in a project with priced and unpriced bills the unpriced bill's positions,
  which have no size, come after the priced ones. Bills in different currencies are not
  compared, and the first bill's `grading.yaml` orders the rows of all bills (only the `boq`
  profile has risk tables).
- **The tender review reads wording, not meaning** ([ADR 0013](decisions/0013-tender-review-checks.md)).
  Its findings (missing items, unclear descriptions, contradictions, typing slips) are signals
  for a reviewer, matched from German and English phrases and from the bill's own numbering and
  vocabulary. No dictionary is used, so a word misspelled the same way throughout is not found,
  and a deleted item number looks like a missing item. Wording that `domain.boq_clauses`
  reports ("nach Bedarf", "nach Erfordernis", "nach Aufwand" in a lump sum, "einschl. aller
  erforderlichen ...") is left to it, read with that check's default patterns: a profile that
  changes those patterns does not change what the tender review leaves out.
- **Abstention over guessing.** Ambiguous values (`(1.234,00)`, day/month order, an undecided
  contingency item) are not guessed; a check that depends on them is skipped or reported as
  undecided, never as a confirmed error.
- **CSV display rounding.** CSV amounts may have been rounded for display, so totals over many
  lines are allowed a drift of 0.005 per line; a small slip in a large total is then reported as
  possible display rounding (info), not as a confirmed mismatch.
- **Formulas are never evaluated.** An XLSX saved without cached results (for example, written by
  a script) has no values in its formula cells; those cells are reported as unavailable.
- **Summary pages** (Zusammenstellung, collection) are reconciled at the total that closes them,
  not line by line against the section subtotals.

## Evaluation

- **Synthetic benchmark only** ([docs/evaluation](evaluation/README.md)). No labelled real bills
  were available, so there is no real-world accuracy figure. Scores are ratios over a generated
  set, not probabilities.

## Operation

- **One application process per database.** Background runs and their crash recovery assume it:
  at start-up, runs left `queued` or `running` are marked `failed`. With several processes on
  one database, all but one must set `TWB_JOBS__RECOVER_INTERRUPTED_RUNS=false`
  ([deployment](deployment.md#background-validation-runs)).
- **Queued runs are not resumed after a crash.** A run that was waiting or running when the
  process stopped is failed, not started again; start a new run.
- **Custom profiles written before round 1 must list `boolean_words`**, or yes/no cells are no
  longer read as booleans (they are reported as unreadable;
  [upgrade notes](deployment.md#upgrade-notes)).

## API details

- A multipart `filename*=` (RFC 2231) parameter is not decoded; browsers and common clients send
  the UTF-8 `filename=` form, which works.
- A client that disconnects during an upload is logged as an internal error; the partial file is
  deleted.
