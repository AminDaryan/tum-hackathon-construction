import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { SheetShape } from '../../components/LoadingState.tsx';
import { Spinner } from '../../components/Spinner.tsx';
import { Skeleton, SkeletonText } from '../../components/Skeleton.tsx';
import { EdgeToggle } from '../../components/EdgeToggle.tsx';
import { useDetectorCatalogue } from '../../hooks/useDetectorCatalogue.ts';
import { useFullScreen } from '../../hooks/useFullScreen.ts';
import { useStoredToggle } from '../../hooks/useStoredToggle.ts';
import { t } from '../../i18n/messages.ts';
import { useSession } from '../../stores/useSession.ts';
import { cx } from '../../utils/classNames.ts';
import { prefersReducedMotion } from '../../app/accessibility.ts';
import type {
  CorrectionsResult,
  DatasetSummary,
  DocumentSummary,
  IssueCorrectionResult,
  Risk,
  RiskPosition,
  Row,
  ValidationIssue,
  ValidationRunDetail,
} from '../../services/apiTypes.ts';
import { DEFAULT_RISK_FILTERS, mainRisks, type RiskFilters } from '../risks/riskFilters.ts';
import { MaterialQuantitiesTab } from '../materials/MaterialQuantitiesTab.tsx';
import { isPriceRisk } from '../risks/pricing.ts';
import { isOpenStatus, riskOfIssue, riskStatus, riskTarget, shownFinding } from '../risks/riskModel.ts';
import { useRiskReport } from '../risks/useRiskReport.ts';
import { useRiskReviews } from '../risks/useRiskReviews.ts';
import { WhatIfTab } from '../scenarios/WhatIfTab.tsx';
import { RunValidationStatus } from '../validation/RunValidationStatus.tsx';
import { useStartValidationRun } from '../validation/useStartValidationRun.ts';
import { ExtractionQualityBanner } from './ExtractionQualityBanner.tsx';
import { cellIndex } from './cellIndex.ts';
import { issueTarget, type SheetTarget } from './issueTarget.ts';
import { LanguageModelActions } from './panel/LanguageModelActions.tsx';
import { PanelDivider } from './panel/PanelDivider.tsx';
import type { RiskSort } from './panel/RiskFilterBar.tsx';
import { PriceSection } from './panel/PriceSection.tsx';
import { RisksTab } from './panel/RisksTab.tsx';
import { usePanelWidth } from './panel/usePanelWidth.ts';
import { PanelScroll, WorkspacePanel } from './panel/WorkspacePanel.tsx';
import { pdfSourceFor } from './sheet/pdfLinks.ts';
import { Sheet, type Reveal } from './sheet/Sheet.tsx';
import { PropertiesTab } from './tabs/PropertiesTab.tsx';
import { useDocumentRuns } from './useDocumentRuns.ts';

const WIDE = '(min-width: 1280px)';
/** Whether the reviewer hid the side panel (wide layout), kept in this browser. */
export const PANEL_HIDDEN_KEY = 'twb.workspace.panelHidden';
/** How long the side panel takes to slide in or out, in ms (the grid's `duration-200`). */
const PANEL_MOTION_MS = 200;
/** How long edits must have settled before the table is checked again, in ms. */
export const RECHECK_DELAY_MS = 1500;

/**
 * True for `PANEL_MOTION_MS` after `hidden` changes, while the panel slides in or out: the grid
 * animates its columns only then, so dragging the divider stays immediate, and a hidden panel
 * stays in place until it has slid out. Never true when the reader asked for less motion.
 */
function usePanelMotion(hidden: boolean) {
  const [state, setState] = useState({ hidden, moving: false });
  if (state.hidden !== hidden) setState({ hidden, moving: !prefersReducedMotion() });
  useEffect(() => {
    if (!state.moving) return undefined;
    const timer = setTimeout(() => setState((current) => ({ ...current, moving: false })), PANEL_MOTION_MS);
    return () => clearTimeout(timer);
  }, [state]);
  return state.moving;
}

/** Tab ids of earlier links, mapped to the tab that holds their content now. */
const LEGACY_TABS: Readonly<Record<string, string>> = Object.freeze({
  insights: 'risks',
  pricing: 'risks',
  issues: 'risks',
  export: 'risks',
  requirements: 'properties',
});

