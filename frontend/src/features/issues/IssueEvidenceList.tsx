import { Badge } from '../../components/Badge.tsx';
import { t } from '../../i18n/messages.ts';
import { EVIDENCE_KIND_LABELS, humanize, labelFor } from '../../utils/vocabulary.ts';
import { CalculationBlock } from './CalculationBlock.tsx';
import { CellReferenceList } from './CellReferenceList.tsx';
import type { EvidenceItem } from '../../services/apiTypes.ts';

interface EvidenceDataProps {
  data?: Record<string, unknown>;
}

function EvidenceData({ data }: EvidenceDataProps) {
  const entries = Object.entries(data ?? {}).filter(([, value]) => value !== null && value !== undefined);
  if (!entries.length) {
    return null;
  }
  return (
    <dl className="mt-2 grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-0.5 font-mono text-caption">
      {entries.map(([key, value]) => (
        <div key={key} className="contents">
          <dt className="text-ink-secondary">{humanize(key)}</dt>
          <dd className="break-all text-ink">{String(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

interface IssueEvidenceListProps {
  evidence?: EvidenceItem[];
}

/**
 * The structured evidence of an issue: what was computed, compared or observed, with the cells
 * involved. Calculations are rendered from their typed structure; other items show their data.
 */
export function IssueEvidenceList({ evidence }: IssueEvidenceListProps) {
  if (!evidence?.length) {
    return <p className="text-callout text-ink-secondary">{t('The detector attached no structured evidence.')}</p>;
  }
  return (
    <ol className="space-y-4">
      {evidence.map((item, index) => (
        <li key={`${item.kind}-${index}`}>
          <div className="flex flex-wrap items-center gap-2">
            <Badge>{t(labelFor(EVIDENCE_KIND_LABELS, item.kind))}</Badge>
            <p className="text-callout font-medium text-ink">{item.label}</p>
          </div>
          <p className="mt-1 whitespace-pre-line text-callout text-ink-secondary">{item.detail}</p>
          {item.calculation ? (
            <div className="mt-2">
              <CalculationBlock calculation={item.calculation} />
            </div>
          ) : (
            <EvidenceData data={item.data} />
          )}
          {item.cells?.length > 0 && (
            <div className="mt-2 flex flex-wrap items-baseline gap-x-2 text-caption text-ink-tertiary">
              <span>{t('Cells')}</span>
              <CellReferenceList cells={item.cells} />
            </div>
          )}
        </li>
      ))}
    </ol>
  );
}
