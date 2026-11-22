import { describe, expect, it } from 'vitest';
import { extractionFacts, gaebFormatLabel, gaebPhaseLabel, isGaeb } from './gaebFacts.ts';

const GAEB_XML = {
  gaeb_version: '3.2',
  gaeb_phase: '83',
  gaeb_dp: '83',
  gaeb_schema: 'GAEB_DA_XML_83_3.2_2013-10.xsd',
  gaeb_schema_sha256: 'ab12cd34',
  gaeb_boq_id: 'LV-7',
  project: 'Neubau Pumpwerk',
  currency: 'EUR',
};

describe('gaebFormatLabel and gaebPhaseLabel', () => {
  it('names DA XML versions and GAEB 90', () => {
    expect(gaebFormatLabel('3.2')).toBe('GAEB DA XML 3.2');
    expect(gaebFormatLabel('90')).toBe('GAEB 90');
    expect(gaebFormatLabel(null)).toBeNull();
  });

  it('gives each phase its German name and keeps an unknown code as it is', () => {
    expect(gaebPhaseLabel('81')).toBe('81 Leistungsbeschreibung (bill exchange)');
    expect(gaebPhaseLabel('83')).toBe('83 Angebotsaufforderung (call for bids)');
    expect(gaebPhaseLabel('84')).toBe('84 Angebotsabgabe (bid)');
    expect(gaebPhaseLabel('86')).toBe('86 Auftragserteilung (contract award)');
    expect(gaebPhaseLabel('85')).toBe('85');
    expect(gaebPhaseLabel(undefined)).toBeNull();
  });
});

describe('isGaeb', () => {
  it('tells a GAEB file from any other', () => {
    expect(isGaeb({ gaeb_version: '90' })).toBe(true);
    expect(isGaeb({ encoding: 'utf-8' })).toBe(false);
    expect(isGaeb(undefined)).toBe(false);
  });
});

describe('extractionFacts', () => {
  it('lists the GAEB facts in order with their labels', () => {
    const { gaeb, other } = extractionFacts(GAEB_XML);
    expect(other).toEqual([]);
    expect(gaeb!.map((fact) => [fact.label, fact.value])).toEqual([
      ['Format', 'GAEB DA XML 3.2'],
      ['Exchange phase', '83 Angebotsaufforderung (call for bids)'],
      ['Schema', 'GAEB_DA_XML_83_3.2_2013-10.xsd'],
      ['Schema SHA-256', 'ab12cd34'],
      ['Project', 'Neubau Pumpwerk'],
      ['Bill of quantities id', 'LV-7'],
      ['Currency', 'EUR'],
    ]);
    expect(gaeb!.find((fact) => fact.label === 'Schema SHA-256')!.mono).toBe(true);
  });

  it('shows the data phase only when it says more than the phase, and every other key humanized', () => {
    const { gaeb } = extractionFacts({
      ...GAEB_XML,
      gaeb_phase: '84',
      gaeb_dp: '84Z',
      encoding: 'cp850',
      gaeb_items_total: 1204,
      price_components_shown: false,
      format: 'odd',
    });
    const labels = Object.fromEntries(gaeb!.map((fact) => [fact.label, fact.value]));
    expect(labels['Data phase (DP)']).toBe('84Z');
    expect(labels['Text encoding']).toBe('cp850');
    expect(labels['Gaeb items total']).toBe((1204).toLocaleString());
    expect(labels['Price components shown']).toBe('No');
    // A key whose humanized name is taken keeps its own key in the label.
    expect(labels['Format (format)']).toBe('odd');
    expect(new Set(gaeb!.map((fact) => fact.label)).size).toBe(gaeb!.length);
  });

  it('keeps a reported key without a value as empty and leaves absent keys out', () => {
    const { gaeb } = extractionFacts({ gaeb_version: '90', gaeb_phase: '86', gaeb_schema: null, project: null });
    expect(gaeb!.map((fact) => [fact.label, fact.value])).toEqual([
      ['Format', 'GAEB 90'],
      ['Exchange phase', '86 Auftragserteilung (contract award)'],
      ['Schema', null],
      ['Project', null],
    ]);
  });

  it('gives no GAEB facts for another file and lists its details as reading facts', () => {
    const { gaeb, other } = extractionFacts({ encoding: 'utf-8', delimiter: 'semicolon', records: 12 });
    expect(gaeb).toBeNull();
    expect(other.map((fact) => [fact.label, fact.value])).toEqual([
      ['Text encoding', 'utf-8'],
      ['Delimiter', 'semicolon'],
      ['Records', '12'],
    ]);
    expect(extractionFacts(undefined)).toEqual({ gaeb: null, other: [] });
  });
});
