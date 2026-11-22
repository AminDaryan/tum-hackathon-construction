import { describe, expect, it } from 'vitest';
import { extractedPdfBox } from './pdfBoxes.ts';
import type { BoundingBox } from '../../../services/apiTypes.ts';

describe('extraction boxes on a PDF page', () => {
  it('converts extraction coordinates without flipping curated PDF anchors or guessing OCR DPI', () => {
    const page = { pageNumber: 3, view: [10, 20, 610, 820] };
    const bbox: BoundingBox = { page_number: 3, x0: 30, y0: 70, x1: 150, y1: 90, unit: 'pt' };
    expect(extractedPdfBox(bbox, page)).toEqual({ left: 40, right: 160, top: 750, bottom: 730 });
    expect(extractedPdfBox({ ...bbox, x0: .1, x1: .3, y0: .2, y1: .4, unit: 'normalized' }, page)).toEqual({ left: 70, right: 190, top: 660, bottom: 500 });
    expect(extractedPdfBox({ ...bbox, unit: 'px' }, page)).toBeNull();
    expect(extractedPdfBox({ ...bbox, page_number: 2 }, page)).toBeNull();
  });
});
