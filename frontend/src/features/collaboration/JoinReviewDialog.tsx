import { useState } from 'react';
import { Button } from '../../components/Button.tsx';
import { Dialog } from '../../components/Dialog.tsx';
import { TextField } from '../../components/Field.tsx';
import { t } from '../../i18n/messages.ts';
import { useChooseReviewer } from './useChooseReviewer.ts';
import { useCollaboration } from './useCollaboration.ts';

interface JoinReviewDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

/**
 * "Choose reviewer": the names joined so far, one click each, and a new name to join with.
 * Opened from the user menu. Reviewer names are shared labels, not verified accounts.
 */
export function JoinReviewDialog({ open, onOpenChange }: JoinReviewDialogProps) {
  const context = useCollaboration();
  const { choose, pending, error, clearError } = useChooseReviewer();
  const [name, setName] = useState('');
  const reviewers = context?.reviewers ?? [];
  // A new opening starts without the last attempt's error (adjusted while rendering, as React
  // recommends for state that follows a prop).
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) clearError();
  }
  const select = async (value: string) => {
    if (await choose(value)) {
      setName('');
      onOpenChange(false);
    }
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={t('Choose reviewer')}
      description={t('Shared reviewer names, not verified accounts. Anyone with site access can choose a name.')}
      size="sm"
    >
      <div className="space-y-4">
        {reviewers.length > 0 && (
          <div role="group" aria-label={t('Joined reviewers')} className="flex flex-wrap gap-2">
            {reviewers.map((person) => (
              <Button key={person.handle} isDisabled={pending} onPress={() => select(person.name)}>
                {person.name}
              </Button>
            ))}
          </div>
        )}
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            select(name);
          }}
        >
          <TextField
            id="reviewer-name"
            label={t('Your name')}
            autoFocus
            isRequired
            pattern="[A-Za-z][A-Za-z0-9_]{0,31}"
            maxLength={32}
            placeholder="Larissa"
            value={name}
            onChange={setName}
            hint={t('Letters, numbers and underscores. Used as your @mention name.')}
          />
          {error && (
            <p role="alert" className="text-caption text-danger">
              {error}
            </p>
          )}
          <div className="flex justify-end">
            <Button type="submit" variant="primary" loading={pending}>
              {t('Join review')}
            </Button>
          </div>
        </form>
      </div>
    </Dialog>
  );
}
