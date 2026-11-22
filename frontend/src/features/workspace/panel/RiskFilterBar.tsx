import { Info, SlidersHorizontal } from 'lucide-react';
import { useId, useState } from 'react';
import { IconButton } from '../../../components/IconButton.tsx';
import { Button } from '../../../components/Button.tsx';
import { Checkbox } from '../../../components/Checkbox.tsx';
import { SearchField } from '../../../components/Field.tsx';
import { Chip } from '../../../components/FilterChips.tsx';
import { Select } from '../../../components/Select.tsx';
import { msg, t } from '../../../i18n/messages.ts';
import { formatCount } from '../../../utils/format.ts';
import { SEVERITY_META } from '../../../utils/vocabulary.ts';
import {
  DEFAULT_RISK_FILTERS,
  hasRiskFilters,
  MONEY_FILTERS,
  RISK_STATUS_FILTERS,
  type RiskFilters,
} from '../../risks/riskFilters.ts';
import { classificationLabel } from '../../risks/riskModel.ts';

/** The orders the risk report can be read in (`getRiskReport`'s `sortBy`). */
export type RiskSort = 'priority' | 'price_impact' | 'confidence';

const RISK_SORTS = Object.freeze<{ value: RiskSort; label: string }[]>([
  Object.freeze({ value: 'priority', label: msg('Priority') }),
  Object.freeze({ value: 'price_impact', label: msg('Money at stake') }),
  Object.freeze({ value: 'confidence', label: msg('Evidence certainty') }),
]);

function anyOption(label: string) {
  return { value: '', label };
}

interface RiskFilterBarProps {
  filters: RiskFilters;
  onChange: (filters: RiskFilters) => void;
  counts: Record<string, number>;
  options: {
    tiers: string[];
    classifications: string[];
    types: string[];
    sections: string[];
  };
  sort: RiskSort;
  onSortChange: (sort: RiskSort) => void;
  recordCount?: number;
  /** Whether "Assigned to me" is offered: only once this browser has a reviewer name. */
  canFilterMine?: boolean;
}

const ASSIGNEE_SCOPES = Object.freeze<{ value: RiskFilters['assignee']; label: string }[]>([
  Object.freeze({ value: '', label: msg('Everyone') }),
  Object.freeze({ value: 'me', label: msg('Assigned to me') }),
  Object.freeze({ value: 'none', label: msg('Unassigned') }),
]);

/** How many of the filters behind the Filters button are set. */
function moreFilterCount(filters: RiskFilters, sort: RiskSort): number {
  return [
    filters.tier,
    filters.classification,
    filters.type,
    filters.section,
    filters.money !== 'any',
    filters.overdueOnly,
    filters.includeRecord,
    sort !== 'priority',
  ].filter(Boolean).length;
}

/**
 * The search, whose risks to show (everyone's, the reviewer's own, unassigned), the status chips,
 * and behind a Filters button the filter menus, the sort and the record switch. Each filter
 * combines with the others; "Clear filters" returns to every risk of the main list.
 */
