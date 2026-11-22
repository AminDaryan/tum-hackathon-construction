import { SearchField } from '../../components/Field.tsx';
import { Select } from '../../components/Select.tsx';
import { t } from '../../i18n/messages.ts';
import { PROJECT_STATUS } from './projectStatus.ts';
import type { ProjectFilters } from './projectFilters.ts';

interface ProjectFilterBarProps {
  filters: ProjectFilters;
  onChange: (filters: ProjectFilters) => void;
  /** the users assigned to any project, offered by the "Assigned to" filter */
  assignees: string[];
}

/**
 * Above the projects table: the search, and the status and assigned-user filters. "Assigned to"
 * is unavailable while no project has an assigned user.
 */
export function ProjectFilterBar({ filters, onChange, assignees }: ProjectFilterBarProps) {
  const change = (next: Partial<ProjectFilters>) => onChange({ ...filters, ...next });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <SearchField
        label={t('Search projects')}
        placeholder={t('Search projects')}
        autoComplete="off"
        value={filters.search}
        onChange={(search) => change({ search })}
        className="min-w-48 max-w-sm flex-1"
      />
      <Select
        label={t('Status')}
        hideLabel
        value={filters.status}
        // The select offers only the project statuses.
        onChange={(status) => change({ status: status as ProjectFilters['status'] })}
        options={[
          { value: '', label: t('All statuses') },
          ...Object.entries(PROJECT_STATUS).map(([value, meta]) => ({ value, label: t(meta.label) })),
        ]}
      />
      <Select
        label={t('Assigned to')}
        hideLabel
        value={filters.assignee}
        onChange={(assignee) => change({ assignee })}
        options={[{ value: '', label: t('All assignees') }, ...assignees.map((name) => ({ value: name, label: name }))]}
        disabled={assignees.length === 0}
      />
    </div>
  );
}
