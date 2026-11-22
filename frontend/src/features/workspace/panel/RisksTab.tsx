import { ChevronLeft, Keyboard } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Button } from '../../../components/Button.tsx';
import { Disclosure } from '../../../components/Disclosure.tsx';
import { ErrorState } from '../../../components/ErrorState.tsx';
import { LoadingState } from '../../../components/LoadingState.tsx';
import { useApiResource } from '../../../hooks/useApiResource.ts';
import { t } from '../../../i18n/messages.ts';
import { getRiskReport } from '../../../services/validationService.ts';
import { formatCount } from '../../../utils/format.ts';
import {
  candidateRisks,
  filterOptions,
  statusCounts,
  visibleRisks,
  type RiskFilters,
} from '../../risks/riskFilters.ts';
import { classificationOf, isOpenStatus, riskStatus, shortTitle, type IssuesById } from '../../risks/riskModel.ts';
import type { useRiskReviews } from '../../risks/useRiskReviews.ts';
import { RunReviewControls } from '../../validation/RunReviewControls.tsx';
import { FindingComments } from '../../collaboration/FindingComments.tsx';
import { isTaskOverdue } from '../../collaboration/tasks.ts';
import { useCollaboration } from '../../collaboration/useCollaboration.ts';
import { useRunTasks } from '../../collaboration/useRunTasks.ts';
import { EmailDraftButton } from '../../email/EmailDraft.tsx';
import { risksEmailDraft } from '../../email/emailDraft.ts';
import { IssueDetails } from '../context/IssueDetails.tsx';
import { ExportTab } from '../tabs/ExportTab.tsx';
import { ClientQuestions } from './ClientQuestions.tsx';
import { RiskDetail } from './RiskDetail.tsx';
import { RiskFilterBar, type RiskSort } from './RiskFilterBar.tsx';
import { RiskRow } from './RiskRow.tsx';
import { PanelScroll } from './WorkspacePanel.tsx';
import type { KeyboardEvent, ReactNode } from 'react';
import type {
  DetectorDescriptor,
  Risk,
  RiskPosition,
  RiskReport,
  Row,
  TableSummary,
  ValidationIssue,
  ValidationRunDetail,
  ValidationRunSummary,
} from '../../../services/apiTypes.ts';
import type { SheetTarget } from '../issueTarget.ts';

function inTextField(target: EventTarget | null) {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName);
}

/** The next open risk after this one in the list, wrapping; null when every other is decided. */
function nextOpenRisk(list: Risk[], risk: Risk | null | undefined, statusOf: (risk: Risk) => string) {
  if (!risk) return null;
  const start = list.findIndex((candidate) => candidate.risk_id === risk.risk_id);
  const ordered = [...list.slice(start + 1), ...list.slice(0, Math.max(start, 0))];
  return ordered.find((candidate) => candidate.risk_id !== risk.risk_id && isOpenStatus(statusOf(candidate))) ?? null;
}

const DECISION_KEYS: Readonly<Record<string, string>> = Object.freeze({ a: 'approved', r: 'rejected', c: 'in_review' });

interface RisksTabProps {
  report?: RiskReport | null;
  loading?: boolean;
  error?: Error | null;
  onRetry: () => void;
  discoveryRunId?: string | null;
  issuesById: IssuesById;
  filters: RiskFilters;
  onFiltersChange: (filters: RiskFilters) => void;
  sort: RiskSort;
  onSortChange: (sort: RiskSort) => void;
  selectedRisk?: Risk | null;
  shownIssue?: ValidationIssue | null;
  onOpenRisk: (risk: Risk) => void;
  onOpenFinding: (issue: ValidationIssue) => void;
  onCloseRisk: () => void;
  onIssueUpdated: (issue: ValidationIssue) => void;
  /** The decisions on risks without a finding (`useRiskReviews`). */
  reviews: Pick<ReturnType<typeof useRiskReviews>, 'statuses' | 'byId' | 'save'>;
  onApproved?: (risk: Risk) => void;
  /** The price of the open risk's position (`PriceSection`). */
  price?: ReactNode;
  row?: Row | null;
  /** The sheet row of the open risk's position, for the email draft. */
  positionRow?: Row | null;
  table?: TableSummary | null;
  catalogue?: ReadonlyMap<string, DetectorDescriptor>;
  onRevealCell: (target: SheetTarget) => void;
  onShowPosition: (position: RiskPosition) => void;
  focusDecisionKey?: number | null;
  /** The file name of the bill, named in email drafts. */
  billName?: string | null;
  currency?: string | null;
  run?: ValidationRunDetail | null;
  runs: ValidationRunSummary[];
  runId?: string | null;
  datasetId: string;
  onRunChange: (runId: string) => void;
  onRunUpdated: (run: ValidationRunDetail) => void;
  /** At the end: what the language models can do for the run (`LanguageModelActions`). */
  modelActions?: ReactNode;
}