export function RiskFilterBar({
  filters,
  onChange,
  counts,
  options,
  sort,
  onSortChange,
  recordCount = 0,
  canFilterMine = true,
}: RiskFilterBarProps) {
  const change = (next: Partial<RiskFilters>) => onChange({ ...filters, ...next });
  const more = moreFilterCount(filters, sort);
  const [open, setOpen] = useState(more > 0);
  const panelId = useId();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-end gap-2">
        <Select
          label={t('Assigned to')}
          hideLabel
          className="w-40"
          value={filters.assignee ?? ''}
          // The select offers only ASSIGNEE_SCOPES.
          onChange={(assignee) => change({ assignee: assignee as RiskFilters['assignee'] })}
          options={ASSIGNEE_SCOPES.filter((option) => canFilterMine || option.value !== 'me').map((option) => ({ ...option, label: t(option.label) }))}
        />
        <div className="min-w-40 flex-1">
          <SearchField
            label={t('Search the risks')}
            value={filters.search}
            placeholder={t('Search risks')}
            autoComplete="off"
            onChange={(search) => change({ search })}
          />
        </div>
        <Button icon={SlidersHorizontal} aria-expanded={open} aria-controls={panelId} onPress={() => setOpen(!open)}>
          {more > 0 ? t('Filters ({count})', { count: formatCount(more) }) : t('Filters')}
        </Button>
      </div>

      <div role="group" aria-label={t('Status')} className="flex flex-wrap items-center gap-1.5">
        {RISK_STATUS_FILTERS.map((option) => (
          <div key={option.value} className="inline-flex items-center">
            <Chip
              selected={option.value === filters.status}
              onChange={() => change({ status: option.value })}
              count={counts[option.value]}
            >
              {t(option.label)}
            </Chip>
            {option.value === 'in_review' && <IconButton icon={Info} label={t('Risks awaiting clarification, within the current filters and assignee selection. A risk may group several findings.')} />}
          </div>
        ))}
      </div>

      {open && (
        <div id={panelId} className="space-y-2 rounded-md border border-hairline bg-surface-muted p-3">
          <div className="grid grid-cols-2 gap-x-3 gap-y-2 @lg:grid-cols-3">
            <Select
              label={t('Priority')}
              value={filters.tier}
              onChange={(tier) => change({ tier })}
              options={[anyOption(t('Any')), ...options.tiers.map((tier) => ({ value: tier, label: t(SEVERITY_META[tier]?.label ?? tier) }))]}
            />
            <Select
              label={t('Classification')}
              value={filters.classification}
              onChange={(classification) => change({ classification })}
              options={[
                anyOption(t('Any')),
                ...options.classifications.map((classification) => ({ value: classification, label: classificationLabel(classification) })),
              ]}
            />
            <Select
              label={t('Type')}
              value={filters.type}
              onChange={(type) => change({ type })}
              options={[anyOption(t('Any')), ...options.types.map((type) => ({ value: type, label: type }))]}
            />
            <Select
              label={t('Section')}
              value={filters.section}
              onChange={(section) => change({ section })}
              options={[anyOption(t('Any')), ...options.sections.map((section) => ({ value: section, label: t('Section {section}', { section }) }))]}
            />
            <Select
              label={t('Money at stake')}
              value={filters.money}
              // The select offers only MONEY_FILTERS.
              onChange={(money) => change({ money: money as RiskFilters['money'] })}
              options={MONEY_FILTERS.map((option) => ({ value: option.value, label: t(option.label) }))}
            />
            <Select
              label={t('Sort by')}
              value={sort}
              // The select offers only RISK_SORTS.
              onChange={(value) => onSortChange(value as RiskSort)}
              options={RISK_SORTS.map((option) => ({ ...option, label: t(option.label) }))}
            />
          </div>
          <div className="flex flex-wrap gap-x-4">
            <Checkbox checked={filters.overdueOnly ?? false} onChange={(overdueOnly) => change({ overdueOnly })}>
              {t('Overdue tasks only')}
            </Checkbox>
            {recordCount > 0 && (
              <Checkbox checked={filters.includeRecord} onChange={(includeRecord) => change({ includeRecord })}>
                {recordCount === 1
                  ? t('Show {count} kept reminder', { count: formatCount(recordCount) })
                  : t('Show {count} kept reminders', { count: formatCount(recordCount) })}
              </Checkbox>
            )}
          </div>
        </div>
      )}

      {(hasRiskFilters(filters) || filters.status !== DEFAULT_RISK_FILTERS.status) && (
        <Button variant="ghost" onPress={() => onChange({ ...DEFAULT_RISK_FILTERS, includeRecord: filters.includeRecord })}>
          {t('Clear filters')}
        </Button>
      )}
    </div>
  );
}
