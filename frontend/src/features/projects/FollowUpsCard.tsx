import { RotateCw } from 'lucide-react';
import { useState } from 'react';
import { Badge } from '../../components/Badge.tsx';
import { Button } from '../../components/Button.tsx';
import type { DataTableColumn } from '../../components/DataTable.tsx';
import { TableCard, TWO_LINE_ROW_REM } from '../../components/TableCard.tsx';
import { t } from '../../i18n/messages.ts';
import type { DocumentSummary } from '../../services/apiTypes.ts';
import type { ClarificationItem } from '../../services/clarificationsService.ts';
import { kindOf, statusText } from '../clarifications/clarificationModel.ts';
import { clarificationKey, useClarificationPage } from '../clarifications/useClarificationPage.ts';
import { useProject, type OpenFile } from './ProjectContext.tsx';

/** Opens a clarification's risk in the Workspace, on the finding its email was about when it has one. */
export function openClarificationRisk(openFile: OpenFile, item: ClarificationItem) {
  openFile(item.document_id, item.issue_id ? { issue: item.issue_id, tab: 'risks' } : { risk: item.risk_id, tab: 'risks' });
}

interface FollowUpsCardProps {
  projectId: string;
  /** The project's files, for the bills' names; null while the project loads. */
  documents: DocumentSummary[] | null;
  onOpen: OpenFile;
  className?: string;
}

/** The most rows a page asks the server for; fewer when fewer fit. */
const PAGE_SIZE = 10;

/**
 * The project's follow-ups on its page, as a table as tall as its row: each clarification's type,
 * item (over its bill) and status, the most severe first, one page at a time from the server; a
 * row opens its risk in the Workspace.
 */
export function FollowUpsCard({ projectId, documents, onOpen, className }: FollowUpsCardProps) {
  const { overviewFollowUpOffset: offset, setOverviewFollowUpOffset: setOffset } = useProject();
  const [fittingRows, setFittingRows] = useState(6);
  const pageSize = Math.min(fittingRows, PAGE_SIZE);
  const resource = useClarificationPage(projectId, { offset, limit: pageSize });
  const page = resource.data;
  const billNames = new Map((documents ?? []).map((doc) => [doc.document_id, doc.original_filename]));
  const columns: DataTableColumn<ClarificationItem>[] = [
    {
      key: 'kind',
      header: t('Type'),
      render: (item) => <Badge tone={kindOf(item.kind).tone}>{t(kindOf(item.kind).label)}</Badge>,
    },
    {
      key: 'title',
      header: t('Item'),
      className: 'max-w-0 w-full',
      render: (item) => (
        <>
          <span className="block truncate" title={item.title}>
            {item.title}
          </span>
          <span className="block truncate text-caption text-ink-secondary">
            {billNames.get(item.document_id) ?? t('A file no longer in the project')}
          </span>
        </>
      ),
    },
    { key: 'status', header: t('Status'), className: 'whitespace-nowrap text-ink-secondary', render: statusText },
  ];
  const failed = Boolean(resource.error && !page);
  const loading = (!page && !failed) || documents === null;

  return (
    <TableCard
      title={t('project.nav.followUps')}
      count={page ? page.total : null}
      columns={columns}
      rows={page?.items ?? []}
      getRowKey={clarificationKey}
      caption={t('project.nav.followUps')}
      onRowActivate={(item) => openClarificationRisk(onOpen, item)}
      pageSize={pageSize}
      rowHeight={TWO_LINE_ROW_REM}
      fill
      onPageSizeChange={setFittingRows}
      offset={offset}
      total={page?.total ?? 0}
      onOffsetChange={setOffset}
      itemLabel={page?.total === 1 ? t('clarification') : t('clarifications')}
      status={failed ? t('The clarifications could not be loaded') : !loading && page?.total === 0 ? t('No clarifications yet') : null}
      statusAction={
        failed && (
          <Button icon={RotateCw} onPress={resource.reload}>
            {t('Retry')}
          </Button>
        )
      }
      loading={loading}
      loadingLabel={t('Loading the clarifications…')}
      className={className}
    />
  );
}
