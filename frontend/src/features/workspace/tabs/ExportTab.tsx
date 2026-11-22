import { Section } from '../../../components/Section.tsx';
import { t } from '../../../i18n/messages.ts';
import { DownloadExcelButton } from '../../exports/DownloadExcelButton.tsx';
import { ExportPanel } from '../../exports/ExportPanel.tsx';
import type { ValidationRunSummary } from '../../../services/apiTypes.ts';

interface ExportTabProps {
  datasetId: string;
  runs: ValidationRunSummary[];
  runId?: string | null;
  onRunChange: (runId: string) => void;
}

/**
 * The downloads of the open file: the exports of the chosen validation (workbook, issues CSV,
 * tables ZIP, JSON) and the table itself as Excel (the newest revision, edits included).
 */
export function ExportTab({ datasetId, runs, runId = null, onRunChange }: ExportTabProps) {
  return (
    <div>
      {runId && (
        <Section title={t('Validation results')} padded>
          <ExportPanel runs={runs} runId={runId} onRunChange={onRunChange} />
        </Section>
      )}
      <Section title={t('Table')} padded>
        <div title={t('An Excel workbook of the newest revision, edits included: one sheet per table and a sheet on how the file was read.')}>
          <DownloadExcelButton datasetId={datasetId} label={t('Download table as Excel')} />
        </div>
      </Section>
    </div>
  );
}
