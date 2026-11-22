import { Download, Eye, FileDown, RotateCw } from 'lucide-react';
import { useMemo, useState } from 'react';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { Button, ButtonLink } from '../../components/Button.tsx';
import type { DataTableColumn } from '../../components/DataTable.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { IconButton } from '../../components/IconButton.tsx';
import { Select } from '../../components/Select.tsx';
import { TableCard, usePagedRows } from '../../components/TableCard.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { msg, t } from '../../i18n/messages.ts';
import { ApiError } from '../../services/apiClient.ts';
import { createReport, downloadReport, listReports, type ProjectReport } from '../../services/projectsService.ts';
import { formatDateTime } from '../../utils/format.ts';
import { useProject } from './ProjectContext.tsx';
import { hasValidationResult } from './projectOverview.ts';

const WHOLE_PROJECT = 'project';
const PAGE_SIZE = 10;

const FORMATS: { value: ProjectReport['format']; label: string }[] = [
  { value: 'pdf', label: msg('PDF report') },
  { value: 'xlsx', label: msg('Excel workbook') },
  { value: 'issues.csv', label: msg('Issues as CSV') },
  { value: 'bid-risk.pdf', label: msg('Bid risk report (PDF)') },
];
/** The bid risk report covers the whole project only. */
const WHOLE_PROJECT_ONLY: ProjectReport['format'] = 'bid-risk.pdf';
const formatLabel = (value: string) => t(FORMATS.find((option) => option.value === value)?.label ?? value);

/**
 * Reports of a project. On top the box that generates one from the project's last validation:
 * on the issues of the whole project or of one of its bills (the findings the Overview counts)
 * as a PDF report, an Excel workbook or a CSV file, or the bid risk report of the whole project
 * as a PDF (after a validation that stopped part-way, only that). Generating keeps the report
 * in the project and downloads it; the bid risk report also opens on screen. Under it the table
 * of the reports generated so far, newest first, each to download again; it fills the rest of the
 * window and shows as many rows as fit, so the page does not scroll. While the project loads,
 * the page is already laid out: the box's controls off, the table's rows grey.
 */
