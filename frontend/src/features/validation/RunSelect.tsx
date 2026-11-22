import { Select } from '../../components/Select.tsx';
import { t } from '../../i18n/messages.ts';
import { formatDateTime, pluralize } from '../../utils/format.ts';
import { statusMeta } from '../../utils/vocabulary.ts';
import type { ValidationRunSummary } from '../../services/apiTypes.ts';

function runLabel(run: ValidationRunSummary, index: number) {
  const parts = [
    formatDateTime(run.started_at),
    t(statusMeta('run', run.status).label),
    pluralize(run.issue_count ?? 0, 'issue'),
  ];
  const label = parts.join('; ');
  return index === 0 ? t('{run} (latest)', { run: label }) : label;
}

interface RunSelectProps {
  runs: ValidationRunSummary[];
  value?: string;
  onChange: (runId: string) => void;
  className?: string;
}

/**
 * Chooses a validation run of the active dataset. A run id from the URL that is not in the list
 * (for example a run of another document) stays selectable so deep links keep working.
 */
export function RunSelect({ runs, value, onChange, className }: RunSelectProps) {
  const options = runs.map((run, index) => ({ value: run.run_id, label: runLabel(run, index) }));
  if (value && !runs.some((run) => run.run_id === value)) {
    options.unshift({ value, label: t('Run {id}', { id: value }) });
  }
  if (!options.length) {
    return null;
  }
  return (
    <Select
      label={t('Validation run')}
      value={value ?? options[0].value}
      options={options}
      onChange={onChange}
      className={className ?? 'w-full sm:w-96'}
    />
  );
}
