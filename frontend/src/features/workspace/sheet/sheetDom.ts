/**
 * DOM helpers of the sheet: find a cell element, keep it in view inside the grid's scroll area
 * (not the page), and respect reduced motion.
 */

/**
 * The `<td>` of a cell by its 0-based row and column on the page (the row header is cell 0).
 */
export function cellAt(
  table: HTMLTableElement | null,
  rowIndex: number,
  columnIndex: number,
): HTMLTableCellElement | null {
  return table?.tBodies[0]?.rows[rowIndex]?.cells[columnIndex + 1] ?? null;
}

/**
 * The part of the scroll area that the sticky header rows and row-number column leave free.
 */
function visibleArea(scroller: HTMLElement, cell: HTMLElement) {
  const box = scroller.getBoundingClientRect();
  const header = scroller.querySelector('thead')?.getBoundingClientRect().height ?? 0;
  // The row numbers, and the item numbers when they are kept in view too.
  const gutter = [...(cell.parentElement?.children ?? [])]
    .filter((element, index) => index === 0 || (element !== cell && getComputedStyle(element).position === 'sticky'))
    .reduce((sum, element) => sum + element.getBoundingClientRect().width, 0);
  return {
    top: box.top + header,
    left: box.left + gutter,
    bottom: box.top + scroller.clientHeight,
    right: box.left + scroller.clientWidth,
  };
}

/**
 * Whether any part of the cell is inside the free part of the scroll area.
 */
export function isCellVisible(scroller: HTMLElement, cell: HTMLElement) {
  const area = visibleArea(scroller, cell);
  const rect = cell.getBoundingClientRect();
  return rect.bottom >= area.top && rect.top <= area.bottom && rect.right >= area.left && rect.left <= area.right;
}

/**
 * Scrolls the grid so the cell, and the `keepInView` cells when they fit, are in view: as little as needed, or vertically centred
 * (`center`). Sideways it always moves as little as needed, so the columns left of the cell
 * (the description beside the frozen item numbers) stay in view as far as they fit.
 * Only the grid's own scroll area moves, so the page does not jump.
 */
export function scrollCellIntoView(
  scroller: HTMLElement | null,
  cell: HTMLElement | null,
  { center = false, keepInView = [] }: { center?: boolean; keepInView?: readonly HTMLElement[] } = {},
) {
  if (!scroller || !cell) return;
  const area = visibleArea(scroller, cell);
  const rect = cell.getBoundingClientRect();
  // Sideways, the related cells (`keepInView`) come along when they all fit beside the frozen columns.
  const spanned = [rect, ...keepInView.map((element) => element.getBoundingClientRect())];
  const spanLeft = Math.min(...spanned.map((box) => box.left));
  const spanRight = Math.max(...spanned.map((box) => box.right));
  const fits = spanRight - spanLeft <= area.right - area.left;
  const delta = (start: number, end: number, areaStart: number, areaEnd: number, centred = false) => {
    if (centred) return (start + end) / 2 - (areaStart + areaEnd) / 2;
    if (start < areaStart) return start - areaStart;
    if (end > areaEnd) return Math.min(end - areaEnd, start - areaStart);
    return 0;
  };
  const dy = delta(rect.top, rect.bottom, area.top, area.bottom, center);
  const dx = fits ? delta(spanLeft, spanRight, area.left, area.right) : delta(rect.left, rect.right, area.left, area.right);
  if (dy) scroller.scrollTop += dy;
  if (dx) scroller.scrollLeft += dx;
}

/** Whether the user asked for reduced motion (here or in the operating system). */
export { prefersReducedMotion } from '../../../app/accessibility.ts';
