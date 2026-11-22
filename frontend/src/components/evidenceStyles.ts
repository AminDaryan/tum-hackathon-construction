/**
 * Visual language of the evidence classes: one icon and one tone per class. Shared by
 * EvidenceBadge, the workspace metric strip and the issue filters so a class always looks the
 * same. Colour is never used alone: every use renders the icon and the text label too.
 */
import {
  BadgeCheck,
  CircleHelp,
  Info,
  MessageSquareWarning,
  OctagonAlert,
  ScanSearch,
  TriangleAlert,
} from 'lucide-react';
import type { ElementType } from 'react';
import type { BadgeTone } from './Badge.tsx';

interface EvidenceStyle {
  icon: ElementType;
  tone: BadgeTone;
  iconClassName: string;
  cellClassName: string;
}

// `cellClassName` marks a table cell that a finding highlights (a tint and a bar on its left);
// the row's finding marker carries the icon and the text.
const EVIDENCE_STYLES: Readonly<Record<string, EvidenceStyle>> = Object.freeze({
  confirmed_rule_violation: {
    icon: OctagonAlert,
    tone: 'violation',
    iconClassName: 'text-violation',
    cellClassName: 'bg-violation-bg shadow-[inset_3px_0_0_var(--color-violation)]',
  },
  suspected_anomaly: {
    icon: TriangleAlert,
    tone: 'anomaly',
    iconClassName: 'text-anomaly',
    cellClassName: 'bg-anomaly-bg shadow-[inset_3px_0_0_var(--color-anomaly)]',
  },
  semantic_warning: {
    icon: MessageSquareWarning,
    tone: 'semantic',
    iconClassName: 'text-semantic',
    cellClassName: 'bg-semantic-bg shadow-[inset_3px_0_0_var(--color-semantic)]',
  },
  extraction_uncertainty: {
    icon: ScanSearch,
    tone: 'extraction',
    iconClassName: 'text-extraction',
    cellClassName: 'bg-extraction-bg shadow-[inset_3px_0_0_var(--color-extraction)]',
  },
  needs_external_context: {
    icon: CircleHelp,
    tone: 'context',
    iconClassName: 'text-context',
    cellClassName: 'bg-context-bg shadow-[inset_3px_0_0_var(--color-context)]',
  },
  human_confirmed_error: {
    icon: BadgeCheck,
    tone: 'confirmed',
    iconClassName: 'text-confirmed',
    cellClassName: 'bg-violation-bg shadow-[inset_3px_0_0_var(--color-confirmed)]',
  },
});

const UNKNOWN_STYLE: EvidenceStyle = Object.freeze({
  icon: Info,
  tone: 'neutral',
  iconClassName: 'text-ink-tertiary',
  cellClassName: 'bg-surface-muted shadow-[inset_3px_0_0_var(--color-hairline-strong)]',
});

export function evidenceStyle(evidenceClass: string | null | undefined): EvidenceStyle {
  return (evidenceClass && EVIDENCE_STYLES[evidenceClass]) || UNKNOWN_STYLE;
}
