import { describe, expect, it } from 'vitest';
import { isAcceptedFile, rejectionMessage } from './uploadRules.ts';

describe('accepted files', () => {
  it('accepts printed bills as PDF, Word documents and GAEB files in any case, and refuses other types', () => {
    for (const name of ['LV 03.pdf', 'Angebot.PDF', 'bill.x86', 'LV.D83', 'bill.xlsx', 'bill.csv', 'LV.docx', 'LV.DOCX']) {
      expect(isAcceptedFile({ name })).toBe(true);
    }
    for (const name of ['scan.png', 'LV.doc', 'book.xls', 'noextension']) {
      expect(isAcceptedFile({ name })).toBe(false);
    }
  });

  it('tells a legacy Word file to be saved as .docx', () => {
    expect(rejectionMessage({ name: 'LV alt.doc' })).toBe(
      '“LV alt.doc” is a legacy Word file (.doc). Save it as .docx (Word: File > Save As > Word Document) or as PDF, and upload that.',
    );
    expect(rejectionMessage({ name: 'scan.png' })).toBe(
      '“scan.png” is not a supported file type. Supported: XLSX, CSV, TSV, TXT, PDF, Word (.docx), and GAEB (.x81, .x83, .x84, .x86, .d81, .d83, .d84, .d86).',
    );
  });
});
