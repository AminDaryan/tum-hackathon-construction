import { CircleCheck, CircleDot, CircleHelp, CircleX, Crosshair, type LucideIcon } from 'lucide-react';
import { Disclosure } from '../../../components/Disclosure.tsx';
import { useId, useState } from 'react';
import { Badge } from '../../../components/Badge.tsx';
import { Button } from '../../../components/Button.tsx';
import { ErrorState } from '../../../components/ErrorState.tsx';
import { EvidenceBadge } from '../../../components/EvidenceBadge.tsx';
import { FindingCategory } from '../../../components/FindingCategory.tsx';
import { KeyValueList } from '../../../components/KeyValueList.tsx';
import { SeverityIndicator } from '../../../components/SeverityIndicator.tsx';
import { t } from '../../../i18n/messages.ts';
import { cx } from '../../../utils/classNames.ts';
import { formatCellReference } from '../../../utils/sourceLocation.ts';
import { AuditHistory } from '../../issues/AuditHistory.tsx';
import { FinancialImpact } from '../../issues/FinancialImpact.tsx';
import { InspectorSection } from '../../issues/InspectorSection.tsx';
import { IssueEvidenceList } from '../../issues/IssueEvidenceList.tsx';
import { IssueSignals } from '../../issues/IssueSignals.tsx';
import { isModelSuggested } from '../../risks/riskModel.ts';
import { methodLabel } from '../methods.ts';
import { reviewStateLabel } from '../reviewLabels.ts';
import type { SheetTarget } from '../issueTarget.ts';
import type { AuditEvent, CellRef, DetectorDescriptor, ValidationIssue } from '../../../services/apiTypes.ts';

const STATE_ICONS: Readonly<Record<string, LucideIcon>> = Object.freeze({
  pending_review: CircleDot,
  confirmed_error: CircleCheck,
  false_positive: CircleX,
  dismissed: CircleX,
  needs_more_information: CircleHelp,
  corrected: CircleCheck,
});

const LONG_TEXT_CHARACTERS = 240;
const LONG_TEXT_LINES = 4;

interface TableColumns {
  table_id?: string;
  columns?: {
      column_id: string;
      original_header?: string | null;
      mapped_semantic_field?: string | null;
    }[];
}

interface RowCells {
  row_id: string;
  source_row_number?: number;
  cells?: Record<string, { raw_value?: string | null }>;
}

function columnByField(table: TableColumns | null | undefined, field: string) {
  return table?.columns?.find((column) => column.mapped_semantic_field === field) ?? null;
}

