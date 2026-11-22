import { CellReference } from '../../components/CellReference.tsx';
import { t } from '../../i18n/messages.ts';
import { formatCount } from '../../utils/format.ts';
import type { CellRef } from '../../services/apiTypes.ts';

const VISIBLE_LIMIT = 12;

interface CellReferenceListProps {
  cells?: CellRef[];
  emptyLabel?: string;
}

/** Source references of a list of cells, e.g. `LV!F12, LV!F13`; long lists are capped. */
export function CellReferenceList({ cells, emptyLabel }: CellReferenceListProps) {
  const located = (cells ?? []).filter((cell) => cell.source);
  if (!located.length) {
    return <span className="text-callout text-ink-tertiary">{emptyLabel ?? t('None')}</span>;
  }
  const visible = located.slice(0, VISIBLE_LIMIT);
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-1">
      {visible.map((cell) => (
        <li key={`${cell.table_id}:${cell.row_id}:${cell.column_id}`}>
          <CellReference source={cell.source} />
        </li>
      ))}
      {located.length > VISIBLE_LIMIT && (
        <li className="text-callout text-ink-tertiary">{t('and {count} more', { count: formatCount(located.length - VISIBLE_LIMIT) })}</li>
      )}
    </ul>
  );
}
