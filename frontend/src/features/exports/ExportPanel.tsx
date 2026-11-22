import { Download } from 'lucide-react';
import { useState } from 'react';
import { Button } from '../../components/Button.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useAsyncAction } from '../../hooks/useAsyncAction.ts';
import { msg, t } from '../../i18n/messages.ts';
import { downloadRunExport, type RunExportKind } from '../../services/exportsService.ts';
import { formatBytes } from '../../utils/format.ts';
import { RunSelect } from '../validation/RunSelect.tsx';
import type { ValidationRunSummary } from '../../services/apiTypes.ts';

/** The exports of a run, the one reviewers need most first (it is the primary action). */
const EXPORTS: { kind: RunExportKind; label: string; description: string }[] = [
  {
    kind: 'xlsx',
    label: msg('Download workbook (Excel)'),
    description: msg(
      'One sheet per extracted table with its source page or row, a sheet with every issue, and the extraction report. Numbers stay numbers.',
    ),
  },
  {
    kind: 'csv',
    label: msg('Download issues (CSV)'),
    description: msg(
      'One row per issue: location, observed and expected values, explanation and review status. Opens in any spreadsheet application.',
    ),
  },
  {
    kind: 'zip',
    label: msg('Download tables (ZIP)'),
    description: msg('The issues CSV, one CSV per extracted table with its source row numbers, and a manifest.'),
  },
  {
    kind: 'json',
    label: msg('Download JSON export'),
    description: msg(
      'The canonical dataset revision, the validation run with its plan and detector reports, the detector specifications and every issue with its current review status.',
    ),
  },
  {
    kind: 'questions',
    label: msg('Download questions document (Markdown)'),
    description: msg(
      'A ready-to-send questions list for findings marked Needs more information, with location and context per finding.',
    ),
  },
];

interface ExportPanelProps {
  runs: ValidationRunSummary[];
  runId: string;
  onRunChange: (runId: string) => void;
}

/**
 * Chooses a run and downloads one of its exports. The status line is a live region, so the
 * outcome is announced.
 */
export function ExportPanel({ runs, runId, onRunChange }: ExportPanelProps) {
  const [kind, setKind] = useState<RunExportKind | null>(null);
  const download = useAsyncAction((signal, id: string, exportKind: RunExportKind) => downloadRunExport(id, exportKind, { signal }));

  let status = '';
  if (download.pending) {
    status = t('Preparing the export…');
  } else if (download.result) {
    status = t('Export downloaded: {file} ({size}).', { file: download.result.filename, size: formatBytes(download.result.size) });
  }

  return (
    <div className="space-y-3">
      <RunSelect
        runs={runs}
        value={runId}
        onChange={(nextRunId) => {
          download.reset();
          onRunChange(nextRunId);
        }}
      />
      <ul className="flex flex-wrap gap-2">
        {EXPORTS.map((item, index) => (
          <li key={item.kind} title={t(item.description)}>
            <Button
              variant={index === 0 ? 'primary' : 'secondary'}
              icon={Download}
              loading={download.pending && kind === item.kind}
              isDisabled={download.pending && kind !== item.kind}
              onPress={() => {
                setKind(item.kind);
                download.execute(runId, item.kind);
              }}
            >
              {t(item.label)}
            </Button>
          </li>
        ))}
      </ul>
      <p role="status" className="text-callout text-ink">
        {status}
      </p>
      {download.error && !download.pending && (
        <ErrorState error={download.error} title={t('The export could not be downloaded')} compact />
      )}
    </div>
  );
}
