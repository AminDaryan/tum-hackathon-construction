import { describe, expect, it } from 'vitest';
import { draftText, MAILTO_MAX_LENGTH, mailtoLink, riskEmailDraft, risksEmailDraft } from './emailDraft.ts';
import type { PriceFacts } from '../risks/pricing.ts';
import { riskReport } from '../../test/fixtures.ts';
import type { Risk } from '../../services/apiTypes.ts';

const [base] = riskReport.risks;
const risk: Risk = {
  ...base,
  risk_id: 'risk_a',
  title: 'Line total of 02.010 does not add up',
  risk_name: 'Arithmetic error',
  why_risk_here: 'Found by a rule: the line total is 25.00 EUR above quantity times unit price.',
  positions: [{ label: '02.010', item_code: '02.010', table_id: 't', row_id: 'r', cells: [] }],
  positions_total: 1,
  money: { ...base.money, kind: 'exact', amount: '25.00', currency: 'EUR' },
  question: null,
  missing_information: [],
};

const facts: PriceFacts = {
  rowId: 'r',
  tableId: 't',
  itemCode: '02.010',
  description: 'Concrete C25/30 for foundations',
  quantity: '12.5',
  unit: 'm3',
  unitPrice: '80.00',
  lineTotal: '1025.00',
  discount: null,
  columns: {},
};

describe('mailtoLink', () => {
  it('percent-encodes subject and body as UTF-8, with CRLF line breaks and %20 for spaces', () => {
    const { href, complete } = mailtoLink({
      to: 'a.b@example.com; c+d@example.com',
      subject: 'Größe & Preis?',
      body: 'Line one\nLine two',
    });
    expect(complete).toBe(true);
    expect(href).toBe(
      'mailto:a.b@example.com,c%2Bd@example.com?subject=Gr%C3%B6%C3%9Fe%20%26%20Preis%3F&body=Line%20one%0D%0ALine%20two',
    );
  });

  it('leaves out the body, not the subject, when the link would be too long', () => {
    const body = 'x'.repeat(MAILTO_MAX_LENGTH);
    const { href, complete } = mailtoLink({ to: '', subject: 'Short', body });
    expect(complete).toBe(false);
    expect(href).toBe('mailto:?subject=Short');
  });

  it('keeps a body that fits exactly at the limit', () => {
    const prefix = 'mailto:?subject=S&body='.length;
    const { complete } = mailtoLink({ to: '', subject: 'S', body: 'y'.repeat(MAILTO_MAX_LENGTH - prefix) });
    expect(complete).toBe(true);
  });
});

describe('riskEmailDraft', () => {
  it('names the bill and position as the client knows them, never the bidder’s prices or the file row', () => {
    const draft = riskEmailDraft({
      risk,
      title: 'Arithmetic error',
      facts: { ...facts, discount: '5' },
      billName: 'Sample school extension.xlsx',
    });
    expect(draft.to).toBe('');
    expect(draft.subject).toBe('Question on Sample school extension.xlsx: Arithmetic error, position 02.010');
    expect(draft.body).toContain('the bill of quantities "Sample school extension.xlsx"');
    expect(draft.body).toContain('Position: 02.010 Concrete C25/30 for foundations\nQuantity: 12.5 m3\n\nArithmetic error\n');
    for (const text of ['Unit price', 'Line total', 'Discount', 'Difference', 'EUR', '80.00', '1,025.00', 'Row in the file']) {
      expect(draft.body).not.toContain(text);
    }
    expect(draft.body).toContain('confirm it or send a corrected version');
    expect(draft.body).not.toMatch(/\u00B7/);
  });

  it('gives the explanation of a risk that is not about prices, without the method prefix', () => {
    const draft = riskEmailDraft({ risk: { ...risk, category: 'unclear_description', why_risk_here: 'Found by a rule: the long text names C25/30.' }, title: 'Arithmetic error' });
    expect(draft.body).toContain('The long text names C25/30.');
    expect(draft.body).not.toContain('Found by');
  });

  it('names the title once when the full title starts with the short one', () => {
    const draft = riskEmailDraft({
      risk: { ...risk, category: 'unclear_description', title: 'Conflicting concrete grades: short text 20/25, long text 25/30' },
      title: 'Conflicting concrete grades',
    });
    expect(draft.body).toContain('\nConflicting concrete grades: short text 20/25, long text 25/30\n');
    expect(draft.body).not.toContain('Conflicting concrete grades: Conflicting concrete grades');
  });

  it('uses the risk question and lists missing information', () => {
    const draft = riskEmailDraft({
      risk: { ...risk, question: 'Which soil class applies?', missing_information: ['Soil report'], money: { ...risk.money, kind: 'unknown', amount: null } },
      title: 'Unclear soil class',
    });
    expect(draft.body).toContain('Which soil class applies?');
    expect(draft.body).toContain('To settle it, we are missing:\n- Soil report');
    expect(draft.body).not.toContain('confirm it or send');
    expect(draft.body).not.toContain('Difference');
  });
});

