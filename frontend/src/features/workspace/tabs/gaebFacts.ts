/**
 * Labels for what the reader reported about a file (`dataset.extraction.details`), with the
 * GAEB facts named the way a Korrektor knows them: the format and version, the exchange phase
 * with its German name, the schema, project, bill of quantities id, currency and encoding.
 * Every other key is listed under its humanized name, so nothing the reader reported is hidden.
 */
import { msg, t } from '../../../i18n/messages.ts';
import { formatCount } from '../../../utils/format.ts';
import { humanize } from '../../../utils/vocabulary.ts';

/** GAEB exchange phases (Datenaustauschphasen) the app reads (ADR 0009, 0010). */
const GAEB_PHASES: Readonly<Record<string, string>> = Object.freeze({
  81: msg('Leistungsbeschreibung (bill exchange)'),
  83: msg('Angebotsaufforderung (call for bids)'),
  84: msg('Angebotsabgabe (bid)'),
  86: msg('Auftragserteilung (contract award)'),
});

/** Labels of the detail keys, in display order. */
const DETAIL_LABELS: Readonly<Record<string, string>> = Object.freeze({
  gaeb_version: msg('Format'),
  gaeb_phase: msg('Exchange phase'),
  gaeb_dp: msg('Data phase (DP)'),
  gaeb_schema: msg('Schema'),
  gaeb_schema_sha256: msg('Schema SHA-256'),
  project: msg('Project'),
  gaeb_boq_id: msg('Bill of quantities id'),
  currency: msg('Currency'),
  encoding: msg('Text encoding'),
});

const MONO_KEYS = Object.freeze(new Set(['gaeb_schema', 'gaeb_schema_sha256', 'gaeb_boq_id']));

/**
 * @param version `gaeb_version`, e.g. "3.2" or "90"
 * @returns "GAEB DA XML 3.2" or "GAEB 90"
 */
export function gaebFormatLabel(version: unknown): string | null {
  if (version === null || version === undefined || version === '') return null;
  const text = String(version);
  return text === '90' ? 'GAEB 90' : `GAEB DA XML ${text}`;
}

/**
 * @param phase `gaeb_phase`, e.g. "86"
 * @returns "86 Auftragserteilung (contract award)", or an unknown code as it is
 */
export function gaebPhaseLabel(phase: unknown): string | null {
  if (phase === null || phase === undefined || phase === '') return null;
  const code = String(phase);
  return GAEB_PHASES[code] ? `${code} ${t(GAEB_PHASES[code])}` : code;
}

/**
 * @returns whether the file was read as a GAEB bill
 */
export function isGaeb(details: Record<string, unknown> | null | undefined): boolean {
  return Boolean(details?.gaeb_version);
}

function displayValue(key: string, value: unknown): string | null {
  if (value === null || value === undefined || value === '') return null;
  if (key === 'gaeb_version') return gaebFormatLabel(value);
  if (key === 'gaeb_phase') return gaebPhaseLabel(value);
  if (typeof value === 'boolean') return value ? t('Yes') : t('No');
  if (typeof value === 'number' && Number.isInteger(value)) return formatCount(value);
  return String(value);
}

/**
 * Facts for a `KeyValueList`: the known keys first in their order, then every other key under
 * its humanized name. A key that is absent is left out; a key reported without a value shows as
 * empty. The data phase is listed only when it says more than the exchange phase ("84Z").
 */
/** One line of facts about the file. */
interface ExtractionFact {
  label: string;
  value: string | null;
  mono?: boolean;
}

function factsOf(details: Record<string, unknown>): ExtractionFact[] {
  const known = Object.keys(DETAIL_LABELS).filter((key) => key in details);
  const others = Object.keys(details).filter((key) => !(key in DETAIL_LABELS));
  const used = new Set<string>();
  const facts: ExtractionFact[] = [];
  for (const key of [...known, ...others]) {
    if (key === 'gaeb_dp' && String(details.gaeb_dp ?? '') === String(details.gaeb_phase ?? '')) continue;
    let label = DETAIL_LABELS[key] ? t(DETAIL_LABELS[key]) : humanize(key);
    if (used.has(label)) label = `${label} (${key})`;
    used.add(label);
    facts.push({ label, value: displayValue(key, details[key]), ...(MONO_KEYS.has(key) && { mono: true }) });
  }
  return facts;
}

/**
 * What the reader reported, split for the Properties tab: the GAEB facts of a GAEB bill (with
 * any other key the reader added), or, for any other file, its details as reading facts.
 *
 * @param details `dataset.extraction.details`
 */
export function extractionFacts(details: Record<string, unknown> | null | undefined): {
  gaeb: ExtractionFact[] | null;
  other: ExtractionFact[];
} {
  const facts = factsOf(details ?? {});
  return isGaeb(details) ? { gaeb: facts, other: [] } : { gaeb: null, other: facts };
}
