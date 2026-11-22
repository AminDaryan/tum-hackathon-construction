import { SearchField } from '../../components/Field.tsx';
import { Select } from '../../components/Select.tsx';
import { t } from '../../i18n/messages.ts';
import { FILE_STATES, FILE_TYPES, type FileFilters } from './projectFileFilters.ts';

interface ProjectFileFilterBarProps {
  filters: FileFilters;
  onChange: (filters: FileFilters) => void;
}

/** Above a project's files table: the search by name, and the type and state filters. */
export function ProjectFileFilterBar({ filters, onChange }: ProjectFileFilterBarProps) {
  const change = (next: Partial<FileFilters>) => onChange({ ...filters, ...next });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchField
        label={t('Search files')}
        placeholder={t('Search files')}
        autoComplete="off"
        value={filters.search}
        onChange={(search) => change({ search })}
        className="min-w-48 max-w-sm flex-1"
      />
      <Select
        label={t('Type')}
        hideLabel
        value={filters.type}
        // The select offers only the file types.
        onChange={(type) => change({ type: type as FileFilters['type'] })}
        options={[{ value: '', label: t('All types') }, ...FILE_TYPES.map((option) => ({ ...option, label: t(option.label) }))]}
      />
      <Select
        label={t('State')}
        hideLabel
        value={filters.state}
        // The select offers only the states.
        onChange={(state) => change({ state: state as FileFilters['state'] })}
        options={[{ value: '', label: t('Any state') }, ...FILE_STATES.map((option) => ({ ...option, label: t(option.label) }))]}
      />
    </div>
  );
}
