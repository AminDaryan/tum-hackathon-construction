import { t } from '../i18n/messages.ts';

interface TokenListProps {
  items?: string[];
  emptyLabel?: string;
}

/**
 * Inline list of identifiers (field ids, data types, categories) in monospace.
 */
export function TokenList({ items, emptyLabel }: TokenListProps) {
  if (!items?.length) {
    return <span className="text-callout text-ink-tertiary">{emptyLabel ?? t('None')}</span>;
  }
  return (
    <ul className="flex flex-wrap gap-1">
      {items.map((item) => (
        <li
          key={item}
          className="rounded-sm border border-hairline bg-surface-muted px-1.5 font-mono text-caption leading-5 text-ink"
        >
          {item}
        </li>
      ))}
    </ul>
  );
}
