import { FileText, MoreHorizontal, Paperclip } from 'lucide-react';
import { useState } from 'react';
import { Badge } from '../../components/Badge.tsx';
import { Button } from '../../components/Button.tsx';
import { IconButton } from '../../components/IconButton.tsx';
import { Menu } from '../../components/Menu.tsx';
import { Spinner } from '../../components/Spinner.tsx';
import { TableCard, usePagedRows } from '../../components/TableCard.tsx';
import { t } from '../../i18n/messages.ts';
import { formatCount } from '../../utils/format.ts';
import { ProjectFileFilterBar } from './ProjectFileFilterBar.tsx';
import { filterFiles, needsAttention, NO_FILE_FILTERS, type FileFilters, type FileType } from './projectFileFilters.ts';
import { groupOf, roleOf } from './projectOverview.ts';
import type { ReactNode } from 'react';
import type { DataTableColumn } from '../../components/DataTable.tsx';
import type { BillReviewCounts, DocumentSummary, FileGroup, Project, ReviewCounts } from '../../services/apiTypes.ts';
import type { OpenFile } from './ProjectContext.tsx';

/** Rows per page before the table is laid out. */
const FILES_PAGE_SIZE = 6;

interface StateBadgeProps { doc: DocumentSummary; type: FileType }

function StateBadge({ doc, type }: StateBadgeProps) {
  if (type === 'reference') return <Badge>{t('projects.file.reference')}</Badge>;
  if (needsAttention(doc, type)) return <Badge tone="violation">{t('Needs attention')}</Badge>;
  if (doc.processing_status === 'stored') return <Badge>{t('Reading')}</Badge>;
  return <Badge tone="success">{t('Ready')}</Badge>;
}

/**
 * Whether the file is being validated: the project's validation runs and has no result for it
 * yet, or a run of its own (a re-check after a change) is queued or running.
 */
function isValidating(validation: Project['validation'] | undefined, doc: DocumentSummary): boolean {
  const pending = validation?.status === 'running' && !(doc.document_id in validation.runs) && !(doc.document_id in validation.skipped);
  return pending || doc.last_run?.status === 'queued' || doc.last_run?.status === 'running';
}

/** What is left to review in a bill: "39, 3 high", "All decided" or "Not validated" ("—" while it is validated). */
function reviewText(counts: BillReviewCounts | undefined, validated: boolean, validating: boolean) {
  if (!counts) return validated || validating ? '—' : t('Not validated');
  if (!counts.to_review) return t('All decided');
  return counts.high_priority
    ? t('{count}, {high} high', { count: formatCount(counts.to_review), high: formatCount(counts.high_priority) })
    : formatCount(counts.to_review);
}

/** The name of a file's type in the Type column. */
function typeName(type: FileType) {
  if (type === 'reference') return t('projects.file.reference');
  if (type === 'support') return t('Supporting document');
  return t('Bill');
}

interface ProjectFilesProps {
  /** null while the project loads: the table's header over grey rows. */
  project: Project | null;
  documents: DocumentSummary[];
  reviewCounts: ReviewCounts;
  onOpen: OpenFile;
  onRemove: (documentId: string) => void;
  /** Puts a file among the bills or the supporting documents. */
  onMove: (documentId: string, group: FileGroup) => void;
  /** Each file's group (`ProjectDetail.groups`); a file not in it is a bill. */
  groups?: Record<string, FileGroup>;
  disabled?: boolean;
  /** A button at the top right. */
  action?: ReactNode;
  footer?: ReactNode;
  filters?: FileFilters;
  onFiltersChange?: (filters: FileFilters) => void;
}

/**
 * Every file of the project in one table, the newest upload first, as many rows a page as fit its
 * height (six before it is laid out): name, type (bill, reference or supporting document), state
 * and the findings still to review in the project's validation. Above it a search by name and
 * the type and state filters. A bill's row opens it in the Workspace (at its open risks when there
 * are some), a supporting document's row opens the document itself, without bill errors. The
 * Actions menu opens a bill's Properties, moves a file between the bills and the supporting
 * documents, or removes it from the project (the uploaded file itself is kept). `footer` goes
 * under the pages.
 */
