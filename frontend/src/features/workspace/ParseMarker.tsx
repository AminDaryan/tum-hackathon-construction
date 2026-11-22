import { CircleHelp, CircleSlash, CircleX, Info, Tag, type LucideIcon } from 'lucide-react';
import { Button as AriaButton } from 'react-aria-components';
import { Tooltip } from '../../components/Tooltip.tsx';
import { t } from '../../i18n/messages.ts';
import { cx } from '../../utils/classNames.ts';
import { labelFor, PARSE_STATUS_DESCRIPTIONS, PARSE_STATUS_LABELS, VALUE_MARKER_LABELS } from '../../utils/vocabulary.ts';

const MARKER_STYLES: Readonly<Record<string, { icon: LucideIcon; className: string }>> = Object.freeze({
  inferred: { icon: Info, className: 'text-ink-tertiary' },
  ambiguous: { icon: CircleHelp, className: 'text-anomaly' },
  failed: { icon: CircleX, className: 'text-danger' },
  unavailable: { icon: CircleSlash, className: 'text-ink-tertiary' },
  marker: { icon: Tag, className: 'text-ink-tertiary' },
});

interface ParseMarkerProps {
  status: string;
  note?: string | null;
  marker?: string | null;
}

/**
 * Marker for a cell whose value was not read verbatim (inferred, ambiguous, failed,
 * unavailable). Hover or keyboard focus shows the parse note in an accessible tooltip; the
 * status is also the marker's accessible name, so it is never conveyed by colour alone.
 */
export function ParseMarker({ status, note, marker }: ParseMarkerProps) {
  const style = MARKER_STYLES[status] ?? MARKER_STYLES.inferred;
  const Icon = style.icon;
  const label = t(labelFor(PARSE_STATUS_LABELS, status));
  const meaning = status === 'marker' && marker ? VALUE_MARKER_LABELS[marker] : null;
  const description = (meaning && t(meaning)) || note || t(PARSE_STATUS_DESCRIPTIONS[status]) || t('No parse note was recorded.');
  return (
    <Tooltip
      content={
        <>
          <span className="font-semibold">{label}.</span> {description}
        </>
      }
    >
      <AriaButton
          aria-label={t('Parse status: {label}', { label })}
          // 20 px visible; the hit area reaches 44 × 44 (48 × 48 on coarse pointers), as tall as
          // a preview row, so it never overlaps a marker in the row above or below.
          className="relative inline-flex size-5 shrink-0 cursor-pointer items-center justify-center rounded-sm before:absolute before:-inset-3 pointer-coarse:before:-inset-3.5"
        >
          <Icon aria-hidden="true" className={cx('size-3.5', style.className)} strokeWidth={2} />
      </AriaButton>
    </Tooltip>
  );
}
