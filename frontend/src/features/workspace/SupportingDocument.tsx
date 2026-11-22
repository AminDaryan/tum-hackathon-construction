import { Download, FileText } from 'lucide-react';
import { Button } from '../../components/Button.tsx';
import { EmptyState } from '../../components/EmptyState.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { t } from '../../i18n/messages.ts';
import type { DocumentSummary } from '../../services/apiTypes.ts';
import { getDocumentOriginal } from '../../services/documentsService.ts';
import { saveBlob } from '../../utils/download.ts';
import { PdfDocument } from './PdfDocument.tsx';

interface SupportingDocumentProps {
  document: Pick<DocumentSummary, 'document_id' | 'original_filename' | 'format'>;
}

/**
 * A supporting document of a project (a drawing, a soil report, a spec) shown as itself, never
 * as a bill: a PDF page by page with its text selectable and a search, any other file as a card
 * to download the original. It shows no bill errors, because it is not read as a bill.
 */
export function SupportingDocument({ document }: SupportingDocumentProps) {
  const download = useAsyncAction(async (signal) =>
    saveBlob(await getDocumentOriginal(document.document_id, { signal }), document.original_filename),
  );
  const downloadButton = (
    <Button icon={Download} loading={download.pending} onPress={() => download.execute()}>
      {t('Download the original')}
    </Button>
  );
  return (
    <section aria-label={t('Supporting document')} className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-lg border border-hairline bg-surface">
      <div className="flex min-h-12 flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-hairline py-2 pl-4 pr-2">
        <p className="text-callout text-ink-secondary">{t('Supporting document, shown as it is and not checked as a bill.')}</p>
        {document.format === 'pdf' && downloadButton}
      </div>
      {download.error && <ErrorState error={download.error} title={t('The file could not be downloaded')} compact />}
      {document.format === 'pdf' ? (
        <PdfDocument documentId={document.document_id} file={document.original_filename} />
      ) : (
        <EmptyState
          icon={FileText}
          title={document.original_filename}
          description={t('This file has no preview here. Download the original to read it.')}
          action={downloadButton}
        />
      )}
    </section>
  );
}
