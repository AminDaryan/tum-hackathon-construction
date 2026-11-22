import { t, tRich } from '../../../i18n/messages.ts';
import { formatCount } from '../../../utils/format.ts';
import type { ReactNode } from 'react';
import type { Risk } from '../../../services/apiTypes.ts';

interface EvidenceListProps {
  title: string;
  items: ReactNode[];
}

function EvidenceList({ title, items }: EvidenceListProps) {
  if (!items.length) return null;
  return (
    <div>
      <h4 className="text-callout font-semibold text-ink">{title}</h4>
      <ul className="mt-1 space-y-1.5">
        {items.map((item, index) => (
          // Evidence lines have no id of their own; their order is the report's.
          <li key={index} className="text-callout text-ink">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

interface RiskEvidenceProps {
  risk: Risk;
}

/** Quotes, evidence links, counter evidence and what was checked, then the rules behind the risk. */
export function RiskEvidence({ risk }: RiskEvidenceProps) {
  const quotes = (risk.quotes ?? []).map((quote) => (
    <>
      <span className="text-ink-secondary">
        {quote.position ? `${quote.position}, ${quote.source}: ` : `${quote.source}: `}
      </span>
      <q className="break-words">{quote.text}</q>
    </>
  ));
  const links = (risk.evidence_links ?? []).map((link) => {
    const labels = (link.positions ?? []).map((position) => position.label);
    const more = (link.positions_total ?? labels.length) - labels.length;
    return `${link.label}: ${labels.join(', ')}${more > 0 ? ` ${t('and {count} more', { count: formatCount(more) })}` : ''}`;
  });
  const against = (risk.counter_evidence ?? []).map((item) => `${item.position ? `${item.position}: ` : ''}${item.detail}`);
  return (
    <div className="space-y-3">
      <EvidenceList title={t('Quotes')} items={quotes} />
      <EvidenceList title={t('Evidence')} items={links} />
      <EvidenceList title={t('Speaks against it')} items={against} />
      <EvidenceList title={t('Checked')} items={risk.checked ?? []} />
      <p className="text-caption text-ink-tertiary">
        {tRich('Rules behind it: {rules}', { rules: <span className="font-mono">{(risk.rules ?? []).join(', ')}</span> })}
      </p>
    </div>
  );
}