function useWideLayout() {
  const query = useMemo(
    () => (typeof window !== 'undefined' && typeof window.matchMedia === 'function' ? window.matchMedia(WIDE) : null),
    [],
  );
  const [wide, setWide] = useState(query ? query.matches : true);
  useEffect(() => {
    if (!query) return undefined;
    const update = () => setWide(query.matches);
    query.addEventListener?.('change', update);
    return () => query.removeEventListener?.('change', update);
  }, [query]);
  return wide;
}

function scrollIntoViewSafely(element: HTMLElement | null, block: ScrollLogicalPosition = 'start') {
  if (element && typeof element.scrollIntoView === 'function') {
    element.scrollIntoView({ block, behavior: prefersReducedMotion() ? 'auto' : 'smooth' });
  }
}

interface DocumentViewProps {
  document: DocumentSummary;
  dataset: DatasetSummary;
  onReload: () => void;
}

/**
 * Everything about one open file (its name is the page's title, set by OpenFile). On the left
 * the editable sheet (the overview of the results is on the project page). The table is checked by itself: when it has no run yet, once edits
 * have settled (a cell or a price saved) and after a model was attached, replaced or removed;
 * the server returns the latest run when nothing changed. The sheet's header says "Checking…"
 * meanwhile. On the right a side panel with tabs: Properties, Risks (after a
 * validation; it opens by itself once one finishes) and the file's other views. The divider between them sets the panel's width. On the wide layout a flagged cell
 * opens its risk in the panel, so the sheet shows no note of its own; a button in the sheet's
 * header hides the panel (the sheet then takes the full width and shows the cell notes) and shows
 * it again, as does opening anything in it.
 *
 * The tab, the chosen run, the selected risk and its shown finding live in the URL (`tab`,
 * `run`, `risk`, `issue`).
 */
