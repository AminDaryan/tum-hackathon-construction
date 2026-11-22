import { Crosshair } from 'lucide-react';
import { useMemo, useState } from 'react';
import { Button } from '../../../components/Button.tsx';
import { Disclosure } from '../../../components/Disclosure.tsx';
import { t, tRich } from '../../../i18n/messages.ts';
import { formatDecimal } from '../../../utils/format.ts';
import { findingsOnRow, isPriced, percentBetween, priceComparisons, priceFacts } from '../../risks/pricing.ts';
import { moneyView, riskTouchesRow } from '../../risks/riskModel.ts';
import { PriceRange } from './PriceRange.tsx';
import { PriceSimulator } from './PriceSimulator.tsx';
import { MoneyText } from './RiskBits.tsx';
import type { ReactNode } from 'react';
import type {
  CorrectionsResult,
  IssueCorrectionResult,
  Risk,
  Row,
  TableSummary,
  ValidationIssue,
} from '../../../services/apiTypes.ts';
import type { IssuesById } from '../../risks/riskModel.ts';
import type { SheetTarget } from '../issueTarget.ts';

function money(value: string | null | undefined, currency: string | null | undefined) {
  return value == null ? t('Not given') : `${formatDecimal(value)}${currency ? ` ${currency}` : ''}`;
}

interface HeadingProps {
  children?: ReactNode;
}

function Heading({ children }: HeadingProps) {
  return <h4 className="text-callout font-semibold text-ink">{children}</h4>;
}

interface PriceSectionProps {
  risks: Risk[];
  currency?: string | null;
  issues: ValidationIssue[];
  issuesById: IssuesById;
  row?: Row | null;
  table?: TableSummary | null;
  open?: boolean;
  onShowInSheet: (target: SheetTarget) => void;
  datasetId: string;
  revision: number;
  onRevised: (result: CorrectionsResult) => void;
  onCorrected: (result: IssueCorrectionResult) => void;
}

/**
 * The price of a risk's position inside the risk detail: quantity, unit price and line total;
 * the unit price against the comparable positions the price checks found; identical positions;
 * the money of the risks on this row; and a simulator that saves a new unit price as the next
 * revision. Every comparison comes from a finding of the run; no market benchmark is invented.
 * Open for a risk about a price, behind "Price of this position" for any other priced row.
 */
export function PriceSection({
  risks,
  currency,
  issues,
  issuesById,
  row,
  table,
  open,
  onShowInSheet,
  datasetId,
  revision,
  onRevised,
  onCorrected,
}: PriceSectionProps) {
  const [suggestion, setSuggestion] = useState<{ price: string; nonce: number } | null>(null);
  const [typedPrice, setTypedPrice] = useState<string | null>(null);
  const facts = useMemo(() => priceFacts(row, table), [row, table]);
  const rowFindings = useMemo(() => (facts ? findingsOnRow(issues, facts.rowId) : []), [issues, facts]);
  const comparisons = useMemo(() => priceComparisons(rowFindings), [rowFindings]);
  const rowRisks = useMemo(
    () => (facts ? risks.filter((risk) => riskTouchesRow(risk, facts.rowId, issuesById)) : []),
    [risks, facts, issuesById],
  );
  const approvedFinding = useMemo(
    () =>
      facts
        ? (rowFindings.find(
            (issue) =>
              issue.review_status === 'confirmed_error' &&
              issue.dataset_revision === revision &&
              (issue.affected_cells ?? []).some((cell) => cell.row_id === facts.rowId && cell.column_id === facts.columns.unit_price),
          ) ?? null)
        : null,
    [facts, rowFindings, revision],
  );
  if (!facts || !isPriced(facts)) return null;

  const peer = comparisons.peer;
  const identical = comparisons.identical;
  const peerChange = peer ? percentBetween(peer.median, facts.unitPrice) : null;
  const withMoney = rowRisks.filter((risk) => moneyView(risk.money).kind !== 'unknown');
  const others = identical ? identical.cells.filter((cell) => cell.row_id && cell.row_id !== facts.rowId) : [];

  const body = (
    <div className="space-y-4">
      <dl className="grid grid-cols-3 gap-x-4 gap-y-2">
        <div>
          <dt className="text-caption text-ink-tertiary">{t('Quantity')}</dt>
          <dd className="sheet-figures text-body text-ink">
            {formatDecimal(facts.quantity)}
            {facts.unit ? ` ${facts.unit}` : ''}
          </dd>
        </div>
        <div>
          <dt className="text-caption text-ink-tertiary">{t('Unit price')}</dt>
          <dd className="sheet-figures text-body text-ink">{money(facts.unitPrice, currency)}</dd>
        </div>
        <div>
          <dt className="text-caption text-ink-tertiary">{t('Line total')}</dt>
          <dd className="sheet-figures text-body text-ink">{money(facts.lineTotal, currency)}</dd>
        </div>
      </dl>

      {peer && (
        <div className="space-y-2">
          <Heading>{t('Unit price against comparable positions')}</Heading>
          <PriceRange
            lowest={peer.lowest}
            highest={peer.highest}
            median={peer.median}
            current={facts.unitPrice}
            simulated={typedPrice}
            currency={currency}
            peers={typeof peer.peers === 'number' ? peer.peers : null}
          />
          {peerChange && (
            <p className="text-body text-ink">
              {tRich('{change} against the median of the comparable positions.', {
                change: <span className="sheet-figures font-medium">{formatDecimal(peerChange, { signed: true })} %</span>,
              })}
            </p>
          )}
        </div>
      )}
      {identical && (
        <div className="space-y-1">
          <p className="text-body text-ink">
            {tRich('Identical positions are priced at {price}.', {
              price: <span className="sheet-figures">{money(identical.reference, currency)}</span>,
            })}
          </p>
          {others.length > 0 && (
            <div className="-ml-3 flex flex-wrap gap-1">
              {others.slice(0, 6).map((cell) => (
                <Button
                  key={`${cell.row_id}:${cell.column_id}`}
                  variant="ghost"
                  icon={Crosshair}
                  onPress={() => onShowInSheet({ tableId: cell.table_id, rowId: cell.row_id, columnId: cell.column_id ?? null })}
                >
                  {t('Show the identical position')}
                </Button>
              ))}
            </div>
          )}
        </div>
      )}
      {comparisons.others.map((issue) => (
        <p key={issue.issue_id} className="text-callout text-ink">
          {issue.title}
        </p>
      ))}

      {withMoney.length > 0 && (
        <div className="space-y-2">
          <Heading>{t('Money on this position')}</Heading>
          <ul className="space-y-2">
            {withMoney.map((risk) => {
              const reference = risk.money?.reference?.recomputed ?? null;
              return (
                <li key={risk.risk_id} className="space-y-1">
                  <MoneyText money={risk.money} showBasis />
                  {reference && (
                    <div className="-ml-3">
                      <Button variant="ghost" onPress={() => setSuggestion({ price: String(reference), nonce: Date.now() })}>
                        {t('Use as new price')}
                      </Button>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}

      <PriceSimulator
        key={facts.rowId}
        facts={facts}
        currency={currency}
        suggestion={suggestion}
        approvedFinding={approvedFinding}
        datasetId={datasetId}
        revision={revision}
        onRevised={onRevised}
        onCorrected={onCorrected}
        onPriceChange={setTypedPrice}
      />
    </div>
  );

  if (open) {
    return (
      <section className="space-y-2">
        <h3 className="text-callout font-semibold text-ink">{t('Price')}</h3>
        {body}
      </section>
    );
  }
  return <Disclosure title={t('Price of this position')}>{body}</Disclosure>;
}
