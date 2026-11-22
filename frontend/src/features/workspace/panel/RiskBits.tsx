import { CircleCheck, CircleDashed, CircleSlash, Clock, type LucideIcon } from 'lucide-react';
import { Badge, type BadgeTone } from '../../../components/Badge.tsx';
import type { RiskMoney } from '../../../services/apiTypes.ts';
import { t } from '../../../i18n/messages.ts';
import { cx } from '../../../utils/classNames.ts';
import { FINDING_CATEGORY_DESCRIPTIONS, SEVERITY_META } from '../../../utils/vocabulary.ts';
import { classificationLabel, moneyView, RISK_STATUS_LABELS } from '../../risks/riskModel.ts';

/** Critical is solid dark red, high a red tint, medium amber, low and info neutral. */
const PRIORITY_TONES: Readonly<Record<string, BadgeTone>> = Object.freeze({
  critical: 'confirmed',
  high: 'violation',
  medium: 'anomaly',
  low: 'outline',
  info: 'outline',
});

interface PriorityBadgeProps {
  tier: string;
  className?: string;
}

/**
 * The review priority of a risk as a badge with its word (never colour alone).
 */
export function PriorityBadge({ tier, className }: PriorityBadgeProps) {
  const label = t(SEVERITY_META[tier]?.label ?? tier);
  return (
    <Badge tone={PRIORITY_TONES[tier] ?? 'outline'} strong className={className}>
      <span className="sr-only">{t('Priority')} </span>
      {label}
    </Badge>
  );
}

const STATUS_STYLES: Readonly<Record<string, { icon: LucideIcon; tone: BadgeTone }>> = Object.freeze({
  open: { icon: CircleDashed, tone: 'outline' },
  in_review: { icon: Clock, tone: 'anomaly' },
  approved: { icon: CircleCheck, tone: 'success' },
  rejected: { icon: CircleSlash, tone: 'neutral' },
});

interface RiskStatusProps {
  status: string;
  className?: string;
}

/** The status of a risk (Open, In review, Approved, Rejected) as a badge with icon and word. */
export function RiskStatus({ status, className }: RiskStatusProps) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.open;
  return (
    <Badge tone={style.tone} icon={style.icon} className={className}>
      {t(RISK_STATUS_LABELS[status] ?? status)}
    </Badge>
  );
}

interface ClassificationChipProps {
  classification: string;
}

/** The classification of a risk (one of the six finding categories), its meaning as tooltip. */
export function ClassificationChip({ classification }: ClassificationChipProps) {
  return (
    <Badge tone="neutral" title={t(FINDING_CATEGORY_DESCRIPTIONS[classification])}>
      {classificationLabel(classification)}
    </Badge>
  );
}

interface MethodBadgesProps {
  methods: string[];
}

/** The method words of a risk as small badges. */
export function MethodBadges({ methods }: MethodBadgesProps) {
  return methods.map((method) => (
    <Badge key={method} tone={method === 'Language model' ? 'semantic' : 'neutral'}>
      {t(method)}
    </Badge>
  ));
}

interface MoneyTextProps {
  money?: RiskMoney | null;
  showBasis?: boolean;
}

/** Money at stake in words: the amount line, then the note and the basis. */
export function MoneyText({ money, showBasis = false }: MoneyTextProps) {
  const view = moneyView(money);
  return (
    <span className="flex min-w-0 flex-col">
      <span className={cx('sheet-figures text-body', view.kind === 'unknown' ? 'text-ink-secondary' : 'text-ink')}>{view.text}</span>
      {view.note && <span className="text-caption text-ink-secondary">{view.note}</span>}
      {showBasis && view.basis && <span className="text-caption text-ink-tertiary">{view.basis}</span>}
    </span>
  );
}
