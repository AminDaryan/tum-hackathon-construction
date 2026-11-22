/**
 * The sheet box's fixed parts, shared by the table view and the PDF view so that switching
 * between them never changes the box's size.
 */

/** The scrolling area under the cell bar: the grid, or the PDF page. */
export const SHEET_SCROLLER = 'h-[clamp(320px,56dvh,640px)] overflow-auto';

/** The same area in full screen, where it takes all the height the cell bar and footer leave. */
export const SHEET_SCROLLER_FILL = 'min-h-0 flex-1 overflow-auto';

/** The footer: the save line and row paging, or the PDF's status and page paging. */
export const SHEET_FOOTER = 'flex min-h-12 flex-wrap items-center justify-between border-t border-hairline';

/** The arithmetic of a priced row: a reveal keeps these cells in view together with its cell. */
export const ARITHMETIC_FIELDS: ReadonlySet<string> = new Set(['quantity', 'unit_price', 'line_total']);

/** The scroll area's width from which the description is frozen too; below it only the item numbers. */
export const FREEZE_DESCRIPTION_MIN_WIDTH = 760;

/** Where the frozen columns sit and how wide they are: the item numbers 96 px, the description 160 px. */
export const FROZEN_COLUMN = Object.freeze({
  item: 'left-12 w-24 min-w-24 max-w-24',
  description: 'left-36 w-40 min-w-40 max-w-40',
});
