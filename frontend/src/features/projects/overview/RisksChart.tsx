import { Skeleton } from '../../../components/Skeleton.tsx';
import { t } from '../../../i18n/messages.ts';
import { formatCount } from '../../../utils/format.ts';
import { SEVERITY_META } from '../../../utils/vocabulary.ts';

/** The priorities, highest first, and the colour of their bars (the colours of the priority badges). */
const PRIORITIES = [
  { id: 'critical', bar: 'bg-danger' },
  { id: 'high', bar: 'bg-danger/60' },
  { id: 'medium', bar: 'bg-warning' },
  { id: 'low', bar: 'bg-ink-tertiary' },
  { id: 'info', bar: 'bg-ink-tertiary/50' },
] as const;

/**
 * "Risks" in the project overview (its name for screen readers): the findings of the last
 * validation by priority, one bar per priority, highest first, each with its word and count
 * (colour is never the only signal). Shown before a validation too (`counts` null), with empty
 * bars and "—" for the counts, so the overview keeps its shape without claiming zero findings.
 * A bar's length is its share of the largest count. While the project loads (`loading`), the
 * counts are grey.
 */
export function RisksChart({ counts, loading = false }: { counts: Record<string, number> | null; loading?: boolean }) {
  const largest = Math.max(1, ...PRIORITIES.map(({ id }) => counts?.[id] ?? 0));
  return (
    <section aria-label={t('Risks')}>
      <dl className="flex flex-col">
        {PRIORITIES.map(({ id, bar }) => {
          const count = counts?.[id] ?? 0;
          const shown = counts ? formatCount(count) : '—';
          const label = t(SEVERITY_META[id].label);
          return (
            <div key={id} title={loading ? undefined : `${label}: ${shown}`} className="grid min-h-5 grid-cols-[5rem_minmax(0,1fr)_3rem] items-center gap-3">
              <dt className="truncate text-callout text-ink-secondary">{label}</dt>
              <div aria-hidden="true" className="h-2 rounded-full bg-surface-muted">
                {count > 0 && <div className={`h-full rounded-full ${bar}`} style={{ width: `${(count / largest) * 100}%` }} />}
              </div>
              <dd className="flex justify-end text-callout font-medium tabular-nums text-ink">
                {loading ? <Skeleton className="h-3 w-4" /> : shown}
              </dd>
            </div>
          );
        })}
      </dl>
    </section>
  );
}
