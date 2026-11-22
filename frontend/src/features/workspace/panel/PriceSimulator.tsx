import { useEffect, useId, useState } from 'react';
import { Button } from '../../../components/Button.tsx';
import { TextField } from '../../../components/Field.tsx';
import { useAsyncAction } from '../../../hooks/useAsyncAction.ts';
import { correctCells } from '../../../services/datasetsService.ts';
import { submitCorrection } from '../../../services/issuesService.ts';
import { cx } from '../../../utils/classNames.ts';
import { compareDecimal, decimalToString, parseDecimal } from '../../../utils/decimal.ts';
import { describeError } from '../../../utils/errors.ts';
import { t } from '../../../i18n/messages.ts';
import { formatDecimal } from '../../../utils/format.ts';
import { difference, lineTotalFor, percentBetween, type PriceFacts } from '../../risks/pricing.ts';
import type { ReactNode } from 'react';
import type { CorrectionsResult, IssueCorrectionResult, ValidationIssue } from '../../../services/apiTypes.ts';

interface CellText {
  table_id: string;
  row_id: string;
  column_id: string;
  raw_value: string;
}

const NOTE_LIMIT = 4000;

/** Whether the line total rule reproduces the line total the row has now (no hidden factor). */
function totalFollowsRule(facts: PriceFacts) {
  if (!facts.columns.line_total || !facts.lineTotal) return false;
  const expected = parseDecimal(lineTotalFor(facts.quantity, facts.unitPrice, facts.discount));
  const actual = parseDecimal(facts.lineTotal);
  return Boolean(expected && actual && compareDecimal(expected, actual) === 0);
}

interface FigureProps {
  label: string;
  value: ReactNode;
  emphasis?: boolean;
}

function Figure({ label, value, emphasis = false }: FigureProps) {
  return (
    <div className="min-w-0">
      <dt className="text-caption text-ink-tertiary">{label}</dt>
      <dd className={cx('sheet-figures mt-0.5 text-body', emphasis ? 'font-semibold text-ink' : 'text-ink')}>{value}</dd>
    </div>
  );
}

interface PriceSimulatorProps {
  facts: PriceFacts;
  currency?: string | null;
  /** a new nonce each time "Use as new price" is pressed */
  suggestion?: { price: string; nonce: number } | null;
  approvedFinding?: ValidationIssue | null;
  datasetId: string;
  revision: number;
  onRevised: (result: CorrectionsResult) => void;
  onCorrected: (result: IssueCorrectionResult) => void;
  onPriceChange?: (price: string | null) => void;
}

/**
 * "Try a new unit price": the line total a typed unit price gives (quantity times price,
 * rounded to cents, the discount applied to the rounded total and rounded again) and its change
 * against the current line total, in exact decimals. "Save the new price" writes the unit price
 * and the line total as the next revision of the file: through the correction of an approved
 * price finding of this row (which also validates the table again), otherwise as a plain cell
 * edit. When the rule does not reproduce the current line total, only the unit price is saved.
 */