export function DocumentView({ document, dataset, onReload }: DocumentViewProps) {
  const panelId = useId();
  const [params, setParams] = useSearchParams();
  const tabParam = LEGACY_TABS[params.get('tab') ?? ''] ?? params.get('tab');
  const riskParam = params.get('risk');
  const issueParam = params.get('issue');
  const { health } = useSession();
  const { byId: catalogue } = useDetectorCatalogue({ profileId: dataset.profile_id });
  const documentRuns = useDocumentRuns(dataset.dataset_id, params.get('run'));
  const { runs, runsLoading, runId, run, issues, replaceIssue, reloadRuns, replaceRun, reloadRun } = documentRuns;
  const [discovery, setDiscovery] = useState<{ runId: string | null; id: string | null }>({ runId: null, id: null });
  const discoveryRunId = discovery.runId === runId ? discovery.id : null;
  const risks = useRiskReport(runId, { discoveryRunId });
  const reloadReport = risks.reload;
  const reviews = useRiskReviews(runId);
  const issueUpdated = useCallback(
    (issue: ValidationIssue) => {
      replaceIssue(issue);
      // A decision changes the run's review counts ("Finish review") and the report (a rejected
      // finding leaves it).
      reloadRun();
      reloadReport();
    },
    [replaceIssue, reloadRun, reloadReport],
  );
  const [revision, setRevision] = useState(dataset.revision);
  const [tableId, setTableId] = useState(dataset.tables[0]?.table_id ?? null);
  const table = dataset.tables.find((candidate) => candidate.table_id === tableId) ?? dataset.tables[0];
  const [rowsById, setRowsById] = useState(() => new Map<string, Row>());
  const [reveal, setReveal] = useState<Reveal | null>(null);
  const [focusDecisionKey, setFocusDecisionKey] = useState<number | null>(null);
  // "All open" on the project page opens the Risks tab with only the open risks (`status=open`).
  const [riskFilters, setRiskFilters] = useState<RiskFilters>(() =>
    params.get('status') === 'open' ? { ...DEFAULT_RISK_FILTERS, status: 'open' } : DEFAULT_RISK_FILTERS,
  );
  const [riskSort, setRiskSort] = useState<RiskSort>('priority');
  const [sheetKey, setSheetKey] = useState(0);
  const wide = useWideLayout();
  const gridRef = useRef<HTMLDivElement>(null);
  const sheetRef = useRef<HTMLDivElement>(null);
  // Full screen for the sheet (table or PDF); it survives a switch to another table.
  const fullScreen = useFullScreen(sheetRef);
  const panelRef = useRef<HTMLElement>(null);
  const staleRisk = useRef<Risk | null>(null);
  // The risk whose cell the sheet went to last (opened from the list, a cell or the URL).
  const shownRiskId = useRef<string | null>(null);
  const panelWidth = usePanelWidth(gridRef);
  const [panelHidden, setPanelHidden] = useStoredToggle(PANEL_HIDDEN_KEY);
  const sideBySide = wide && !panelHidden;
  const panelMoving = usePanelMotion(panelHidden) && wide;

  useEffect(() => {
    if (dataset.revision > revision) setRevision(dataset.revision);
  }, [dataset.revision, revision]);

  const setParam = useCallback(
    (changes: Record<string, string | null | undefined>, { replace = true }: { replace?: boolean } = {}) =>
      setParams(
        (current) => {
          const next = new URLSearchParams(current);
          for (const [key, value] of Object.entries(changes)) {
            if (value === null || value === undefined) next.delete(key);
            else next.set(key, value);
          }
          return next;
        },
        { replace },
      ),
    [setParams],
  );

  // A finished check shows its results in place: the selected risk stays (its id is stable), the
  // finding is the new run's.
  const runCompleted = (finished: ValidationRunDetail) => {
    reloadRuns();
    setParam({ run: finished.run_id, risk: selectedRisk?.risk_id ?? riskParam, issue: null });
  };
  const validation = useStartValidationRun(dataset.dataset_id, { onCompleted: runCompleted });
  // The same run, after the local model was asked for material matches (stored for later runs).
  const materialMatch = useStartValidationRun(dataset.dataset_id, { onCompleted: runCompleted, matchMaterials: true });

  // Check the table by itself when it has no run for its revision or its model changed, once
  // edits have settled. `checked` is what was checked last: the revision and the model.
  const checkKey = `${revision}/${document.model?.sha256 ?? ''}`;
  const latestRevision = runs[0]?.dataset_revision ?? 0;
  const checked = useRef<string | null>(null);
  const startCheck = validation.execute;
  useEffect(() => {
    if (runsLoading || validation.pending || checked.current === checkKey) return undefined;
    if (checked.current === null && runs.length > 0 && latestRevision >= revision) {
      checked.current = checkKey; // opened up to date
      return undefined;
    }
    const timer = setTimeout(() => {
      checked.current = checkKey;
      startCheck();
    }, RECHECK_DELAY_MS);
    return () => clearTimeout(timer);
  }, [checkKey, runsLoading, validation.pending, latestRevision, revision, runs.length, startCheck]);

  const issuesById = useMemo(() => new Map(issues.map((issue) => [issue.issue_id, issue])), [issues]);
  const hasRun = runs.length > 0;
  // A file opened on Risks (`tab=risks`) shows it while its runs load, not Properties first.
  const risksTabShown = hasRun || (runsLoading && tabParam === 'risks');
  const report = risks.report;

  // The selected risk: by its id, else the risk of the selected finding; a risk that left the
  // report after a reload (a rejection) stays shown while its id is selected.
  const foundRisk = riskParam ? (risks.byId.get(riskParam) ?? null) : issueParam ? riskOfIssue(risks.all, issueParam) : null;
  if (foundRisk) staleRisk.current = foundRisk;
  const selectedRisk = foundRisk ?? (riskParam && staleRisk.current?.risk_id === riskParam ? staleRisk.current : null);
  const shownIssue = selectedRisk
    ? shownFinding(selectedRisk, issuesById, issueParam)
    : issueParam
      ? (issuesById.get(issueParam) ?? null)
      : null;

  const openCount = useMemo(
    () => mainRisks(report).filter((risk) => isOpenStatus(riskStatus(risk, issuesById, reviews.statuses))).length,
    [report, issuesById, reviews.statuses],
  );
  // The file first (Properties), then the review (Risks) and the file's other views.
  const tabs = [
    { id: 'properties', label: t('Properties') },
    ...(risksTabShown
      ? [{ id: 'risks', label: t('Risks'), count: report ? openCount : undefined, countTone: openCount > 0 ? ('danger' as const) : undefined }]
      : []),
    { id: 'what-if', label: t('What-if') },
    { id: 'materials', label: t('Quantities') },
  ];
  const defaultTab = risksTabShown ? 'risks' : 'properties';
  const tab = tabParam && tabs.some((candidate) => candidate.id === tabParam) ? tabParam : defaultTab;

  const sheetFindings = useMemo(() => cellIndex(issues), [issues]);

  // A risk opened from a link: the sheet goes to its cell once, so its row (and price) is at hand.
  const selectedRiskId = selectedRisk?.risk_id ?? null;
  useEffect(() => {
    const selectionId = issueParam ?? selectedRiskId;
    if (!selectionId || shownRiskId.current === selectionId) return;
    const target = selectedRisk ? riskTarget(selectedRisk, shownIssue) : issueTarget(shownIssue);
    if (!target?.rowId) return;
    shownRiskId.current = selectionId;
    if (target.tableId && target.tableId !== tableId && dataset.tables.some((candidate) => candidate.table_id === target.tableId)) {
      setTableId(target.tableId);
    }
    setReveal({ ...target, nonce: Date.now() + Math.random() });
    // Only when another risk is selected; the risk object changes with every report reload.
  }, [selectedRiskId, issueParam, shownIssue?.issue_id]);

  const revealCell = useCallback(
    ({ tableId: targetTable, rowId, columnId }: SheetTarget) => {
      if (targetTable && targetTable !== tableId && dataset.tables.some((candidate) => candidate.table_id === targetTable)) {
        setTableId(targetTable);
      }
      setReveal({ tableId: targetTable, rowId, columnId: columnId ?? null, nonce: Date.now() + Math.random() });
      scrollIntoViewSafely(sheetRef.current);
    },
    [dataset.tables, tableId],
  );
  // Opening something in the panel shows it: scrolled to when stacked, shown again when hidden.
  const showPanel = useCallback(() => {
    if (!wide) scrollIntoViewSafely(panelRef.current);
    else setPanelHidden(false);
  }, [wide, setPanelHidden]);

  const openRisk = useCallback(
    (risk: Risk) => {
      shownRiskId.current = risk.risk_id;
      setParam({ tab: 'risks', risk: risk.risk_id, issue: null }, { replace: false });
      const target = riskTarget(risk, shownFinding(risk, issuesById));
      if (target) {
        if (target.tableId && target.tableId !== tableId && dataset.tables.some((candidate) => candidate.table_id === target.tableId)) {
          setTableId(target.tableId);
        }
        setReveal({ ...target, nonce: Date.now() + Math.random() });
        if (wide) scrollIntoViewSafely(sheetRef.current);
      }
      showPanel();
    },
    [dataset.tables, issuesById, setParam, showPanel, tableId, wide],
  );
  const openFinding = useCallback(
    (issue: ValidationIssue) => {
      const risk = riskOfIssue(risks.all, issue.issue_id);
      shownRiskId.current = risk?.risk_id ?? null;
      setParam({ tab: 'risks', risk: risk?.risk_id ?? null, issue: issue.issue_id }, { replace: false });
      const target = issueTarget(issue);
      if (target) {
        if (target.tableId !== tableId && dataset.tables.some((candidate) => candidate.table_id === target.tableId)) {
          setTableId(target.tableId);
        }
        setReveal({ ...target, nonce: Date.now() + Math.random() });
        if (wide) scrollIntoViewSafely(sheetRef.current);
      }
      showPanel();
    },
    [dataset.tables, risks.all, setParam, showPanel, tableId, wide],
  );
  const reviewFromCell = useCallback(
    (issue: ValidationIssue) => {
      openFinding(issue);
      setFocusDecisionKey((key) => (key ?? 0) + 1);
    },
    [openFinding],
  );
  // On the wide layout a flagged cell opens its risk (the open one when the cell is part of it).
  const cellFindingsChosen = useCallback(
    (found: readonly ValidationIssue[]) => {
      const owned = found
        .map((issue) => riskOfIssue(risks.all, issue.issue_id))
        .filter((risk): risk is Risk => Boolean(risk));
      if (!owned.length) return;
      const risk = owned.find((candidate) => candidate.risk_id === selectedRisk?.risk_id) ?? owned[0];
      if (risk.risk_id === selectedRisk?.risk_id) return;
      const issue = found.find((candidate) => (risk.source_issue_ids ?? []).includes(candidate.issue_id));
      shownRiskId.current = risk.risk_id;
      setParam({ tab: 'risks', risk: risk.risk_id, issue: issue?.issue_id ?? null });
    },
    [risks.all, selectedRisk, setParam],
  );
  // Approve: the risk's cell opens for editing in the sheet.
  const editApproved = useCallback(
    (risk: Risk) => {
      const target = riskTarget(risk, shownFinding(risk, issuesById));
      if (!target?.rowId) return;
      if (target.tableId && target.tableId !== tableId && dataset.tables.some((candidate) => candidate.table_id === target.tableId)) {
        setTableId(target.tableId);
      }
      setReveal({ ...target, edit: true, nonce: Date.now() + Math.random() });
      scrollIntoViewSafely(sheetRef.current);
    },
    [dataset.tables, issuesById, tableId],
  );
  const closeRisk = useCallback(() => {
    setFocusDecisionKey(null);
    setParam({ risk: null, issue: null }, { replace: false });
  }, [setParam]);
  const showPosition = useCallback(
    (position: RiskPosition) => revealCell({ tableId: position.table_id, rowId: position.row_id, columnId: position.cells?.[0]?.column_id ?? null }),
    [revealCell],
  );
  const showProperties = useCallback(() => {
    setParam({ tab: 'properties' });
    showPanel();
  }, [setParam, showPanel]);
  const rowsLoaded = useCallback((rows: Row[]) => {
    setRowsById((current) => {
      const next = new Map(current);
      for (const row of rows) next.set(row.row_id, row);
      return next;
    });
  }, []);
  const reloadTable = useCallback(() => {
    setSheetKey((key) => key + 1);
    onReload();
  }, [onReload]);
  const shownTarget = selectedRisk ? riskTarget(selectedRisk, shownIssue) : issueTarget(shownIssue);
  const targetRow = shownTarget?.rowId ? (rowsById.get(shownTarget.rowId) ?? null) : null;
  // A new price from the risk's price section: the sheet reloads and goes back to the row.
  const revealTargetRow = useCallback(() => {
    if (targetRow) setReveal({ tableId: table?.table_id, rowId: targetRow.row_id, columnId: null, nonce: Date.now() + Math.random() });
  }, [targetRow, table]);
  const priceRevised = useCallback(
    (result: CorrectionsResult) => {
      if (result?.revision) setRevision(result.revision);
      reloadTable();
      revealTargetRow();
    },
    [reloadTable, revealTargetRow],
  );
  const priceCorrected = useCallback(
    (result: IssueCorrectionResult) => {
      reloadTable();
      reloadRuns();
      revealTargetRow();
      const rerun = result.validation_run;
      if (rerun?.run_id) setParam({ run: rerun.run_id, issue: null, tab: 'risks' });
    },
    [reloadTable, reloadRuns, revealTargetRow, setParam],
  );
  const discovered = useCallback((id: string | null) => setDiscovery({ runId, id }), [runId]);

  const issueTargetCell = issueTarget(shownIssue);
  const issueRow = issueTargetCell ? (rowsById.get(issueTargetCell.rowId) ?? null) : null;
  const pdfSource = useMemo(() => pdfSourceFor(document), [document]);
  // Quiet: the live region of RunValidationStatus announces the check to screen readers.
  const actions = validation.pending ? (
    <span aria-hidden="true" className="flex items-center gap-2 text-caption text-ink-tertiary">
      <Spinner size="sm" />
      {t('Checking…')}
    </span>
  ) : null;

  // On the wide layout the panel fills the row beside the sheet; stacked under the sheet it is one
  // viewport tall: below the top bar (3.5rem) and inside the page margins (3rem).
  const panel = (
    <WorkspacePanel
      ref={panelRef}
      id={panelId}
      tabs={tabs}
      selectedId={tab}
      onSelect={(id) => setParam({ tab: id })}
      className={wide ? 'h-full' : 'h-project-page scroll-mt-4'}
    >
      {tab === 'risks' && (
        <RisksTab
          report={report}
          loading={risks.loading || runsLoading}
          error={risks.error}
          onRetry={reloadReport}
          discoveryRunId={discoveryRunId}
          issuesById={issuesById}
          filters={riskFilters}
          onFiltersChange={setRiskFilters}
          sort={riskSort}
          onSortChange={setRiskSort}
          selectedRisk={selectedRisk}
          shownIssue={shownIssue}
          onOpenRisk={openRisk}
          onOpenFinding={openFinding}
          onCloseRisk={closeRisk}
          onIssueUpdated={issueUpdated}
          reviews={reviews}
          onApproved={editApproved}
          price={
            selectedRisk && targetRow ? (
              <PriceSection
                key={selectedRisk.risk_id}
                risks={risks.all}
                currency={report?.context?.currency ?? null}
                issues={issues}
                issuesById={issuesById}
                row={targetRow}
                table={table}
                open={isPriceRisk(selectedRisk, issuesById)}
                onShowInSheet={revealCell}
                datasetId={dataset.dataset_id}
                revision={revision}
                onRevised={priceRevised}
                onCorrected={priceCorrected}
              />
            ) : null
          }
          row={issueRow}
          positionRow={targetRow}
          table={table}
          catalogue={catalogue}
          onRevealCell={revealCell}
          onShowPosition={showPosition}
          focusDecisionKey={focusDecisionKey}
          billName={document.original_filename}
          currency={report?.context?.currency ?? null}
          run={run}
          runs={runs}
          runId={runId}
          datasetId={dataset.dataset_id}
          onRunChange={(id) => setParam({ run: id, risk: null, issue: null })}
          onRunUpdated={replaceRun}
          modelActions={
            report ? (
              <LanguageModelActions
                runId={report.run_id}
                datasetId={dataset.dataset_id}
                discovery={report.discovery}
                localModelReady={Boolean(health?.llm?.ready)}
                billReviewAvailable={Boolean(health?.bill_review_available)}
                onDiscovered={discovered}
                onMatchMaterials={materialMatch.execute}
                matchingMaterials={materialMatch.pending}
                onRunCompleted={runCompleted}
              />
            ) : null
          }
        />
      )}
      {tab === 'materials' && (
        <MaterialQuantitiesTab
          key={`${dataset.dataset_id}/${revision}`}
          dataset={dataset}
          revision={revision}
          billName={document.original_filename}
          onShowPosition={(position) => revealCell({ tableId: position.tableId, rowId: position.rowId, columnId: null })}
        />
      )}
      {tab === 'what-if' && (
        <WhatIfTab key={`${dataset.dataset_id}/${revision}`} dataset={dataset} revision={revision} />
      )}
      {tab === 'properties' && (
        <PanelScroll>
          <PropertiesTab document={document} dataset={dataset} onModelChanged={onReload} />
        </PanelScroll>
      )}
    </WorkspacePanel>
  );

  // Wide: the page fits the window (below the top bar and inside the page margins) and the sheet
  // takes the height left under the validation's status, so the page itself never scrolls.
  return (
    <div className={wide ? 'flex h-project-page min-h-[32rem] flex-col gap-4' : 'flex flex-col gap-4'}>
      <ExtractionQualityBanner dataset={dataset} onShowDetails={showProperties} />
      <div
        ref={gridRef}
        // The divider's column is its hit area and holds the arrow that hides or shows the panel:
        // 44 px, 48 px for a coarse pointer. With the panel hidden the column stays for the arrow
        // and the panel's column is 0, so hiding and showing slide the panel.
        className={
          wide
            ? cx(
                'grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] [--divider:44px] pointer-coarse:[--divider:48px]',
                panelMoving && 'transition-[grid-template-columns] duration-200 ease-standard',
              )
            : 'space-y-6'
        }
        style={wide ? { gridTemplateColumns: `minmax(0,1fr) var(--divider) ${sideBySide ? panelWidth.width : 0}px` } : undefined}
      >
        <div className={wide ? 'flex min-h-0 min-w-0 flex-col gap-3' : 'min-w-0 space-y-6'}>
          <RunValidationStatus
            pending={validation.pending}
            error={validation.error}
            result={validation.result}
            trackedRun={validation.trackedRun}
          />
          <div ref={sheetRef} className={wide ? 'flex min-h-0 flex-1 flex-col' : 'scroll-mt-4'}>
            {table ? (
              <Sheet
                key={`${table.table_id}/${sheetKey}`}
                datasetId={dataset.dataset_id}
                table={table}
                tables={dataset.tables}
                onTableChange={setTableId}
                revision={revision}
                onRevised={(result) => setRevision(result.revision)}
                onReload={reloadTable}
                findingsIndex={sheetFindings}
                selectedIssue={shownIssue}
                reveal={reveal && reveal.tableId === table.table_id ? reveal : null}
                onReview={reviewFromCell}
                showNotes={!sideBySide}
                onCellFindings={sideBySide ? cellFindingsChosen : undefined}
                onRowsLoaded={rowsLoaded}
                actions={actions}
                pdf={pdfSource}
                fill={wide}
                fullScreen={fullScreen.active}
                onFullScreenChange={(on) => (on ? fullScreen.enter() : fullScreen.exit())}
              />
            ) : (
              <p className="text-body text-ink-secondary">{t('This file has no table to show.')}</p>
            )}
          </div>
        </div>
        {wide && (
          <div className="relative min-h-0">
            {sideBySide && (
              <PanelDivider
                width={panelWidth.width}
                min={panelWidth.min}
                max={panelWidth.max}
                onChange={panelWidth.setWidth}
                onReset={panelWidth.reset}
                controls={panelId}
                className="h-full"
              />
            )}
            {!fullScreen.active && (
              <EdgeToggle
                label={panelHidden ? t('Show the side panel') : t('Hide the side panel')}
                icon={panelHidden ? ChevronLeft : ChevronRight}
                expanded={!panelHidden}
                controls={panelHidden ? undefined : panelId}
                onPress={() => setPanelHidden(!panelHidden)}
                tooltipPlacement="start"
                className="left-1/2 -translate-x-1/2"
              />
            )}
          </div>
        )}
        {!wide && panel}
        {(sideBySide || panelMoving) && (
          // The panel at its own width, held to the right edge, so its column slides it in and out.
          <div inert={!sideBySide} aria-hidden={!sideBySide || undefined} className="flex min-w-0 justify-end overflow-hidden">
            <div className="h-full shrink-0" style={{ width: panelWidth.width }}>
              {panel}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

const noop = () => {};

/**
 * A file while it loads, in the layout it will have: the sheet's box (its title, buttons and
 * cell bar as grey shapes over grey cells) and, on the wide layout, the side panel at the width
 * the reviewer left it (or hidden if they hid it), with its first tabs. Nothing moves when the
 * file arrives.
 */
export function DocumentPlaceholder({ label }: { label: string }) {
  const wide = useWideLayout();
  const gridRef = useRef<HTMLDivElement>(null);
  const panelWidth = usePanelWidth(gridRef);
  const [panelHidden] = useStoredToggle(PANEL_HIDDEN_KEY);
  const sideBySide = wide && !panelHidden;
  const [params] = useSearchParams();
  // A file opened on Risks shows that tab selected from the first frame.
  const onRisks = (LEGACY_TABS[params.get('tab') ?? ''] ?? params.get('tab')) === 'risks';
  const tabs = [
    { id: 'properties', label: t('Properties') },
    ...(onRisks ? [{ id: 'risks', label: t('Risks') }] : []),
    { id: 'materials', label: t('Quantities') },
  ];
  return (
    <div className={wide ? 'flex h-project-page min-h-[32rem] flex-col gap-4' : 'flex flex-col gap-4'}>
      <p role="status" className="sr-only">
        {label}
      </p>
      <div
        ref={gridRef}
        aria-hidden="true"
        className={wide ? 'grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)] [--divider:44px] pointer-coarse:[--divider:48px]' : 'space-y-6'}
        style={wide ? { gridTemplateColumns: sideBySide ? `minmax(0,1fr) var(--divider) ${panelWidth.width}px` : 'minmax(0,1fr)' } : undefined}
      >
        <section className={cx('overflow-hidden rounded-lg border border-hairline bg-surface', wide ? 'flex min-h-0 flex-col' : 'h-[32rem]')}>
          <div className="flex min-h-14 items-center justify-between gap-4 border-b border-hairline px-4 py-1.5">
            <Skeleton className="h-4 w-40" />
            <div className="flex items-center gap-2">
              <Skeleton className="h-11 w-40" />
              <Skeleton className="size-11" />
            </div>
          </div>
          <div className="flex min-h-10 items-center border-b border-hairline px-4 py-1.5">
            <Skeleton className="h-3 w-80 max-w-full" />
          </div>
          <div className="min-h-0 flex-1 overflow-hidden">
            <SheetShape rows={24} />
          </div>
        </section>
        {sideBySide && <div />}
        {(!wide || sideBySide) && (
          <div inert className={wide ? 'h-full min-h-0' : 'h-project-page'}>
            <WorkspacePanel tabs={tabs} selectedId={onRisks ? 'risks' : 'properties'} onSelect={noop} className="h-full">
              <PanelScroll>
                <div className="flex flex-col gap-4">
                  <Skeleton className="h-4 w-16" />
                  <div className="rounded-lg border border-hairline p-4">
                    <SkeletonText lines={8} />
                  </div>
                  <SkeletonText lines={4} />
                </div>
              </PanelScroll>
            </WorkspacePanel>
          </div>
        )}
      </div>
    </div>
  );
}
