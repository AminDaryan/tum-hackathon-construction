import { msg, t } from '../../i18n/messages.ts';
import { formatCount, formatDecimal } from '../../utils/format.ts';
import { formatCellReference } from '../../utils/sourceLocation.ts';
import type { ReactNode } from 'react';
import type { Calculation } from '../../services/apiTypes.ts';

const OPERATIONS = {
  product: { label: msg('Product'), symbol: '×' },
  sum: { label: msg('Sum'), symbol: '+' },
  difference: { label: msg('Difference'), symbol: '−' },
  percentage: { label: msg('Percentage'), symbol: null },
  comparison: { label: msg('Comparison'), symbol: null },
};

interface LineProps {
  label: ReactNode;
  value: ReactNode;
  reference?: ReactNode;
  emphasis?: boolean;
}

function Line({ label, value, reference, emphasis = false }: LineProps) {
  return (
    <tr>
      <th scope="row" className="py-px pr-3 text-left align-top font-normal text-ink-secondary">
        {label}
      </th>
      <td className={`py-px text-right align-top tabular-nums ${emphasis ? 'font-semibold text-ink' : 'text-ink'}`}>
        {value}
      </td>
      <td className="py-px pl-3 align-top text-ink-tertiary">{reference}</td>
    </tr>
  );
}

interface CalculationBlockProps {
  calculation: Calculation;
}

/**
 * A recomputation written out from the typed `calculation` structure: operands with their
 * source cells, the exact result, rounding, the reported value and the difference. Values are
 * exact decimal strings from the API and are never converted to floating point.
 */
export function CalculationBlock({ calculation }: CalculationBlockProps) {
  const operation = OPERATIONS[calculation.operation] ?? { label: calculation.operation, symbol: null };
  const operands = calculation.operands ?? [];
  const hidden = Math.max(0, (calculation.terms ?? operands.length) - operands.length);
  return (
    <div className="overflow-x-auto rounded-md border border-hairline bg-surface-muted px-3 py-2 font-mono text-caption leading-5">
      <table className="w-full border-collapse">
        <caption className="pb-1 text-left text-ink-secondary">
          {calculation.terms > operands.length
            ? t('{operation} of {count} terms', { operation: t(operation.label), count: formatCount(calculation.terms) })
            : t(operation.label)}
        </caption>
        <tbody>
          {operands.map((operand, index) => (
            <Line
              key={`${operand.label}-${index}`}
              label={`${index > 0 && operation.symbol ? `${operation.symbol} ` : ''}${operand.label}`}
              value={formatDecimal(operand.value)}
              reference={operand.cell?.source ? formatCellReference(operand.cell.source) : null}
            />
          ))}
          {(calculation.operands_truncated || hidden > 0) && (
            <tr>
              <td colSpan={3} className="py-px text-ink-tertiary">
                … {hidden > 0 ? hidden === 1 ? t('{count} more term not listed', { count: formatCount(hidden) }) : t('{count} more terms not listed', { count: formatCount(hidden) }) : t('further terms not listed')}
              </td>
            </tr>
          )}
          <Line label={`= ${t('Exact result')}`} value={formatDecimal(calculation.exact_result)} emphasis />
          {calculation.rounding && (
            <Line label={t('Rounded ({rounding})', { rounding: calculation.rounding })} value={formatDecimal(calculation.rounded_result)} />
          )}
          {calculation.reported != null && <Line label={t('Reported')} value={formatDecimal(calculation.reported)} />}
          {calculation.difference != null && (
            <Line
              label={t('Difference (reported − expected)')}
              value={formatDecimal(calculation.difference, { signed: true })}
              emphasis
            />
          )}
          {calculation.allowed_difference != null && (
            <Line label={t('Allowed difference')} value={`±${formatDecimal(calculation.allowed_difference)}`} />
          )}
        </tbody>
      </table>
    </div>
  );
}
