# D-9: demonstrate the Bid risk report

Decision: **option 2 — show only the Bid risk report in the report segment**.
The ordinary findings PDF, Excel workbook and CSV remain available. Keep the default
report type unchanged; renaming reports for different audiences is outside D-9.

Tracked in [#193](https://github.com/AminDaryan/tabular-integrity-workbench/issues/193).
Related: [#112](https://github.com/AminDaryan/tabular-integrity-workbench/issues/112)
(report implementation), [#127](https://github.com/AminDaryan/tabular-integrity-workbench/issues/127)
(demo pipeline). This supplements the [demo instructions](../../tools/demo-video/README.md);
it does not change the video, script or recording pipeline.

## Current UI and preparation

UI instructions checked against `main` through `272ab88` on 2026-11-22, including
the navigation change merged in #195. Reports has **one** `Generate a report` panel with a `Type`
selector. The older issue comment describing a separate Bid risk report box is obsolete.
Reports is in the project's navigation bar below the application top bar. The original
browser/PDF verification used `dad0d48` (#191); after #195, the navigation and unchanged
report logic were checked in code and the two frontend report test files were rerun.

Use the English UI and the prepared **Kalkufer 17, anchored excavation** project
(the catalogue ID is `prj_demo_showcase`; use the actual ID if it was imported separately).
Use an isolated local instance with disposable storage and the synthetic Kalkufer sources.
The [showcase instructions](../../tools/showcase/README.md) describe the source package.
Preparation and any necessary validation must happen in that local instance before rehearsal.
Do not generate reports, import sources or revalidate a production project for D-9.

Before starting, confirm the local project's last validation completed and record its
finish time and bill run IDs. Do not edit its data, change review decisions or validate
again between viewing and exporting. If the page says `Validate the project first.`,
stop this segment and prepare the local project. While validation is running, wait for
completion. A failed, partially completed validation can still produce a Bid risk report,
but it is partial coverage and does not pass the normal completed-project rehearsal.

## Presenter sequence

1. Open **Kalkufer 17, anchored excavation**, then select **Reports** in the project's
   navigation bar below the top bar (`/projects/<id>/reports`). Check the project identity
   before proceeding.
2. In **Generate a report**, change **Type** from **PDF report** to
   **Bid risk report (PDF)**. The API format is `bid-risk.pdf`; `PDF report` is the
   ordinary findings report and is not this demo's selection.
3. Confirm **Report on** reads **Whole project** and is disabled. Selecting this type
   forces project scope even if a single bill was selected previously. There is no
   additional whole-project checkbox or separate report entry to open.
4. Click **Generate report** once. It stores the report in the project's **Reports**
   table and downloads a file ending in **`-bid-risk-report.pdf`**. Wait for completion;
   an error is not a successful export. Identify this new row by type, scope and creation
   time, and retain its downloaded file. Generation does **not** navigate to the preview.
5. Click **View on screen** beside the generation button. This opens
   `/projects/<id>/report`, headed **Bid risk report: Kalkufer 17, anchored excavation**.
   First show **Bills in this report** and every **Not in this report** entry. The
   expected bill in the standard synthetic package is `Kalkufer-17-LV.xlsx`; reference
   PDFs/supporting documents are listed separately with reasons. `Whole project` means
   a project-level report on eligible bills from its last validation, not that every
   attached file was validated or every project position is shown.
6. Show **Positions that drive price and risk**: position, **Line total**, reminder,
   priority and **Money at stake**. Show **Reminders about several positions** if present,
   then **How this list was made**. Select an illustrative risk from the current output;
   do not promise an old video's specific position, count or amount.
7. Open the file downloaded in step 4 in a local PDF viewer. Show its project heading,
   bill coverage, the same selected positions/reminders and their amounts. Compare against
   this preview before calling it the corresponding PDF. The backend PDF is English and
   A4 landscape; its layout differs from the screen, with one table row per reminder.
8. If a second download is needed, use **Back to reports**, then the download icon on
   the stored report's row (accessible name: **Download <filename>**). This retrieves
   the same saved file. Returning to Reports remounts the form with **PDF report** as
   its default: reselect **Bid risk report (PDF)** before generating anything again.

The preview also has **Print or save as PDF**, which opens the browser's print dialog.
That is a separate browser-print path, not the saved backend PDF from step 4. It is not
needed for this sequence. **View on screen** can also be used before generation, but does
not save a report. There is no `Download as PDF` button on this current preview page.

## What to say, and what the figures mean

Suggested narration: “For the bid decision, this report brings together the positions
that drive price and risk. We can see the reminders and the money attached to each, then
hand over the corresponding PDF. The coverage and limitations are stated in the report.”

- This segment presents the **bid decision risk report**. Do not call its reminders
  findings, or substitute the findings report/Overview's counts or severity totals for
  its position counts, reminder priorities or money. They are different report views.
- The preview and saved PDF use a limit of 20 positions. Some may be included only for
  size, explicitly labelled **No reminder: listed for its size**. Neither 20 positions
  nor a PDF's row count is the project's total number of risks. A position may have
  several reminders, and reminders about several positions are listed separately.
- **Line total** is the position's price; **Money at stake** belongs to the reminder.
  Keep exact amounts, estimates, comparisons and **Not known** distinct. A comparison
  is not a confirmed loss; unknown money is not zero. Do not add these columns together
  or describe their sum as savings. Follow the report's current explanation of ordering
  and the [known limitations](../known-limitations.md), including the size-first cut.
- The on-screen report is recomputed when opened using current reviews and the last
  validation; the stored PDF is a snapshot. Same project name alone does not establish
  equivalence. If data/reviews change, prepare a new matched local preview/PDF pair.
  Generation times may differ; do not require identical timestamps or screen/PDF layout.

## Rehearsal acceptance checklist

Fill this in for each rehearsal. These are live comparisons, not fixed expected numbers
from a previous recording. Use pass/fail/blocked and record why anything is blocked.

- [ ] Record build commit, local base URL, project ID/name, language, validation finish
      time and bill run IDs; verify completed validation and unchanged review decisions.
- [ ] Reports shows one generation panel; select **Bid risk report (PDF)** and confirm
      disabled **Whole project**. The other types remain available; default is unchanged.
- [ ] **Generate report** creates the correct table row and downloads a nonempty, readable
      PDF. Record report ID, filename and creation time to distinguish older exports.
- [ ] **View on screen** opens the correct project. Included bills, skipped files and
      reasons are understood; there is no unexplained missing bill or partial validation.
- [ ] Compare preview and downloaded PDF: project identity, included/excluded bills,
      bill totals/currency, displayed position order and labels, reminder titles/priorities,
      line totals and reminder amounts/types, plus any separate multi-position reminders.
      Check the same validation and unchanged data/reviews throughout.
- [ ] Open every PDF page: headings, long reminders, table columns, amounts and page
      breaks are readable without clipping/overlap. Re-download the saved row if needed;
      it must still be the same saved document.
- [ ] Narration distinguishes bid risk from findings, line prices from risk money,
      comparisons from losses, and project scope from complete attachment coverage.

Record: `commit / local URL / project ID / validation finished_at + runs / report ID /
filename + created_at / PDF result / tester + date / outstanding checks`.

## Verification performed for this change

**Passed locally on `dad0d48`, 2026-11-22:** worktree Vite UI at `127.0.0.1:5199`, proxied
only to FastAPI at `127.0.0.1:8909`; fresh SQLite/uploads under
`/private/tmp/d9-report-verification/data`. The temporary startup harness limited demo
import to the synthetic Kalkufer catalogue entry; it did not modify application code.
Only copies of the existing local Kalkufer XLSX, three PDFs, IFC and synthetic context
were imported. Their scenario differs from current `tools/showcase/scenario.json` only
in `clarifications` and `video`; this was not a new full showcase/video generation.
No production endpoint or external model was used. Source files and generated evidence
remain local and are not committed or attached to GitHub.

- Real Chromium/Playwright flow verified the selector's four options, unchanged default,
  locked scope, generated PDF download, on-screen preview and saved-row re-download.
- The same project and validation were retained across the flow. All 20 displayed
  positions, their 10 attached reminders and one separate reminder were compared against
  the PDF, including project/bill coverage, order, titles, priorities and money. These
  counts describe this run only, not future acceptance thresholds. The two downloads
  were byte-identical. All four PDF pages were rendered and visually inspected.
- Local evidence directory: `/private/tmp/d9-report-verification/` (temporary, not a
  portable repository artifact). It contains the downloaded PDF, preview screenshot/text,
  report JSON, project validation snapshot, report metadata, comparison result and
  temporary verification scripts. PDF SHA-256:
  `7ec39dfd6023abcaa2ac9bf8ffd802256c36d7a96969e358f9836c5917036d78`.
- Targeted frontend tests: **7 passed** in `ReportsPage.test.tsx` and
  `ProjectReportPage.test.tsx`. Targeted backend tests: **13 passed** (11 report builder,
  PDF and API tests; 2 kept-report tests on memory/SQLite). The backend emitted the
  existing Starlette/httpx deprecation warning.

Environment: macOS, Python 3.13.18, Node 26.13.1, Vitest 5.1.0, Playwright 1.63.0
with Chromium 1243. Existing local dependencies were reused (frontend dependencies
copied into this worktree); this is not a clean installation or the pinned Node 24 CI
environment. Poppler rendering used a temporary local font/cache configuration.

Commands run from this worktree, using the existing backend Python environment:

```sh
cd frontend
node node_modules/vitest/vitest.mjs run src/features/projects/ReportsPage.test.tsx src/features/projects/ProjectReportPage.test.tsx
cd ../backend
python -m pytest tests/integration/test_bid_report_api.py tests/unit/risk/test_bid_report.py tests/unit/risk/test_bid_report_pdf.py -q
python -m pytest tests/integration/test_projects_api.py -k kept_reports -q
```

**Still to verify at rehearsal:** the target presentation machine's download/viewer
behavior and its current prepared project data. Browser **Print or save as PDF**, German
UI, production and the full video pipeline were not exercised. The browser/PDF flow was
not repeated after the navigation-only change in #195. No full application suite
was run for this documentation-only change. The local snapshot checks do not certify
those paths or a future dataset.

## Implementation references

- [ReportsPage](../../frontend/src/features/projects/ReportsPage.tsx) and
  [its tests](../../frontend/src/features/projects/ReportsPage.test.tsx): type, scope,
  generation, preview link and saved downloads.
- [ProjectReportPage](../../frontend/src/features/projects/ProjectReportPage.tsx) and
  [its tests](../../frontend/src/features/projects/ProjectReportPage.test.tsx): preview,
  coverage, money and browser printing.
- [projectsService](../../frontend/src/services/projectsService.ts): preview GET,
  report POST and saved-file GET. These use `/api/v1/projects/<id>/risk-report?limit=20`,
  `/api/v1/projects/<id>/reports` and `/api/v1/projects/<id>/reports/<report_id>/file`.
- [exports service](../../backend/app/services/exports.py),
  [bid report service](../../backend/app/risk/service.py),
  [builder](../../backend/app/risk/bid_report.py) and
  [PDF renderer](../../backend/app/risk/bid_report_pdf.py): common report data, scope
  enforcement and saved snapshot behavior.
