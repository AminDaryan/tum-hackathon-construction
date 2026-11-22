import type { BoundingBox } from '../../../services/apiTypes.ts';

/** A text item of PDF.js (`page.getTextContent().items`); marked content has no `str`. */
export interface PdfTextItem {
  str?: string;
  /** [a, b, c, d, x, y] */
  transform: number[];
  width: number;
  height: number;
}

/** A region in PDF coordinates (bottom-left origin). */
export interface PdfBox {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

// Canonical extraction boxes have a top-left origin; PDF.js transforms bottom-left PDF points.
// Pixel boxes have no DPI in the API contract, so do not guess their scale.
export function extractedPdfBox(
  bbox: BoundingBox | null | undefined,
  page: { pageNumber: number; view: number[] },
): PdfBox | null {
  if (!bbox || bbox.page_number !== page.pageNumber || !['pt', 'normalized'].includes(bbox.unit)) return null;
  const [left, bottom, right, top] = page.view;
  const sx = bbox.unit === 'normalized' ? right - left : 1;
  const sy = bbox.unit === 'normalized' ? top - bottom : 1;
  return { left: left + bbox.x0 * sx, right: left + bbox.x1 * sx, top: top - bbox.y0 * sy, bottom: top - bbox.y1 * sy };
}
