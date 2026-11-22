import { ChevronDown } from 'lucide-react';
import { useState } from 'react';
import { Button as AriaButton, ListBox, Popover, Select as AriaSelect } from 'react-aria-components';
import { HIT_TARGET } from '../../components/hitTarget.ts';
import { OptionItem, POPOVER } from '../../components/Select.tsx';
import { t } from '../../i18n/messages.ts';
import { cx } from '../../utils/classNames.ts';

interface ProjectAssigneesSelectProps {
  /** the project's name, for the control's accessible name */
  projectName: string;
  /** the people assigned now */
  value: readonly string[];
  /** the people who can be assigned: the reviewers and everyone assigned to a project */
  people: readonly string[];
  onChange: (assignees: string[]) => void;
  /** nothing to change here (a viewer): the names alone */
  readOnly?: boolean;
  /** a change is being saved */
  disabled?: boolean;
}

/**
 * The people assigned to a project, in its row of the projects table: their names with an arrow,
 * which opens the people to tick or untick (React Aria Select with several chosen; it stays open
 * while ticking). Closing it saves the people ticked, in the order they are offered, once. A
 * press on it never opens the row. Read-only, or with nobody to offer, it is the names.
 */
export function ProjectAssigneesSelect({ projectName, value, people, onChange, readOnly = false, disabled = false }: ProjectAssigneesSelectProps) {
  // The people ticked while the list is open; saved when it closes.
  const [ticked, setTicked] = useState<string[] | null>(null);
  const offered = [...new Set([...people, ...value])].sort((a, b) => a.localeCompare(b, undefined, { sensitivity: 'base' }));
  const chosen = ticked ?? value;
  const names = chosen.length ? chosen.join(', ') : null;
  if (readOnly || offered.length === 0) return <span className="text-ink-secondary">{names ?? '—'}</span>;
  return (
    <AriaSelect
      selectionMode="multiple"
      aria-label={t('People assigned to {name}', { name: projectName })}
      value={chosen}
      onChange={(keys) => {
        const picked = new Set(keys.map(String));
        setTicked(offered.filter((name) => picked.has(name)));
      }}
      onOpenChange={(open) => {
        if (open || ticked === null) return;
        setTicked(null);
        if (ticked.join('\n') !== value.join('\n')) onChange(ticked);
      }}
      isDisabled={disabled}
      className="flex min-w-0"
    >
      <AriaButton
        className={cx(
          'state-layer -mx-2 inline-flex min-w-0 max-w-56 cursor-pointer items-center gap-1.5 rounded-md px-2 text-left transition-colors data-disabled:cursor-wait',
          HIT_TARGET,
          names ? 'text-ink-secondary hover:text-ink' : 'text-ink-tertiary hover:text-ink-secondary',
        )}
      >
        <span className="truncate">{names ?? t('Unassigned')}</span>
        <ChevronDown aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2} />
      </AriaButton>
      <Popover className={cx(POPOVER, 'max-h-80 min-w-48')} placement="bottom start" offset={4}>
        <ListBox className="outline-none">
          {offered.map((name) => (
            <OptionItem key={name} id={name} textValue={name}>
              {name}
            </OptionItem>
          ))}
        </ListBox>
      </Popover>
    </AriaSelect>
  );
}
