import { cx } from '../utils/classNames.ts';
import {
  FINDING_CATEGORY_DESCRIPTIONS,
  FINDING_CATEGORY_LABELS,
  findingCategoryKey,
  labelFor,
  NO_FINDING_CATEGORY,
} from '../utils/vocabulary.ts';
import { t } from '../i18n/messages.ts';

interface FindingCategoryProps {
  category?: string | null;
  describe?: boolean;
  className?: string;
}

/**
 * A finding's category as text ("Error", "Inconsistency", …), with its meaning as a tooltip or,
 * with `describe`, on a line below. A finding without a category is about reading the file and
 * reads "Reading the file", in quieter ink. Neutral ink on purpose: colour belongs to the
 * evidence class. The text size comes from the surrounding text.
 */
export function FindingCategory({ category, describe = false, className }: FindingCategoryProps) {
  const key = findingCategoryKey(category);
  const description = t(FINDING_CATEGORY_DESCRIPTIONS[key]);
  const label = (
    <span
      title={describe ? undefined : description}
      className={cx(key === NO_FINDING_CATEGORY ? 'text-ink-tertiary' : 'font-medium text-ink', className)}
    >
      {labelFor(FINDING_CATEGORY_LABELS, key)}
    </span>
  );
  if (!describe || !description) {
    return label;
  }
  return (
    <>
      {label}
      <span className="block text-caption text-ink-tertiary">{description}</span>
    </>
  );
}