export function ProjectFiles({
  project,
  documents,
  reviewCounts,
  onOpen,
  onRemove,
  onMove,
  groups,
  disabled,
  action = null,
  footer = null,
  filters: savedFilters,
  onFiltersChange,
}: ProjectFilesProps) {
  const loading = project === null;
  const validation = project?.validation;
  const typeOf = (doc: DocumentSummary): FileType => {
    if (groupOf(groups, doc) === 'support') return 'support';
    return project && roleOf(project, doc) === 'reference' ? 'reference' : 'bill';
  };
  const [localFilters, setLocalFilters] = useState<FileFilters>(NO_FILE_FILTERS);
  const filters = savedFilters ?? localFilters;
  const setFilters = onFiltersChange ?? setLocalFilters;
  const [pageSize, setPageSize] = useState(FILES_PAGE_SIZE);
  const rows = filterFiles(documents, filters, typeOf, reviewCounts);
  const page = usePagedRows(rows, pageSize);
  const changeFilters = (next: FileFilters) => {
    setFilters(next);
    page.setOffset(0);
  };

  const open = (doc: DocumentSummary) => {
    if (typeOf(doc) === 'support') {
      onOpen(doc.document_id);
      return;
    }
    const runId = validation?.runs?.[doc.document_id];
    onOpen(doc.document_id, runId && reviewCounts[doc.document_id]?.to_review ? { run: runId, tab: 'risks', status: 'open' } : {});
  };

  const columns: DataTableColumn<DocumentSummary>[] = [
    {
      key: 'name',
      placeholderWidth: 'w-48',
      header: t('Name'),
      render: (doc) => {
        const Icon = typeOf(doc) === 'support' ? Paperclip : FileText;
        return (
          <span className="flex min-w-0 items-start gap-2.5">
            {isValidating(validation, doc) ? (
              <>
                <Spinner size="sm" className="mt-0.5 text-ink-secondary" />
                <span className="sr-only">{t('Validating…')}</span>
              </>
            ) : (
              <Icon aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-ink-tertiary" />
            )}
            <span className="min-w-0">
              <span className="block break-all font-medium text-ink">{doc.original_filename}</span>
              {typeOf(doc) === 'bill' && doc.failure_reason && <span className="block text-caption text-danger">{doc.failure_reason}</span>}
            </span>
          </span>
        );
      },
    },
    {
      key: 'type',
      placeholderWidth: 'w-8',
      header: t('Type'),
      className: 'whitespace-nowrap text-ink-secondary max-lg:hidden',
      headerClassName: 'max-lg:hidden',
      render: (doc) => typeName(typeOf(doc)),
    },
    {
      key: 'state',
      placeholderWidth: 'w-14',
      header: t('State'),
      className: 'whitespace-nowrap max-sm:hidden',
      headerClassName: 'max-sm:hidden',
      render: (doc) => (typeOf(doc) === 'support' ? <span className="text-ink-tertiary">—</span> : <StateBadge doc={doc} type={typeOf(doc)} />),
    },
    {
      key: 'review',
      placeholderWidth: 'w-20',
      header: t('To review'),
      className: 'whitespace-nowrap tabular-nums',
      render: (doc) => {
        const type = typeOf(doc);
        if (type === 'support') return <span className="text-ink-tertiary">—</span>;
        if (type === 'reference') return <span className="text-ink-tertiary">{t('Compared')}</span>;
        const counts = reviewCounts[doc.document_id];
        return (
          <span className={counts?.high_priority ? 'font-medium text-danger' : counts?.to_review ? 'text-ink' : 'text-ink-secondary'}>
            {reviewText(counts, Boolean(validation?.runs?.[doc.document_id]), isValidating(validation, doc))}
          </span>
        );
      },
    },
    {
      key: 'actions',
      placeholderWidth: 'w-6',
      header: <span className="sr-only">{t('Actions')}</span>,
      align: 'right',
      className: 'w-14 py-0',
      render: (doc) => (
        <Menu
          label={t('Actions for {file}', { file: doc.original_filename })}
          trigger={<IconButton icon={MoreHorizontal} label={t('Actions for {file}', { file: doc.original_filename })} />}
          items={
            typeOf(doc) === 'support'
              ? [
                  { id: 'move', label: t('Move to bills'), disabled, onAction: () => onMove(doc.document_id, 'bill') },
                  { id: 'remove', label: t('Remove from project'), danger: true, disabled, onAction: () => onRemove(doc.document_id) },
                ]
              : [
                  { id: 'properties', label: t('Open Properties'), onAction: () => onOpen(doc.document_id, { tab: 'properties' }) },
                  { id: 'move', label: t('Move to supporting documents'), disabled, onAction: () => onMove(doc.document_id, 'support') },
                  { id: 'remove', label: t('Remove from project'), danger: true, disabled, onAction: () => onRemove(doc.document_id) },
                ]
          }
        />
      ),
    },
  ];

  const noMatch = !loading && rows.length === 0 && documents.length > 0;
  return (
    <TableCard
      title={t('Files')}
      count={loading ? null : rows.length}
      actions={action}
      summary={<ProjectFileFilterBar filters={filters} onChange={changeFilters} />}
      columns={columns}
      rows={page.rows}
      getRowKey={(doc) => doc.document_id}
      caption={t('Files')}
      onRowActivate={open}
      pageSize={pageSize}
      fill
      onPageSizeChange={setPageSize}
      offset={page.offset}
      total={page.total}
      onOffsetChange={page.setOffset}
      itemLabel={page.total === 1 ? t('file') : t('files')}
      loading={loading}
      loadingLabel={t('Loading the files…')}
      status={
        loading || rows.length
          ? null
          : noMatch
            ? t('No files match the search and filters')
            : t('No files yet. Add the bills of this project.')
      }
      statusAction={noMatch && <Button onPress={() => changeFilters(NO_FILE_FILTERS)}>{t('Clear filters')}</Button>}
      footer={footer}
      className="max-xl:h-[32rem]"
    />
  );
}
