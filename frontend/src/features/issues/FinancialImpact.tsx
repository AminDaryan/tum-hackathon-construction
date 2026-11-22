import { KeyValueList } from '../../components/KeyValueList.tsx';
import { msg, t } from '../../i18n/messages.ts';
import { formatDecimal } from '../../utils/format.ts';
import type { FinancialImpact } from '../../services/apiTypes.ts';

const KIND_NOTES: Readonly<Record<string, string>> = {
  discrepancy: msg(
    'Amount = reported − recomputed: a positive amount means the document states more than the recomputed value. It shows that the figures disagree, not which one is wrong.',
  ),
  potential_double_count: msg(
    'The value of rows that look duplicated: it would be counted twice if both rows stay in the total.',
  ),
  reference_deviation: msg(
    'Quantity × (unit price − reference unit price), after any item discount. Reported and recomputed below are unit prices, not line totals. This is a comparison scenario, not a confirmed loss or a market-price estimate.',
  ),
};

interface MoneyProps {
  value: string;
  currency?: string | null;
}

function Money({ value, currency }: MoneyProps) {
  return (
    <span className="font-mono tabular-nums">
      {value} {currency ?? <span className="font-sans text-ink-tertiary">{t('(currency unknown)')}</span>}
    </span>
  );
}

interface FinancialImpactProps {
  impact: FinancialImpact;
}

/** Estimated financial impact, present only when the API could calculate it. */
export function FinancialImpact({ impact }: FinancialImpactProps) {
  const { currency } = impact;
  return (
    <>
      <KeyValueList
        layout="inline"
        items={[
          { label: t('Amount'), value: <Money value={formatDecimal(impact.amount, { signed: true })} currency={currency} /> },
          impact.reported != null && {
            label: t('Reported'),
            value: <Money value={formatDecimal(impact.reported)} currency={currency} />,
          },
          impact.recomputed != null && {
            label: t('Recomputed'),
            value: <Money value={formatDecimal(impact.recomputed)} currency={currency} />,
          },
          impact.basis && { label: t('Basis'), value: impact.basis },
        ]}
      />
      <p className="mt-2 text-caption text-ink-secondary">{t(KIND_NOTES[impact.kind] ?? KIND_NOTES.discrepancy)}</p>
    </>
  );
}
