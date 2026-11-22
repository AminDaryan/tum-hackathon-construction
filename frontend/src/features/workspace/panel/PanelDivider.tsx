import { useRef, type KeyboardEvent, type PointerEvent } from 'react';
import { t } from '../../../i18n/messages.ts';
import { cx } from '../../../utils/classNames.ts';
import { formatCount } from '../../../utils/format.ts';

const STEP = 32;

interface PanelDividerProps {
  width: number;
  min: number;
  max: number;
  onChange: (width: number) => void;
  onReset: () => void;
  controls?: string;
  className?: string;
}

/**
 * The divider between the sheet and the side panel (HIG split view): drag it, or focus it and
 * use the arrow keys (Shift moves three steps), Home for the narrowest and End for the widest
 * panel. A double click returns to the default width. The value is the panel width in px.
 */
export function PanelDivider({ width, min, max, onChange, onReset, controls, className }: PanelDividerProps) {
  const drag = useRef<{ x: number; width: number } | null>(null);

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    drag.current = { x: event.clientX, width };
    event.currentTarget.setPointerCapture?.(event.pointerId);
  };
  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    if (!drag.current) return;
    onChange(drag.current.width + (drag.current.x - event.clientX));
  };
  const endDrag = (event: PointerEvent<HTMLDivElement>) => {
    drag.current = null;
    event.currentTarget.releasePointerCapture?.(event.pointerId);
  };
  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const step = event.shiftKey ? STEP * 3 : STEP;
    const moves: Record<string, number> = {
      ArrowLeft: width + step,
      ArrowRight: width - step,
      Home: min,
      End: max,
    };
    if (event.key in moves) {
      event.preventDefault();
      onChange(moves[event.key]);
    }
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label={t('Width of the side panel')}
      aria-controls={controls}
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-valuetext={t('{count} pixels', { count: formatCount(width) })}
      title={t('Drag to resize. Double-click for the default width.')}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={endDrag}
      onPointerCancel={endDrag}
      onDoubleClick={onReset}
      onKeyDown={onKeyDown}
      className={cx(
        'group flex w-full cursor-col-resize touch-none select-none items-center justify-center rounded-md outline-offset-2',
        className,
      )}
    >
      {/* A hairline the full height: its middle holds the arrow that hides the panel. */}
      <span aria-hidden="true" className="h-full w-px bg-hairline-strong transition-colors group-hover:bg-accent group-focus-visible:bg-accent" />
    </div>
  );
}
