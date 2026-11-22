import { useCallback, useLayoutEffect, useState, type RefObject } from 'react';
import { readStorage, writeStorage } from '../../../utils/safeStorage.ts';

export const PANEL_WIDTH_KEY = 'twb.workspace.panelWidth';
/** The panel is never narrower than this: the decision buttons and the tabs fit. */
export const PANEL_MIN = 440;
/** Nor wider than this, and never so wide that the sheet gets less than SHEET_MIN. */
export const PANEL_MAX = 860;
const SHEET_MIN = 480;
/** The divider's column and the gaps on either side of it. */
const DIVIDER_SPACE = 48;
/** The panel's share of the workspace until the reviewer moves the divider. */
const DEFAULT_SHARE = 0.44;

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

/**
 * The widest the panel may be in a workspace `containerWidth` px wide.
 */
export function maxPanelWidth(containerWidth: number | null) {
  if (!containerWidth) return PANEL_MAX;
  return Math.max(PANEL_MIN, Math.min(PANEL_MAX, containerWidth - SHEET_MIN - DIVIDER_SPACE));
}

/**
 * @param stored the width the reviewer chose, or null
 * @returns the panel width in px
 */
export function panelWidthFor(stored: number | null, containerWidth: number | null): number {
  const preferred = stored ?? (containerWidth ? Math.round(containerWidth * DEFAULT_SHARE) : 560);
  return clamp(preferred, PANEL_MIN, maxPanelWidth(containerWidth));
}

function readStored() {
  const value = Number(readStorage(PANEL_WIDTH_KEY));
  return Number.isFinite(value) && value > 0 ? value : null;
}

/**
 * The width of the workspace's side panel: 44 % of the workspace until the reviewer drags or
 * moves the divider, then that width (remembered in this browser), always within the limits.
 * `containerRef` is the element the sheet and the panel share.
 */
export function usePanelWidth(containerRef: RefObject<HTMLElement | null>) {
  const [stored, setStored] = useState(readStored);
  const [containerWidth, setContainerWidth] = useState<number | null>(null);

  useLayoutEffect(() => {
    const element = containerRef.current;
    if (!element) return undefined;
    const measure = () => setContainerWidth(element.getBoundingClientRect().width || null);
    measure();
    if (typeof ResizeObserver === 'undefined') return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [containerRef]);

  const max = maxPanelWidth(containerWidth);
  const width = panelWidthFor(stored, containerWidth);

  const setWidth = useCallback(
    (next: number) => {
      const value = clamp(Math.round(next), PANEL_MIN, max);
      setStored(value);
      writeStorage(PANEL_WIDTH_KEY, String(value));
    },
    [max],
  );
  const reset = useCallback(() => {
    setStored(null);
    writeStorage(PANEL_WIDTH_KEY, null);
  }, []);

  return { width, min: PANEL_MIN, max, setWidth, reset };
}
