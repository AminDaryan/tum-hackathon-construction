import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '../../components/Button.tsx';
import { TextField } from '../../components/Field.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { t } from '../../i18n/messages.ts';
import { getReviewerSession } from '../../services/collaborationService.ts';
import { AssigneesField } from './AssigneesField.tsx';
import type { ElementType, ReactNode } from 'react';

/** What the form submits. */
export interface ProjectDetails {
  name: string;
  description: string;
  assignees: string[];
}

interface ProjectFormProps {
  initial: {
    name?: string;
    description?: string;
    assignees?: string[];
  };
  submitLabel: string;
  submitIcon?: ElementType;
  pending?: boolean;
  onSubmit: (details: ProjectDetails) => void;
  onCancel: () => void;
  assignSelf?: boolean;
  children?: ReactNode;
}

/**
 * A project's details in one column across the page, labels above their fields: name, short
 * description and the users assigned to it. The reviewers who signed in before are offered as
 * assignees, and on a new project the reviewer signed in on this browser is assigned from the start. `children`
 * (the files of a new project) come between the details and the buttons; Cancel and the
 * primary button sit on the trailing edge.
 */
export function ProjectForm({
  initial,
  submitLabel,
  submitIcon,
  pending = false,
  onSubmit,
  onCancel,
  assignSelf = false,
  children,
}: ProjectFormProps) {
  const id = useId();
  const [name, setName] = useState(initial.name ?? '');
  const [description, setDescription] = useState(initial.description ?? '');
  const [assignees, setAssignees] = useState(initial.assignees ?? []);
  const touched = useRef(false);
  const session = useApiResource((signal) => getReviewerSession(signal), []);
  const me = session.data?.reviewer?.name ?? null;
  const known = (session.data?.reviewers ?? []).map((person) => person.name);

  useEffect(() => {
    if (assignSelf && me && !touched.current) setAssignees((current) => (current.length ? current : [me]));
  }, [assignSelf, me]);

  return (
    <form
      className="flex flex-col gap-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (name.trim()) onSubmit({ name: name.trim(), description: description.trim(), assignees });
      }}
    >
      <section aria-labelledby={`${id}-details`} className="flex flex-col gap-5 rounded-lg border border-hairline bg-surface p-5">
        <h2 id={`${id}-details`} className="text-headline text-ink">
          {t('Details')}
        </h2>
        <TextField
          label={t('Name')}
          value={name}
          onChange={setName}
          maxLength={160}
          isRequired
          autoFocus
          placeholder={t('For example, Riverside tender')}
        />
        <TextField
          label={t('Description (optional)')}
          value={description}
          onChange={setDescription}
          maxLength={2000}
          multiline
          rows={3}
          hint={t('What the tender covers, in a sentence or two. It shows in the projects table.')}
        />
        <AssigneesField
          value={assignees}
          onChange={(next) => {
            touched.current = true;
            setAssignees(next);
          }}
          suggestions={known}
          suggestionsLoading={!session.data && !session.error}
        />
      </section>
      {children}
      <div className="flex flex-wrap justify-end gap-3">
        <Button onPress={onCancel}>{t('Cancel')}</Button>
        <Button type="submit" variant="primary" size="lg" icon={submitIcon} loading={pending} isDisabled={!name.trim()}>
          {submitLabel}
        </Button>
      </div>
    </form>
  );
}
