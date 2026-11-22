import { cx } from '../utils/classNames.ts';
import type { ElementType, ReactNode } from 'react';

/**
 * Badge tones. Evidence tones are used through EvidenceBadge so icon and label always go along;
 * priority and review status use the same badge shape (see features/workspace/panel/RiskBits).
 */
const TONE_CLASSES = {
  neutral: 'border-hairline bg-surface-muted text-ink-secondary',
  outline: 'border-hairline-strong bg-surface text-ink',
  accent: 'border-accent/30 bg-accent-subtle text-accent-strong',
  success: 'border-success/35 bg-surface text-success',
  violation: 'border-violation-border bg-violation-bg text-violation',
  anomaly: 'border-anomaly-border bg-anomaly-bg text-anomaly',
  semantic: 'border-semantic-border bg-semantic-bg text-semantic',
  extraction: 'border-extraction-border bg-extraction-bg text-extraction',
  context: 'border-context-border bg-context-bg text-context',
  confirmed: 'border-confirmed bg-confirmed text-on-confirmed',
};

export type BadgeTone = keyof typeof TONE_CLASSES;

export const BADGE_TONES = Object.freeze(Object.keys(TONE_CLASSES) as BadgeTone[]);

interface BadgeProps {
  tone?: BadgeTone;
  icon?: ElementType;
  title?: string;
  strong?: boolean;
  className?: string;
  children: ReactNode;
}

/** The badge's shape and colours, for a control that looks like one (StatusSelect). */
export function badgeClassName(tone: BadgeTone = 'neutral', strong = false): string {
  return cx(
    'inline-flex h-6 max-w-full shrink-0 items-center gap-1 whitespace-nowrap rounded-sm border px-1.5 text-caption',
    strong ? 'font-semibold' : 'font-medium',
    TONE_CLASSES[tone],
  );
}

/** Small label with an optional leading icon. `strong` sets it in semibold (priorities). */
export function Badge({ tone = 'neutral', icon: Icon, title, strong = false, className, children }: BadgeProps) {
  return (
    <span title={title} className={cx(badgeClassName(tone, strong), className)}>
      {Icon && <Icon aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2} />}
      <span className="truncate">{children}</span>
    </span>
  );
}