/**
 * Risks: every risk of the validation as a list with search, status chips, filters and sort,
 * and a drill-in detail for one risk with its decision pinned at the bottom. Keys while focus is
 * in the tab and not in a text field (opening a risk from the list moves focus into the tab):
 * J and K move, Enter opens the risk, A approves, R rejects, C asks for clarification (in the
 * list: the highlighted risk, which opens), Esc goes back to the list. A bill whose every reminder
 * was kept in the record lists the record (`mainRisks`).
 * Under the list: the questions for the client, the review of the run, closed until asked for
 * the downloads and earlier validations, and what the local language model can do.
 */
export function RisksTab({
  report,
  loading,
  error,
  onRetry,
  discoveryRunId,
  issuesById,
  filters,
  onFiltersChange,
  sort,
  onSortChange,
  selectedRisk,
  shownIssue,
  onOpenRisk,
  onOpenFinding,
  onCloseRisk,
  onIssueUpdated,
  reviews,
  onApproved,
  price,
  row,
  positionRow,
  table,
  catalogue,
  onRevealCell,
  onShowPosition,
  focusDecisionKey,
  billName,
  currency,
  run,
  runs,
  runId,
  datasetId,
  onRunChange,
  onRunUpdated,
  modelActions,
}: RisksTabProps) {
  const rootRef = useRef<HTMLDivElement>(null);
  const focusAfterBack = useRef<string | null>(null);
  const tasks = useRunTasks(runId);
  const me = useCollaboration()?.reviewer?.handle ?? null;
  const sorted = useApiResource(
    // Only fetched with a run id (enabled).
    (signal) => getRiskReport(runId!, { sortBy: sort, discoveryRunId: discoveryRunId ?? undefined }, { signal }),
    [runId, sort, discoveryRunId],
    { enabled: Boolean(runId) && sort !== 'priority' },
  );
  // A non-default sort keeps the priority order on screen until its own copy arrives.
  const base = sort !== 'priority' && sorted.data?.run_id === report?.run_id ? sorted.data : report;

  const candidates = useMemo(() => candidateRisks(base, filters.includeRecord), [base, filters.includeRecord]);
  const deadlineCandidates = useMemo(
    () =>
      candidates.filter((risk) => {
        const riskTasks = (risk.source_issue_ids ?? []).map((id) => tasks.get(id));
        if (filters.overdueOnly && !riskTasks.some(isTaskOverdue)) return false;
        if (filters.assignee === 'me') return riskTasks.some((task) => task?.assignee && task.assignee === me);
        if (filters.assignee === 'none') return !riskTasks.some((task) => task?.assignee);
        return true;
      }),
    [candidates, filters.overdueOnly, filters.assignee, tasks, me],
  );
  const statuses = reviews.statuses;
  const statusOf = useCallback((risk: Risk) => riskStatus(risk, issuesById, statuses), [issuesById, statuses]);
  const visible = useMemo(
    () => visibleRisks(deadlineCandidates, filters, issuesById, statuses),
    [deadlineCandidates, filters, issuesById, statuses],
  );
  const counts = useMemo(
    () => statusCounts(deadlineCandidates, filters, issuesById, statuses),
    [deadlineCandidates, filters, issuesById, statuses],
  );
  const options = useMemo(() => filterOptions(candidates, filters, issuesById), [candidates, filters, issuesById]);
  const selectedId = selectedRisk?.risk_id ?? null;
  const inList = selectedId ? visible.some((risk) => risk.risk_id === selectedId) : false;
  // A risk opened from the sheet that the filters hide steps through the list it belongs to,
  // unfiltered; a kept reminder the list does not show has no place in it (no "N of M") and
  // "Next risk" goes on in the shown list.
  const listed = useMemo(() => {
    if (!selectedId || inList) return visible;
    const pool = candidateRisks(base, filters.includeRecord);
    return pool.some((risk) => risk.risk_id === selectedId) ? pool : visible;
  }, [selectedId, inList, base, filters.includeRecord, visible]);
  // The list the open risk was opened from, kept while the detail is open: a decision moves a
  // risk out of a status filter, and the counter, the arrows and "Next risk" must still step
  // through the list the reviewer was in. Set while rendering, when another list is entered.
  const [trail, setTrail] = useState<string[] | null>(null);
  const onTrail = Boolean(selectedId && trail?.includes(selectedId));
  if (selectedId && !onTrail && listed.some((risk) => risk.risk_id === selectedId)) {
    setTrail(listed.map((risk) => risk.risk_id));
  } else if (!selectedId && trail) {
    setTrail(null);
  }
  const navigation = useMemo(() => {
    if (!onTrail || !trail) return listed;
    const byId = new Map(candidateRisks(base, true).map((risk) => [risk.risk_id, risk]));
    return trail
      .map((id) => byId.get(id) ?? (id === selectedId ? selectedRisk : null))
      .filter((risk): risk is Risk => Boolean(risk));
  }, [onTrail, trail, listed, base, selectedId, selectedRisk]);
  const index = selectedId ? navigation.findIndex((risk) => risk.risk_id === selectedId) : -1;
  const detailOpen = Boolean(selectedRisk);
  const findings = useMemo(
    () =>
      (selectedRisk?.source_issue_ids ?? [])
        .map((id) => issuesById.get(id))
        .filter((issue): issue is ValidationIssue => Boolean(issue)),
    [selectedRisk, issuesById],
  );
  const nextRisk = useMemo(() => nextOpenRisk(navigation, selectedRisk, statusOf), [navigation, selectedRisk, statusOf]);

  const back = useCallback(() => {
    focusAfterBack.current = selectedId;
    onCloseRisk();
  }, [selectedId, onCloseRisk]);

  // Back in the list, the keyboard returns to the risk that was open.
  useEffect(() => {
    if (detailOpen || !focusAfterBack.current) return;
    const id = focusAfterBack.current;
    focusAfterBack.current = null;
    const rowButton = [...(rootRef.current?.querySelectorAll<HTMLElement>('[data-risk-id]') ?? [])].find(
      (element) => element.dataset.riskId === id,
    );
    rowButton?.focus();
  }, [detailOpen]);

  // A risk opened from the list replaces the row that had focus, which leaves focus on the page
  // body, where the tab's keys do not reach: focus moves into the tab. Focus anywhere else (a
  // sheet cell, a field, the arrows) stays where it is.
  useEffect(() => {
    if (!selectedId || (document.activeElement && document.activeElement !== document.body)) return;
    rootRef.current?.focus({ preventScroll: true });
  }, [selectedId]);

  const move = (step: number) => {
    if (detailOpen) {
      const target = navigation[index + step];
      if (index >= 0 && target) onOpenRisk(target);
      return;
    }
    const buttons = [...(rootRef.current?.querySelectorAll<HTMLElement>('[data-risk-id]') ?? [])];
    if (!buttons.length) return;
    const at = buttons.findIndex((button) => button === document.activeElement);
    const target = buttons[Math.min(Math.max(at + step, 0), buttons.length - 1)] ?? buttons[0];
    target.focus();
  };

  // A decision key pressed on a row of the list opens that risk and decides it there, so it is
  // saved, announced and followed up exactly as in the detail.
  const decisionAfterOpen = useRef<string | null>(null);
  useEffect(() => {
    const decision = decisionAfterOpen.current;
    if (!selectedId || !decision) return;
    decisionAfterOpen.current = null;
    rootRef.current?.querySelector<HTMLElement>(`[data-decision="${decision}"]:not([disabled])`)?.click();
  }, [selectedId]);

  const handleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || inTextField(event.target)) return;
    const key = event.key.toLowerCase();
    const rowId = !detailOpen && event.target instanceof HTMLElement ? event.target.dataset.riskId : undefined;
    const rowRisk = rowId ? visible.find((risk) => risk.risk_id === rowId) : undefined;
    if (key === 'j' || key === 'k') {
      event.preventDefault();
      move(key === 'j' ? 1 : -1);
    } else if (DECISION_KEYS[key] && rowRisk) {
      event.preventDefault();
      decisionAfterOpen.current = DECISION_KEYS[key];
      onOpenRisk(rowRisk);
    } else if (DECISION_KEYS[key] && detailOpen) {
      const button = rootRef.current?.querySelector<HTMLElement>(`[data-decision="${DECISION_KEYS[key]}"]:not([disabled])`);
      if (button) {
        event.preventDefault();
        button.click();
      }
    } else if (event.key === 'Escape' && detailOpen) {
      event.preventDefault();
      back();
    }
  };

  let body;
  if (error && !report) {
    body = (
      <PanelScroll>
        <ErrorState error={error} title={t('The risks could not be loaded')} onRetry={onRetry} compact />
      </PanelScroll>
    );
  } else if (selectedRisk) {
    body = (
      <RiskDetail
        risk={selectedRisk}
        title={shortTitle(selectedRisk, issuesById)}
        classification={classificationOf(selectedRisk, issuesById)}
        status={statusOf(selectedRisk)}
        review={reviews.byId.get(selectedRisk.risk_id) ?? null}
        findings={findings}
        issue={shownIssue}
        position={index >= 0 ? { index, total: navigation.length } : null}
        onBack={back}
        onPrevious={() => index > 0 && onOpenRisk(navigation[index - 1])}
        onNext={() => index >= 0 && index < navigation.length - 1 && onOpenRisk(navigation[index + 1])}
        onSelectFinding={onOpenFinding}
        onIssueUpdated={onIssueUpdated}
        onSaveReview={reviews.save}
        onApproved={onApproved}
        nextRisk={nextRisk}
        onOpenRisk={onOpenRisk}
        price={price}
        row={row}
        positionRow={positionRow}
        table={table}
        catalogue={catalogue}
        onRevealCell={onRevealCell}
        onShowPosition={onShowPosition}
        focusDecisionKey={focusDecisionKey}
        billName={billName}
        currency={currency}
      />
    );
  } else if (shownIssue) {
    body = (
      <PanelScroll className="space-y-4">
        <Button variant="link" icon={ChevronLeft} onPress={onCloseRisk}>{t('All risks')}</Button>
        <FindingComments key={shownIssue.issue_id} issueId={shownIssue.issue_id} />
        <IssueDetails issue={shownIssue} row={row} table={table ?? undefined} catalogue={catalogue} onRevealCell={onRevealCell} onRetryHistory={onRetry} />
      </PanelScroll>
    );
  } else if (!report) {
    body = (
      <PanelScroll>
        {loading ? (
          <LoadingState variant="list" label={t('Reading the risks of this validation…')} />
        ) : (
          <p className="text-callout text-ink-secondary">{t('No validation to show yet.')}</p>
        )}
      </PanelScroll>
    );
  } else {
    const total = candidates.length;
    body = (
      <PanelScroll className="space-y-4">
        <RiskFilterBar
          filters={filters}
          onChange={onFiltersChange}
          counts={counts}
          options={options}
          sort={sort}
          onSortChange={onSortChange}
          recordCount={base?.risks?.length ? (base.record?.length ?? 0) : 0}
          canFilterMine={Boolean(me)}
        />
        {visible.length === 0 ? (
          <p className="py-6 text-center text-body text-ink-secondary">
            {total === 0 ? t('No risk was found in this validation.') : t('No risk matches these filters.')}
          </p>
        ) : (
          <ul aria-label={t('Risks')} className="-mx-3 divide-y divide-hairline border-y border-hairline">
            {visible.map((risk) => (
              <li key={risk.risk_id}>
                <RiskRow
                  risk={risk}
                  title={shortTitle(risk, issuesById)}
                  classification={classificationOf(risk, issuesById)}
                  status={statusOf(risk)}
                  task={(risk.source_issue_ids ?? []).map((id) => tasks.get(id)).find(isTaskOverdue)
                    ?? (risk.source_issue_ids ?? []).map((id) => tasks.get(id)).find(Boolean)}
                  selected={risk.risk_id === selectedId}
                  onSelect={onOpenRisk}
                />
              </li>
            ))}
          </ul>
        )}
        <div className="flex items-center justify-between gap-2 text-caption text-ink-secondary">
          <p aria-live="polite" className="sr-only">
            {total === 1
              ? t('Showing {count} of {total} risk.', { count: formatCount(visible.length), total: formatCount(total) })
              : t('Showing {count} of {total} risks.', { count: formatCount(visible.length), total: formatCount(total) })}
          </p>
          <span aria-hidden="true">{sort !== 'priority' && sorted.loading ? t('Sorting…') : ''}</span>
          <span
            className="inline-flex items-center gap-1"
            title={t('J and K move, A approves, R rejects, C asks for clarification, Esc goes back.')}
          >
            <Keyboard aria-hidden="true" className="size-4" />
            {t('Shortcuts')}
            <span className="sr-only">{t('J and K move, A approves, R rejects, C asks for clarification, Esc goes back.')}</span>
          </span>
        </div>
        {visible.length > 0 && (
          <EmailDraftButton
            draft={risksEmailDraft({ risks: visible, titleOf: (risk) => shortTitle(risk, issuesById), billName })}
            label={visible.length === 1 ? t('Email the shown risk') : t('Email the {count} shown risks', { count: formatCount(visible.length) })}
            title={t('Email about the shown risks')}
          />
        )}
        <ClientQuestions questions={report.open_questions} />
        {run && issuesById.size > 0 && (
          <section aria-label={t('Review of this run')} className="border-t border-hairline pt-3">
            <RunReviewControls run={run} onUpdated={onRunUpdated} />
          </section>
        )}
        <Disclosure title={t('Downloads and earlier validations')} className="border-t border-hairline pt-2">
          <section aria-label={t('Download the results')}>
            <ExportTab datasetId={datasetId} runs={runs} runId={runId} onRunChange={onRunChange} />
          </section>
        </Disclosure>
        {modelActions}
      </PanelScroll>
    );
  }

  return (
    // The keys of the tab act only while focus is inside it.
    <div ref={rootRef} tabIndex={-1} onKeyDown={handleKeyDown} className="flex min-h-0 flex-1 flex-col outline-none">
      {body}
    </div>
  );
}
