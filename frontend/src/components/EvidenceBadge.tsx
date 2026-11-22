import {
  EVIDENCE_CLASS_DESCRIPTIONS,
  EVIDENCE_CLASS_LABELS,
  labelFor,
} from '../utils/vocabulary.ts';
import { Badge } from './Badge.tsx';
import { evidenceStyle } from './evidenceStyles.ts';
import { t } from '../i18n/messages.ts';

interface EvidenceBadgeProps {
  evidenceClass: string;
  className?: string;
}

/**
 * Evidence class as colour + icon + text label, e.g. a red octagon "Rule violation".
 */
export function EvidenceBadge({ evidenceClass, className }: EvidenceBadgeProps) {
  const style = evidenceStyle(evidenceClass);
  return (
    <Badge
      tone={style.tone}
      icon={style.icon}
      title={t(EVIDENCE_CLASS_DESCRIPTIONS[evidenceClass])}
      className={className}
    >
      {labelFor(EVIDENCE_CLASS_LABELS, evidenceClass)}
    </Badge>
  );
}
