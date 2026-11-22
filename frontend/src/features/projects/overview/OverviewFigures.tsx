import { Info } from 'lucide-react';
import { IconButton } from '../../../components/IconButton.tsx';
import { Skeleton } from '../../../components/Skeleton.tsx';
import { t } from '../../../i18n/messages.ts';
import { cx } from '../../../utils/classNames.ts';
import type { ProjectFigure } from '../projectOverview.ts';

const TONES = {
  neutral: 'text-ink',
  warning: 'text-warning',
  danger: 'text-danger',
};

/**
 * The project's figures as a plain list: the label at the start of the row, the figure at its
 * end, hairlines between the rows. A figure's `tone` colours it (`warning` for work left,
 * `danger` for what needs attention first); its label says what it means, so colour is never
 * the only signal. A figure not known yet (null, while the project loads) is a grey bar.
 */
export function OverviewFigures({ items }: { items: ProjectFigure[] }) {
  return (
    <dl className="divide-y divide-hairline">
      {items.map((item) => (
        <div key={item.label} className="flex min-h-8 items-center justify-between gap-4">
          <dt className="flex min-w-0 items-center gap-1 text-callout text-ink-secondary">
            <span className="truncate">{t(item.label)}</span>
            {item.label === 'To review' && <IconButton icon={Info} label={t('Unreviewed findings across the bills in the last project validation. Counts all reviewers, regardless of workspace filters.')} />}
          </dt>
          <dd className={cx('shrink-0 text-body font-semibold tabular-nums', TONES[item.tone ?? 'neutral'])}>
            {item.value ?? <Skeleton className="h-4 w-8" />}
          </dd>
        </div>
      ))}
    </dl>
  );
}
