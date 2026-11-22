import { SearchField } from '../../components/Field.tsx';
import { Select } from '../../components/Select.tsx';
import { t } from '../../i18n/messages.ts';
import { KINDS, PHASES } from './clarificationModel.ts';
import { STATUS_FILTERS, type ClarificationFilters } from './clarificationFilters.ts';

interface ClarificationFilterBarProps {
  filters: ClarificationFilters;
  onChange: (filters: ClarificationFilters) => void;
}

/** Above the clarifications table: the search, then the phase, type, status and due filters. */
export function ClarificationFilterBar({ filters, onChange }: ClarificationFilterBarProps) {
  const change = (next: Partial<ClarificationFilters>) => onChange({ ...filters, ...next });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchField
        label={t('Search clarifications')}
        placeholder={t('Search clarifications')}
        autoComplete="off"
        value={filters.search}
        onChange={(search) => change({ search })}
        className="min-w-48 max-w-sm flex-1"
      />
      <Select
        label={t('Phase')}
        hideLabel
        value={filters.phase}
        // Each select offers only the values of its filter.
        onChange={(phase) => change({ phase: phase as ClarificationFilters['phase'] })}
        options={[{ value: '', label: t('All phases') }, ...PHASES.map((option) => ({ value: option.value, label: t(option.label) }))]}
      />
      <Select
        label={t('Type')}
        hideLabel
        value={filters.kind}
        onChange={(kind) => change({ kind: kind as ClarificationFilters['kind'] })}
        options={[{ value: '', label: t('All types') }, ...KINDS.map((kind) => ({ value: kind.value, label: t(kind.label) }))]}
      />
      <Select
        label={t('Status')}
        hideLabel
        value={filters.status}
        onChange={(status) => change({ status: status as ClarificationFilters['status'] })}
        options={[{ value: '', label: t('All statuses') }, ...STATUS_FILTERS.map((option) => ({ value: option.value, label: t(option.label) }))]}
      />
      <Select
        label={t('Due')}
        hideLabel
        value={filters.due}
        onChange={(due) => change({ due: due as ClarificationFilters['due'] })}
        options={[
          { value: '', label: t('Any due date') },
          { value: 'this_week', label: t('Due this week') },
        ]}
      />
    </div>
  );
}