function cellText(row: RowCells | null | undefined, column: { column_id: string } | null) {
  const value = column ? row?.cells?.[column.column_id]?.raw_value : null;
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

interface LongTextProps {
  text: string;
}

/** The long text, four lines at first. */
function LongText({ text }: LongTextProps) {
  const [open, setOpen] = useState(false);
  const long = text.length > LONG_TEXT_CHARACTERS || text.split('\n').length > LONG_TEXT_LINES;
  return (
    <>
      <p className={cx('whitespace-pre-line', long && !open && 'line-clamp-4')}>{text}</p>
      {long && (
        <Button variant="ghost" className="-ml-3" aria-expanded={open} onPress={() => setOpen(!open)}>
          {open ? t('Show less') : t('Show all')}
        </Button>
      )}
    </>
  );
}

interface CellButtonsProps {
  cells: CellRef[];
  table?: TableColumns;
  onRevealCell: (target: SheetTarget) => void;
}

/** Buttons that take the sheet to each cell, named by column header and source reference. */
function CellButtons({ cells, table, onRevealCell }: CellButtonsProps) {
  return (
    <ul className="flex flex-wrap gap-2">
      {cells.map((cell) => {
        const header = table?.columns?.find((column) => column.column_id === cell.column_id)?.original_header;
        const reference = formatCellReference(cell.source);
        return (
          <li key={`${cell.table_id}:${cell.row_id}:${cell.column_id}`}>
            <Button
              icon={Crosshair}
              onPress={() => onRevealCell({ tableId: cell.table_id, rowId: cell.row_id, columnId: cell.column_id })}
            >
              {header || (!reference && cell.column_id)}
              {header && reference && ' '}
              {reference && <span className="font-mono text-caption text-ink-secondary">{reference}</span>}
            </Button>
          </li>
        );
      })}
    </ul>
  );
}

interface WhereProps {
  issue: ValidationIssue;
  row?: RowCells | null;
  table?: TableColumns;
  onRevealCell: (target: SheetTarget) => void;
}

function Where({ issue, row, table, onRevealCell }: WhereProps) {
  if (!issue.row_id) {
    return <p className="text-body text-ink">{t('This finding is about the whole table.')}</p>;
  }
  const ownRow = row?.row_id === issue.row_id ? row : null;
  const oz = cellText(ownRow, columnByField(table, 'item_code'));
  const shortText = cellText(ownRow, columnByField(table, 'description'));
  const longText = cellText(ownRow, columnByField(table, 'long_description'));
  const affected = issue.affected_cells ?? [];
  const inputs = (issue.input_cells ?? []).filter(
    (cell) => !affected.some((other) => other.row_id === cell.row_id && other.column_id === cell.column_id),
  );
  const rowNumber = ownRow?.source_row_number ?? affected.find((cell) => cell.source?.row_number)?.source?.row_number;
  return (
    <KeyValueList
      layout="inline"
      items={[
        (oz || shortText) && {
          label: t('Position'),
          value: (
            <>
              {oz && <span className="sheet-figures font-medium">{oz}</span>}
              {oz && shortText && ' '}
              {shortText}
            </>
          ),
        },
        longText && { label: t('Long text'), value: <LongText text={longText} /> },
        rowNumber != null && { label: t('Row'), value: <span className="sheet-figures">{rowNumber}</span> },
        {
          label: affected.length === 1 ? t('Cell') : t('Cells'),
          value: affected.length ? (
            <CellButtons cells={affected} table={table} onRevealCell={onRevealCell} />
          ) : (
            <Button
              icon={Crosshair}
              // A finding on a row names its table and row.
              onPress={() => onRevealCell({ tableId: issue.table_id!, rowId: issue.row_id!, columnId: null })}
            >
              {t('Show the row')}
            </Button>
          ),
        },
        inputs.length > 0 && {
          label: t('Computed from'),
          value: <CellButtons cells={inputs} table={table} onRevealCell={onRevealCell} />,
        },
      ]}
    />
  );
}

interface HistoryProps {
  events?: AuditEvent[];
  loading: boolean;
  error?: Error | null;
  onRetry: () => void;
}

function History({ events, loading, error, onRetry }: HistoryProps) {
  let content;
  if (error) {
    content = <ErrorState error={error} title={t('The history could not be loaded')} onRetry={onRetry} compact />;
  } else if (loading && !events) {
    content = <p className="text-callout text-ink-secondary">{t('Loading the history…')}</p>;
  } else if (!events?.length) {
    return null;
  } else {
    content = <AuditHistory events={events} />;
  }
  return (
    <Disclosure title={t('History')} className="border-t border-hairline pt-2">
      <div className="pb-2">{content}</div>
    </Disclosure>
  );
}

interface IssueDetailsProps {
  issue: ValidationIssue;
  history?: AuditEvent[];
  historyLoading?: boolean;
  historyError?: Error | null;
  onRetryHistory: () => void;
  row?: RowCells | null;
  table?: TableColumns;
  catalogue?: ReadonlyMap<string, DetectorDescriptor>;
  onRevealCell: (target: SheetTarget) => void;
  titleId?: string;
}

/**
 * The specifications of one finding in the issue window: what was found, where (with buttons
 * that take the sheet to each cell), the evidence, the money at stake, the recommendation, the
 * signals and, closed, the history.
 */
export function IssueDetails({
  issue,
  history,
  historyLoading = false,
  historyError = null,
  onRetryHistory,
  row = null,
  table,
  catalogue,
  onRevealCell,
  titleId,
}: IssueDetailsProps) {
  const fallbackTitleId = useId();
  const spec = catalogue?.get(issue.detector_id)?.spec;
  const method = methodLabel(issue.detector_id, spec?.category);
  const StateIcon = STATE_ICONS[issue.review_status] ?? CircleDot;
  const hasObserved = issue.observed_value !== null && issue.observed_value !== undefined;
  const hasExpected = issue.expected_value !== null && issue.expected_value !== undefined;
  const hasSignals = typeof issue.extraction_confidence === 'number' || Boolean(issue.anomaly_score);
  return (
    <div className="space-y-4">
      <header className="space-y-2">
        <h2 id={titleId ?? fallbackTitleId} className="text-headline text-ink">
          {issue.title}
        </h2>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <SeverityIndicator severity={issue.severity} />
          <FindingCategory category={issue.finding_category} className="text-callout" />
          <EvidenceBadge evidenceClass={issue.effective_evidence_class ?? issue.evidence_class} />
          <Badge title={spec?.description}>{method}</Badge>
          <Badge icon={StateIcon}>{reviewStateLabel(issue.review_status)}</Badge>
          {isModelSuggested(issue) && <Badge>Model-suggested match</Badge>}
        </div>
        <p className="text-caption text-ink-secondary">{t('Check: {name}', { name: spec?.name ?? issue.detector_id })}</p>
        {isModelSuggested(issue) && (
          <p className="text-callout text-ink-secondary">
            {t('The local model suggested which material this position is. Code checked its quotes, the scope (supply only), the unit rule and the published value, not whether the match is right. Reject the finding if the material is wrong.')}
          </p>
        )}
      </header>
      <InspectorSection title={t('What was found')}>
        <p className="whitespace-pre-line text-body text-ink">{issue.explanation}</p>
        {(hasObserved || hasExpected) && (
          <div className="mt-3">
            <KeyValueList
              layout="inline"
              items={[
                hasObserved && { label: t('Observed'), value: issue.observed_value, mono: true },
                hasExpected && { label: t('Expected'), value: issue.expected_value, mono: true },
              ]}
            />
          </div>
        )}
      </InspectorSection>
      <InspectorSection title={t('Where')}>
        <Where issue={issue} row={row} table={table} onRevealCell={onRevealCell} />
      </InspectorSection>
      {issue.evidence?.length > 0 && (
        <InspectorSection title={t('Evidence')}>
          <IssueEvidenceList evidence={issue.evidence} />
        </InspectorSection>
      )}
      {issue.estimated_financial_impact && (
        <InspectorSection title={t('Money at stake')}>
          <FinancialImpact impact={issue.estimated_financial_impact} />
        </InspectorSection>
      )}
      {issue.suggested_action && (
        <InspectorSection title={t('Recommendation')}>
          <p className="whitespace-pre-line text-body text-ink">{issue.suggested_action}</p>
        </InspectorSection>
      )}
      {hasSignals && (
        <InspectorSection title={t('Signals')}>
          <IssueSignals issue={issue} />
        </InspectorSection>
      )}
      <History events={history} loading={historyLoading} error={historyError} onRetry={onRetryHistory} />
    </div>
  );
}
