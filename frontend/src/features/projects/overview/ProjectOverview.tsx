import { RotateCw } from 'lucide-react';
import { useState, type ReactNode } from 'react';
import { Button } from '../../../components/Button.tsx';
import type { DataTableColumn } from '../../../components/DataTable.tsx';
import { TableCard, TWO_LINE_ROW_REM } from '../../../components/TableCard.tsx';
import { useApiResource } from '../../../hooks/useApiResource.ts';
import { t } from '../../../i18n/messages.ts';
import type { DocumentSummary, FileGroup, Project, ReviewCounts, ValidationIssue } from '../../../services/apiTypes.ts';
import { listTopIssues } from '../../../services/projectsService.ts';
import { cx } from '../../../utils/classNames.ts';
import { absDecimal, decimalToString, parseDecimal, roundDecimal } from '../../../utils/decimal.ts';
import { formatDecimal } from '../../../utils/format.ts';
import { PriorityBadge } from '../../workspace/panel/RiskBits.tsx';
import { useProject, type OpenFile } from '../ProjectContext.tsx';
import { findingsBySeverity, hasValidationResult, projectFigures } from '../projectOverview.ts';
import { OverviewFigures } from './OverviewFigures.tsx';
import { RisksChart } from './RisksChart.tsx';

/** Rows a page before the box is laid out. */
const RISKS_PAGE_SIZE = 5;

interface ProjectOverviewProps {
  projectId: string;
  /** null while the project loads: the figures and the risks are grey. */
  project: Project | null;
  documents: DocumentSummary[];
  reviewCounts: ReviewCounts;
  /** Each file's group (`ProjectDetail.groups`): the figures count the bills only. */
  groups?: Record<string, FileGroup>;
  /** The project's status and its actions, at the top right. */
  actions: ReactNode;
  onOpenIssue: OpenFile;
  className?: string;
}

/**
 * The project overview: its figures over all bills (bills, findings, to review) and the findings
 * by priority on top, then the risks of the project as a table: every finding still to review
 * over the bills of the last validation, the most severe first, then the largest financial
 * impact (a comparison with reference prices is shown as one, not as money lost), as many a page
 * as fit the box. A row opens the finding in the Workspace. Before a validation, or after one
 * that failed, the table says "Not validated yet" and has no pages (the figures say "Not
 * validated" until a bill has a result); while one runs, or while the project loads, its rows
 * are grey.
 */
export function ProjectOverview({ projectId, project, documents, reviewCounts, groups, actions, onOpenIssue, className }: ProjectOverviewProps) {
  const validation = project?.validation;
  const completed = validation?.status === 'completed';
  const running = validation?.status === 'running';
  // A new validation or a decision changes the list: it is read again from its first page.
  const key = completed ? JSON.stringify([validation.finished_at, reviewCounts]) : '';
  const [pageSize, setPageSize] = useState(RISKS_PAGE_SIZE);
  const { overviewRiskPaging: paging, setOverviewRiskPaging: setPaging } = useProject();
  const offset = paging.key === key ? paging.offset : 0;
  const risks = useApiResource(
    (signal) => listTopIssues(projectId, { limit: pageSize, offset }, signal),
    [projectId, key, pageSize, offset],
    { enabled: completed },
  );
  const nameOf = (id: string) => documents.find((doc) => doc.document_id === id)?.original_filename ?? id;

  const columns: DataTableColumn<ValidationIssue>[] = [
    {
      key: 'priority',
      header: t('Priority'),
      placeholderWidth: 'w-16',
      render: (issue) => <PriorityBadge tier={issue.severity} className="w-[4.5rem] justify-center" />,
    },
    {
      key: 'risk',
      header: t('Risk'),
      className: 'max-w-0 w-full',
      render: (issue) => (
        <>
          <span className="block truncate font-medium text-ink" title={issue.title}>
            {issue.title}
          </span>
          <span className="block truncate text-caption text-ink-secondary">{nameOf(issue.document_id)}</span>
        </>
      ),
    },
    {
      key: 'impact',
      header: t('Impact'),
      align: 'right',
      placeholderWidth: 'w-20',
      // On a phone the risk's title needs the width.
      className: 'whitespace-nowrap font-mono text-callout tabular-nums text-ink max-sm:hidden',
      headerClassName: 'max-sm:hidden',
      render: (issue) => {
        const impact = issue.estimated_financial_impact;
        if (!impact) return null;
        // By its size (a bill can state too much or too little), in cents. A comparison with
        // reference prices is never a loss: it says so.
        const size = parseDecimal(impact.amount);
        const amount = `${formatDecimal(size ? decimalToString(roundDecimal(absDecimal(size), 2)) : impact.amount)}${impact.currency ? ` ${impact.currency}` : ''}`;
        return impact.kind === 'reference_deviation' ? t('Comparison: {amount}', { amount }) : amount;
      },
    },
  ];

  const failed = Boolean(completed && risks.error && !risks.data);
  let status: string | null = null;
  if (failed) status = t('The issues could not be loaded');
  else if (risks.data && !risks.data.total) status = t('No issue is left to review.');
  else if (project && !completed && !running) status = t('Not validated yet');

  return (
    <TableCard
      title={t('Project overview')}
      actions={actions}
      summary={
        <div className="grid gap-x-8 gap-y-4 @lg:grid-cols-2">
          <OverviewFigures items={projectFigures({ project, documents, reviewCounts, groups })} />
          <RisksChart counts={project && hasValidationResult(project) ? findingsBySeverity(reviewCounts) : null} loading={!project} />
        </div>
      }
      columns={columns}
      rows={risks.data?.items ?? []}
      getRowKey={(issue) => issue.issue_id}
      caption={t('Risks')}
      onRowActivate={(issue) => onOpenIssue(issue.document_id, { run: issue.validation_run_id, issue: issue.issue_id, tab: 'risks' })}
      pageSize={pageSize}
      rowHeight={TWO_LINE_ROW_REM}
      fill
      onPageSizeChange={setPageSize}
      offset={offset}
      total={risks.data?.total ?? null}
      onOffsetChange={completed || running ? (next) => setPaging({ key, offset: next }) : undefined}
      itemLabel={risks.data?.total === 1 ? t('risk') : t('risks')}
      status={status}
      statusAction={
        failed && (
          <Button icon={RotateCw} onPress={risks.reload}>
            {t('Retry')}
          </Button>
        )
      }
      loading={!project || running || (completed && !risks.data && !failed)}
      loadingLabel={t('Loading the risks…')}
      className={cx('@container', className)}
    />
  );
}