export function ReportsPage() {
  const { projectId, loaded, project, error, reload } = useProject();
  const [scope, setScope] = useState(WHOLE_PROJECT);
  const [format, setFormat] = useState<ProjectReport['format']>('pdf');
  const reports = useApiResource((signal) => listReports(projectId, signal), [projectId]);
  const generate = useAsyncAction(async (signal, documentId: string | null, kind: ProjectReport['format']) => {
    const report = await createReport(projectId, kind, documentId, signal);
    reports.reload();
    return downloadReport(projectId, report, { signal });
  });
  const download = useAsyncAction((signal, report: ProjectReport) => downloadReport(projectId, report, { signal }));
  const [pageSize, setPageSize] = useState(PAGE_SIZE);
  const page = usePagedRows(reports.data?.items ?? [], pageSize);
  useDocumentTitle(t('project.nav.reports'));
  usePageTitle({
    title: t('project.nav.reports'),
    back: { label: t('Back to all projects'), to: '/projects' },
  });

  const validation = project?.validation ?? null;
  const names = useMemo(() => new Map((loaded?.documents ?? []).map((doc) => [doc.document_id, doc.original_filename])), [loaded]);
  const bills = useMemo(() => {
    const runs = validation?.status === 'completed' ? (validation.runs ?? {}) : {};
    return (project?.files ?? [])
      .filter((file) => runs[file.document_id] && names.has(file.document_id))
      // Filtered to the documents in `names` just above.
      .map((file) => ({ value: file.document_id, label: names.get(file.document_id)! }));
  }, [project, names, validation]);

  if (error && !project) return <ErrorState error={error} onRetry={reload} />;
  const running = validation?.status === 'running';
  // While the project loads, the box is laid out with its controls off and the table is grey.
  const waiting = running || !project;
  // After a validation that stopped part-way only the bid risk report can be made, on the bills
  // it validated; the other types wait for a whole validation.
  const partial = validation?.status === 'failed' && project !== null && hasValidationResult(project);
  const formats = partial ? FORMATS.filter((option) => option.value === WHOLE_PROJECT_ONLY) : FORMATS;
  const kind = formats.some((option) => option.value === format) ? format : formats[0].value;
  const target = kind !== WHOLE_PROJECT_ONLY && bills.some((bill) => bill.value === scope) ? scope : WHOLE_PROJECT;
  const columns: DataTableColumn<ProjectReport>[] = [
    {
      key: 'name',
      header: t('Name'),
      className: 'max-w-0 w-full',
      render: (report) => (
        <span className="block truncate" title={report.filename}>
          {report.filename}
        </span>
      ),
    },
    {
      key: 'scope',
      header: t('Report on'),
      className: 'whitespace-nowrap',
      render: (report) => (report.document_id ? (names.get(report.document_id) ?? report.document_id) : t('Whole project')),
    },
    { key: 'format', header: t('Type'), className: 'whitespace-nowrap', render: (report) => formatLabel(report.format) },
    { key: 'created', header: t('Created'), className: 'whitespace-nowrap tabular-nums', render: (report) => formatDateTime(report.created_at) },
    {
      key: 'download',
      header: <span className="sr-only">{t('Download')}</span>,
      className: 'w-0 pr-2',
      render: (report) => (
        <IconButton
          icon={Download}
          label={t('Download {file}', { file: report.filename })}
          isDisabled={download.pending}
          onPress={() => download.execute(report)}
        />
      ),
    },
  ];

  // A server without the reports list (404) has no reports to show.
  const missing = reports.error instanceof ApiError && reports.error.status === 404;
  const failed = Boolean(reports.error && !reports.data && !missing);
  let status: string | null = null;
  if (failed) status = t('The reports could not be loaded');
  else if ((reports.data || missing) && !page.total) status = t('No reports yet');

  return (
    <div className="flex h-project-page min-h-fit flex-col gap-4">
      <section aria-labelledby="generate-report-heading" className="flex flex-col rounded-lg border border-hairline bg-surface">
        <div className="flex min-h-14 items-center border-b border-hairline px-4 py-2">
          <h2 id="generate-report-heading" className="text-headline text-ink">
            {t('Generate a report')}
          </h2>
        </div>
        <div className="flex flex-col gap-4 p-4">
          {bills.length || waiting || partial ? (
            <div className="flex flex-wrap items-end gap-4">
              <Select
                label={t('Report on')}
                value={target}
                options={[{ value: WHOLE_PROJECT, label: t('Whole project') }, ...bills]}
                onChange={(next) => {
                  generate.reset();
                  setScope(next);
                }}
                disabled={waiting || kind === WHOLE_PROJECT_ONLY}
                className="w-80 max-w-full"
              />
              <Select
                label={t('Type')}
                value={kind}
                options={formats.map((option) => ({ value: option.value, label: t(option.label) }))}
                onChange={(next) => {
                  generate.reset();
                  // The options are the FORMATS values.
                  setFormat(next as ProjectReport['format']);
                }}
                disabled={waiting}
                className="w-56 max-w-full"
              />
              <Button
                variant="primary"
                icon={FileDown}
                loading={generate.pending}
                isDisabled={waiting}
                onPress={() => generate.execute(target === WHOLE_PROJECT ? null : target, kind)}
              >
                {t('Generate report')}
              </Button>
              {kind === WHOLE_PROJECT_ONLY && !waiting && (
                <ButtonLink to={`/projects/${encodeURIComponent(projectId)}/report`} icon={Eye}>
                  {t('View on screen')}
                </ButtonLink>
              )}
            </div>
          ) : (
            <p className="text-body text-ink-secondary">{t('Validate the project first.')}</p>
          )}
          {generate.error && !generate.pending && <ErrorState error={generate.error} title={t('The report could not be generated')} compact />}
          {download.error && !download.pending && <ErrorState error={download.error} title={t('The report could not be downloaded')} compact />}
        </div>
      </section>
      <div className="flex-1">
        <TableCard
          title={t('Reports')}
          count={reports.data && project ? page.total : null}
          columns={columns}
          rows={page.rows}
          getRowKey={(report) => report.report_id}
          caption={t('Reports')}
          pageSize={pageSize}
          offset={page.offset}
          total={page.total}
          onOffsetChange={page.setOffset}
          fill
          onPageSizeChange={setPageSize}
          itemLabel={page.total === 1 ? t('report') : t('reports')}
          status={status}
          statusAction={
            failed && (
              <Button icon={RotateCw} onPress={reports.reload}>
                {t('Retry')}
              </Button>
            )
          }
          loading={(!reports.data && !reports.error) || !project}
          loadingLabel={t('Loading the reports…')}
        />
      </div>
    </div>
  );
}
