/**
 * Which method a check uses, in the words of the Requirements tab: rules (if-else),
 * statistics, machine learning or a language model. Rule-based text checks of category
 * "semantic" count as rules; the unit-fit and section-fit checks of plan step B3 compare
 * positions by text similarity, so they count as statistics. A language-model check has an id
 * starting with `llm.`.
 */
import { msg, t } from '../../i18n/messages.ts';

const METHOD_LABELS: Readonly<Record<string, string>> = Object.freeze({
  rule: msg('Rule (if-else)'),
  statistics: msg('Statistics'),
  machine_learning: msg('Machine learning'),
  llm: msg('Language model (LLM)'),
});

/** Text-similarity checks of category "semantic": they compare positions, they apply no rule. */
const SIMILARITY_CHECKS = new Set(['semantic.unit_fit', 'semantic.section_fit']);

const CATEGORY_METHODS: Readonly<Record<string, string>> = Object.freeze({
  deterministic: 'rule',
  domain: 'rule',
  semantic: 'rule',
  statistical: 'statistics',
  machine_learning: 'machine_learning',
});

/**
 * @param category the catalogue's `category` of the detector
 * @returns a key of METHOD_LABELS, or the category itself when it is none of them
 */
export function methodOf(detectorId: string, category: string | undefined | null): string {
  if (detectorId?.startsWith('llm.')) return 'llm';
  if (SIMILARITY_CHECKS.has(detectorId)) return 'statistics';
  if (category && CATEGORY_METHODS[category]) return CATEGORY_METHODS[category];
  if (!category) return detectorId?.startsWith('statistical.') ? 'statistics' : 'rule';
  return category;
}

/**
 * @returns e.g. "Rule (if-else)"
 */
export function methodLabel(detectorId: string, category: string | undefined | null): string {
  const method = methodOf(detectorId, category);
  return t(METHOD_LABELS[method]) ?? method.replaceAll('_', ' ').replace(/^./, (c) => c.toUpperCase());
}