describe('risksEmailDraft', () => {
  it('numbers one point per risk with its positions and question', () => {
    const other = { ...risk, risk_id: 'risk_b', title: 'Soil class not stated', why_risk_here: '', question: 'Which class?' };
    const draft = risksEmailDraft({ risks: [risk, other], titleOf: (r) => r.title, billName: 'Bill.xlsx' });
    expect(draft.subject).toBe('Questions on Bill.xlsx (2 points)');
    expect(draft.body).toContain('1. Line total of 02.010 does not add up\n   Positions: 02.010');
    expect(draft.body).toContain('2. Soil class not stated\n   Positions: 02.010\n   Question: Which class?');
  });
});

describe('draftText', () => {
  it('puts recipient and subject above the body', () => {
    expect(draftText({ to: 'x@example.com', subject: 'S', body: 'B' })).toBe('To: x@example.com\nSubject: S\n\nB');
  });
});


describe('arithmetic confirmation questions', () => {
  // Both drafts reuse the backend question.
  it.each([
    '02.010: under the rule used in this check, the unit price prevails. Please confirm this basis for the line total.',
    '02.010: under the rule used in this check, the stated lump-sum amount prevails. Please confirm.',
    '02.010: the unit price prevails unless this position is a lump sum. Please confirm whether the exception applies.',
  ])('keeps the shared pricing question and hides bidder prices: %s', (question) => {
    const arithmetic = { ...risk, category: 'pricing', question };
    const single = riskEmailDraft({ risk: arithmetic, title: 'Arithmetic error', facts });
    const batch = risksEmailDraft({ risks: [arithmetic, { ...arithmetic, risk_id: 'risk_second' }], titleOf: () => 'Arithmetic error' });
    for (const draft of [single, batch]) {
      expect(draft.body).toContain(question);
      expect(draft.body).not.toMatch(/80\.00|1025|1,025|25\.00|VOB|§|Which value applies/);
    }
    expect(batch.body.split(question)).toHaveLength(3);
  });

  it('uses a supplied nonpricing corrected amount verbatim in single and batch drafts', () => {
    const question = '02.010: under the rule used in this check, the unit price prevails, so we interpret the line total as 987.65. Please confirm.';
    const arithmetic = { ...risk, category: 'other', question, why_risk_here: '' };
    for (const draft of [riskEmailDraft({ risk: arithmetic, facts }), risksEmailDraft({ risks: [arithmetic] })]) {
      expect(draft.body).toContain(question);
      expect(draft.body).not.toContain('1000.00');
    }
  });
});


it('keeps each confirmation with its own position after mixed risks are reordered', () => {
  // Reordering a batch must not swap its questions.
  const first = { ...risk, risk_id: 'zero', category: 'other', title: 'Zero total', why_risk_here: '', question: '09.700: the interpreted total is 0.00. Please confirm.' };
  const second = { ...risk, risk_id: 'lump', category: 'pricing', title: 'Lump sum', question: '02.010: the stated lump sum applies. Please confirm.' };
  const neutral = { ...risk, risk_id: 'neutral', category: 'unclear_description', title: 'Material grade', why_risk_here: '', question: 'Which grade applies?' };
  for (const ordered of [[first, neutral, second], [second, first, neutral]]) {
    const draft = risksEmailDraft({ risks: ordered, titleOf: (r) => r.title });
    const offsets = ordered.map((r) => draft.body.indexOf(r.question));
    expect(offsets).toEqual([...offsets].sort((a, b) => a - b));
    for (const r of ordered) expect(draft.body.split(r.question)).toHaveLength(2);
    expect(draft.body).not.toContain('25.00');
  }
});
