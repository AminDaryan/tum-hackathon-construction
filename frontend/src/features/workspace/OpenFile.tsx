import { FileWarning } from 'lucide-react';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { Button } from '../../components/Button.tsx';
import { EmptyState } from '../../components/EmptyState.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { t } from '../../i18n/messages.ts';
import { useWorkspace } from '../../stores/useWorkspace.ts';
import { DocumentPlaceholder, DocumentView } from './DocumentView.tsx';
import { SupportingDocument } from './SupportingDocument.tsx';

interface OpenFileProps {
  documentId: string;
  /** The file is a supporting document of its project: shown as itself, not as a bill. */
  supporting?: boolean;
  /** what the file belongs to (its project), named before the file's name in the top bar */
  parent: { label: string | null; to: string };
  /** leaves the file ("Choose another file" when it could not be read) */
  onClose: () => void;
}

/**
 * One open file in the Workspace: everything about it on one page, the sheet, its tabs and the
 * issue window (DocumentView), once `GET /documents/{documentId}` has loaded. The file's name is
 * the page's title, after `parent` like a breadcrumb. A supporting document (`supporting`) shows
 * the document itself instead, without bill errors.
 */
export function OpenFile({ documentId, supporting = false, parent, onClose }: OpenFileProps) {
  const { activeDocumentId, activeDocument, error, reload } = useWorkspace();
  const current = activeDocumentId === documentId ? activeDocument : null;
  useDocumentTitle(current?.document?.original_filename ?? t('Loading the file…'));
  // While the file loads, the top bar shows its name as a grey shape after the project's.
  usePageTitle({ title: current?.document?.original_filename ?? null, pending: !current, parent });

  if (error && activeDocumentId === documentId) {
    return <ErrorState error={error} title={t('The file could not be loaded')} onRetry={reload} />;
  }
  if (!current) {
    return <DocumentPlaceholder label={t('Loading the file…')} />;
  }
  const { document, dataset } = current;
  if (supporting) return <SupportingDocument document={document} />;
  if (!dataset) {
    return (
      <EmptyState
        icon={FileWarning}
        title={t('This file could not be read')}
        description={document.failure_reason ?? t('Reading the file produced no table.')}
        action={
          <Button variant="primary" onPress={onClose}>
            {t('Choose another file')}
          </Button>
        }
      />
    );
  }
  return <DocumentView key={dataset.dataset_id} document={document} dataset={dataset} onReload={reload} />;
}
