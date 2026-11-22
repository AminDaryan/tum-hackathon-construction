import { t } from '../../../i18n/messages.ts';
import { formatCount, formatDecimal } from '../../../utils/format.ts';
import { rangePositions } from '../../risks/pricing.ts';

function percent(share: number) {
  return `${(share * 100).toFixed(2)}%`;
}

interface GlyphProps {
  kind: 'range' | 'median' | 'current' | 'simulated';
}

/** The glyph of a mark, repeated in the legend so no mark is told apart by colour alone. */
function Glyph({ kind }: GlyphProps) {
  if (kind === 'range') return <span aria-hidden="true" className="inline-block h-2 w-4 rounded-full bg-accent-subtle ring-1 ring-accent/40" />;
  if (kind === 'median') return <span aria-hidden="true" className="inline-block h-3 w-0.5 rounded-full bg-ink" />;
  if (kind === 'current') return <span aria-hidden="true" className="inline-block size-2.5 rounded-full bg-accent ring-2 ring-surface" />;
  return <span aria-hidden="true" className="inline-block size-2.5 rounded-full border-2 border-ink bg-surface" />;
}

interface PriceRangeProps {
  lowest?: string | null;
  highest?: string | null;
  median?: string | null;
  current?: string | null;
  simulated?: string | null;
  currency?: string | null;
  peers?: number | null;
}

/**
 * The unit price of a position against the comparable positions the peer price check found: a
 * linear scale from zero, the range from the lowest to the highest comparable price, their
 * median, the current price and, when one is typed, the new price. Every mark is named and
 * valued in the legend under the bar.
 */
export function PriceRange({
  lowest,
  highest,
  median,
  current,
  simulated = null,
  currency = null,
  peers = null,
}: PriceRangeProps) {
  const shares = rangePositions({ lowest, highest, median, current, simulated });
  if (!shares) return null;
  const unit = currency ? ` ${currency}` : '';
  type Item = { kind: GlyphProps['kind']; label: string; value: string };
  const items = ([
    lowest != null &&
      highest != null && {
        kind: 'range',
        label: peers ? t('Range of {count} comparable positions', { count: formatCount(peers) }) : t('Range of comparable positions'),
        value: `${t('{lowest} to {highest}', { lowest: formatDecimal(lowest), highest: formatDecimal(highest) })}${unit}`,
      },
    median != null && { kind: 'median', label: t('Median'), value: `${formatDecimal(median)}${unit}` },
    current != null && { kind: 'current', label: t('This position'), value: `${formatDecimal(current)}${unit}` },
    simulated != null && { kind: 'simulated', label: t('New price'), value: `${formatDecimal(simulated)}${unit}` },
  ] as (Item | false)[]).filter((item): item is Item => Boolean(item));

  const point = (share: number) => ({ left: percent(share) });
  return (
    <figure className="space-y-3">
      <div aria-hidden="true" className="relative mx-1.5 h-6">
        <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-hairline-strong" />
        {shares.lowest != null && shares.highest != null && (
          <div
            title={items[0]?.value}
            className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-accent-subtle ring-1 ring-accent/40"
            style={{ left: percent(shares.lowest), width: percent(Math.max(shares.highest - shares.lowest, 0.004)) }}
          />
        )}
        {shares.median != null && (
          <div title={`${t('Median')} ${formatDecimal(median)}${unit}`} className="absolute top-1/2 h-4 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-ink" style={point(shares.median)} />
        )}
        {shares.current != null && (
          <div
            title={`${t('This position')} ${formatDecimal(current)}${unit}`}
            className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent ring-2 ring-surface"
            style={point(shares.current)}
          />
        )}
        {shares.simulated != null && (
          <div
            title={`${t('New price')} ${formatDecimal(simulated)}${unit}`}
            className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-ink bg-surface"
            style={point(shares.simulated)}
          />
        )}
      </div>
      <figcaption>
        <dl className="space-y-1">
          {items.map((item) => (
            <div key={item.kind} className="flex min-w-0 items-center gap-2">
              <Glyph kind={item.kind} />
              <dt className="text-caption text-ink-secondary">{item.label}</dt>
              <dd className="sheet-figures ml-auto text-callout text-ink">{item.value}</dd>
            </div>
          ))}
        </dl>
        <p className="mt-1 text-caption text-ink-tertiary">{t('Scale from zero, unit prices.')}</p>
      </figcaption>
    </figure>
  );
}