export function PriceSimulator({
  facts,
  currency = null,
  suggestion = null,
  approvedFinding = null,
  datasetId,
  revision,
  onRevised,
  onCorrected,
  onPriceChange = () => {},
}: PriceSimulatorProps) {
  const inputId = useId();
  const [price, setPrice] = useState('');
  const [note, setNote] = useState('');
  const [saved, setSaved] = useState<{ revision: number; price: string } | null>(null);

  // "Use as new price" fills the field (a new nonce each time).
  useEffect(() => {
    if (suggestion?.price) {
      setPrice(suggestion.price);
      setSaved(null);
    }
  }, [suggestion]);

  const save = useAsyncAction(async (signal, cells: CellText[]) => {
    if (approvedFinding) {
      const result = await submitCorrection(
        approvedFinding.issue_id,
        {
          expectedVersion: approvedFinding.version,
          cells: cells.map((cell) => ({ table_id: cell.table_id, row_id: cell.row_id, column_id: cell.column_id, value: cell.raw_value })),
          comment: note,
          rerunValidation: true,
        },
        { signal },
      );
      return { kind: 'correction' as const, result, revision: result.dataset?.revision ?? revision + 1 };
    }
    const result = await correctCells(datasetId, { expectedRevision: revision, corrections: cells }, { signal });
    return { kind: 'edit' as const, result, revision: result.revision ?? revision + 1 };
  });

  const parsed = parseDecimal(price);
  const valid = parsed !== null && parsed.units >= 0n;
  const typed = valid ? decimalToString(parsed) : null;
  const withTotal = totalFollowsRule(facts);
  const newTotal = typed ? lineTotalFor(facts.quantity, typed, facts.discount) : null;
  const change = newTotal && facts.lineTotal ? difference(facts.lineTotal, newTotal) : null;
  const changePercent = newTotal && facts.lineTotal ? percentBetween(facts.lineTotal, newTotal) : null;
  const current = parseDecimal(facts.unitPrice);
  const unchanged = Boolean(typed && valid && current && compareDecimal(parsed, current) === 0);
  const unit = currency ? ` ${currency}` : '';

  // The range bar above shows the typed price as "New price".
  useEffect(() => {
    onPriceChange(typed && !unchanged ? typed : null);
  }, [typed, unchanged, onPriceChange]);

  const submit = async () => {
    const { tableId, columns } = facts;
    // A priced row always has its table and a unit price column.
    if (!typed || unchanged || !tableId || !columns.unit_price) return;
    const cells: CellText[] = [{ table_id: tableId, row_id: facts.rowId, column_id: columns.unit_price, raw_value: typed }];
    if (withTotal && newTotal && columns.line_total) {
      cells.push({ table_id: tableId, row_id: facts.rowId, column_id: columns.line_total, raw_value: newTotal });
    }
    const outcome = await save.execute(cells);
    if (!outcome) return;
    setSaved({ revision: outcome.revision, price: typed });
    setNote('');
    if (outcome.kind === 'correction') onCorrected(outcome.result);
    else onRevised(outcome.result);
  };

  const failure = save.error && !save.pending ? describeError(save.error) : null;
  const inputInvalid = price.trim() !== '' && !valid;
  return (
    <section aria-labelledby={`${inputId}-heading`} className="space-y-3">
      <h3 id={`${inputId}-heading`} className="text-callout font-semibold text-ink">
        {t('Try a new unit price')}
      </h3>
      <TextField
        label={currency ? t('New unit price in {currency}', { currency }) : t('New unit price')}
        inputMode="decimal"
        autoComplete="off"
        value={price}
        placeholder={facts.unitPrice ?? undefined}
        errorMessage={inputInvalid ? t('Type a number such as 63.50 or 63,50.') : undefined}
        inputClassName="sheet-figures max-w-60 text-body"
        onChange={(value) => {
          setPrice(value);
          setSaved(null);
        }}
      />
      {newTotal && (
        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 @md:grid-cols-3">
          <Figure label={t('Line total now')} value={facts.lineTotal ? `${formatDecimal(facts.lineTotal)}${unit}` : t('Not given')} />
          <Figure label={t('New line total')} value={`${formatDecimal(newTotal)}${unit}`} emphasis />
          {change && (
            <Figure
              label={t('Change')}
              value={`${formatDecimal(change, { signed: true })}${unit}${changePercent ? ` (${formatDecimal(changePercent, { signed: true })} %)` : ''}`}
            />
          )}
        </dl>
      )}
      {approvedFinding && typed && !unchanged && (
        <TextField label={t('Note (optional)')} multiline rows={2} value={note} maxLength={NOTE_LIMIT} onChange={setNote} />
      )}
      <div className="space-y-1">
        <Button variant="primary" isDisabled={!typed || unchanged} loading={save.pending} onPress={submit}>
          {t('Save the new price')}
        </Button>
        {saved ? (
          <p role="status" className="text-callout text-ink">
            {t('Saved as revision {revision}. The uploaded file stays unchanged.', { revision: saved.revision })}
          </p>
        ) : (
          (approvedFinding || !withTotal) && (
            <p className="text-caption text-ink-secondary">
              {approvedFinding &&
                t('Saves as revision {revision}, marks the approved finding as corrected and validates the table again.', { revision: revision + 1 })}
              {approvedFinding && !withTotal && ' '}
              {!withTotal && t('Only the unit price is saved; the line total is checked on the next validation.')}
            </p>
          )
        )}
        {failure && (
          <p role="alert" className="text-callout text-danger">
            {t('The price was not saved.')} {failure.message}
            {failure.hint && <span className="block text-ink-secondary">{failure.hint}</span>}
          </p>
        )}
      </div>
    </section>
  );
}
