import { FileSpreadsheet } from 'lucide-react';
import { Button } from '../../components/Button.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { t } from '../../i18n/messages.ts';
import { downloadDatasetExcel } from '../../services/exportsService.ts';
import { formatBytes } from '../../utils/format.ts';

interface DownloadExcelButtonProps {
  datasetId: string;
  variant?: 'primary' | 'secondary' | 'ghost';
  size?: 'md' | 'lg';
  label?: string;
}

/**
 * Downloads the extracted tables of a dataset as an Excel workbook (no validation run needed).
 * The outcome is announced in a live region.
 */
export function DownloadExcelButton({
  datasetId,
  variant = 'secondary',
  size = 'lg',
  label,
}: DownloadExcelButtonProps) {
  const download = useAsyncAction((signal, id: string) => downloadDatasetExcel(id, { signal }));
  let status = '';
  if (download.pending) {
    status = t('Preparing the Excel file…');
  } else if (download.result) {
    status = t('Downloaded {file} ({size}).', { file: download.result.filename, size: formatBytes(download.result.size) });
  }
  return (
    <div className="flex flex-col gap-2">
      <div>
        <Button
          variant={variant}
          size={size}
          icon={FileSpreadsheet}
          loading={download.pending}
          onPress={() => download.execute(datasetId)}
        >
          {label ?? t('Download Excel')}
        </Button>
      </div>
      <p role="status" className="text-callout text-ink-secondary empty:hidden">
        {status}
      </p>
      {download.error && !download.pending && (
        <ErrorState error={download.error} title={t('The Excel file could not be downloaded')} compact />
      )}
    </div>
  );
}
