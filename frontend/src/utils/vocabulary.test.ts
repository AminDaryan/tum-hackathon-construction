import { describe, expect, it } from 'vitest';
import {
  FINDING_CATEGORY_DESCRIPTIONS,
  FINDING_CATEGORY_LABELS,
  FINDING_CATEGORY_ORDER,
  findingCategoryKey,
  NO_FINDING_CATEGORY,
  PARSE_STATUS_LABELS,
  ROW_KIND_LABELS,
  STATUS_VOCABULARY,
  VALUE_MARKER_LABELS,
} from './vocabulary.ts';

// The values the backend sends (backend/app/models: RowKind, ParseStatus, ValueMarker,
// DetectorExecutionStatus, RunStatus, DetectorRunReport.limit_reached, FindingCategoryKey). A
// value without a label would still render (humanized), but without its wording and tone.
describe('vocabulary', () => {
  it.each([
    [ROW_KIND_LABELS, ['item', 'section', 'subtotal', 'grand_total', 'tax', 'gross_total', 'adjustment', 'carry_forward', 'summary_line', 'text', 'blank']],
    [PARSE_STATUS_LABELS, ['exact', 'inferred', 'ambiguous', 'failed', 'unavailable', 'not_applicable', 'marker']],
    [VALUE_MARKER_LABELS, ['nil', 'included_elsewhere', 'not_applicable', 'by_others', 'rate_only', 'lump_sum', 'not_offered']],
    [STATUS_VOCABULARY.detector, ['completed', 'skipped', 'failed', 'stopped']],
    [STATUS_VOCABULARY.run, ['queued', 'running', 'completed', 'completed_with_errors', 'failed']],
    [FINDING_CATEGORY_LABELS, ['error', 'omission', 'inconsistency', 'ambiguity', 'risk', 'change_order_opportunity', 'none']],
    [FINDING_CATEGORY_DESCRIPTIONS, ['error', 'omission', 'inconsistency', 'ambiguity', 'risk', 'change_order_opportunity', 'none']],
  ])('labels every value the backend sends (%#)', (labels, values) => {
    expect(Object.keys(labels).sort()).toEqual([...values].sort());
  });
});

describe('finding categories', () => {
  it('use the approved names, in the order of the risk report, with reading the file last', () => {
    expect([...FINDING_CATEGORY_ORDER, NO_FINDING_CATEGORY].map((key) => FINDING_CATEGORY_LABELS[key as keyof typeof FINDING_CATEGORY_LABELS])).toEqual([
      'Error',
      'Inconsistency',
      'Omission',
      'Ambiguity',
      'Risk',
      'Change order opportunity',
      'Reading the file',
    ]);
  });

  it('file a finding without a category under none', () => {
    expect(findingCategoryKey(null)).toBe(NO_FINDING_CATEGORY);
    expect(findingCategoryKey(undefined)).toBe('none');
    expect(findingCategoryKey('change_order_opportunity')).toBe('change_order_opportunity');
  });
});
