import { Mail } from 'lucide-react';
import { useState } from 'react';
import { buttonClassName, Button } from '../../components/Button.tsx';
import { CopyButton } from '../../components/CopyButton.tsx';
import { Dialog } from '../../components/Dialog.tsx';
import { TextField } from '../../components/Field.tsx';
import { t } from '../../i18n/messages.ts';
import { draftText, mailtoLink, type EmailDraft } from './emailDraft.ts';

interface EmailDraftActionsProps {
  draft: EmailDraft;
  /** called when the draft is opened in the email app or copied */
  onSent?: (draft: EmailDraft) => void;
}

/**
 * Hands a draft to the reviewer's email app ("Open in email app", a mailto: link) or to the
 * clipboard ("Copy email"). A draft too long for a mailto: link opens without its body and
 * copies the body on the same click, so it can be pasted into the new message.
 *
 * `onSent(draft)` is called on either: the closest the workbench sees to the email going out.
 */
function EmailDraftActions({ draft, onSent }: EmailDraftActionsProps) {
  const { href, complete } = mailtoLink(draft);
  const [copied, setCopied] = useState<boolean | null>(null);

  const copyBody = async () => {
    try {
      if (!navigator.clipboard?.writeText) throw new Error('no clipboard');
      await navigator.clipboard.writeText(draft.body);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2">
        <a
          href={href}
          onClick={() => {
            if (!complete) copyBody();
            onSent?.(draft);
          }}
          className={buttonClassName({ variant: 'primary' })}
        >
          <Mail aria-hidden="true" className="size-4 shrink-0" strokeWidth={1.75} />
          <span>Open in email app</span>
        </a>
        <CopyButton text={draftText(draft)} label={t('Copy email')} variant="secondary" onCopied={onSent && (() => onSent(draft))} />
      </div>
      {onSent && (
        <p className="text-caption text-ink-secondary">
          {t("Opening or copying it marks it as sent in the project's Clarifications.")}
        </p>
      )}
      {!complete && (
        <p role="status" className="text-caption text-ink-secondary">
          {copied === true
            ? 'The text is copied. Paste it into the new email.'
            : copied === false
              ? 'The browser did not allow copying. Use Copy email, then paste it into the new email.'
              : 'This email is too long to hand over in full. Opening the email app copies the text, so you can paste it in.'}
        </p>
      )}
    </div>
  );
}

interface EmailDraftEditorProps {
  draft: EmailDraft;
  onChange: (draft: EmailDraft) => void;
  onSent?: (draft: EmailDraft) => void;
}

/** The recipient, subject and body of a draft as fields, with the actions under them. */
function EmailDraftEditor({ draft, onChange, onSent }: EmailDraftEditorProps) {
  const set = (field: keyof EmailDraft) => (value: string) => onChange({ ...draft, [field]: value });
  return (
    <div className="space-y-3">
      <TextField label="To" value={draft.to} onChange={set('to')} inputMode="email" placeholder="name@example.com" autoComplete="email" />
      <TextField label="Subject" value={draft.subject} onChange={set('subject')} />
      <TextField label="Message" value={draft.body} onChange={set('body')} multiline rows={14} inputClassName="text-callout" />
      <EmailDraftActions draft={draft} onSent={onSent} />
    </div>
  );
}

interface EmailDraftButtonProps {
  draft: EmailDraft;
  label?: string;
  variant?: 'primary' | 'secondary' | 'ghost';
  title?: string;
  className?: string;
  onSent?: (draft: EmailDraft) => void;
}

/**
 * The entry point for email drafting: a button that opens the draft in a dialog to edit and
 * send. `draft` is `{ to, subject, body }` from `riskEmailDraft`, `risksEmailDraft` or any other
 * source (such as the assistant). Edits are kept across closing and opening the dialog until
 * `draft` says something else (another risk, another filter). `onSent(draft)` gets the edited
 * draft when it is opened in the email app or copied.
 */
export function EmailDraftButton({
  draft,
  label = 'Draft an email',
  variant = 'secondary',
  title = 'Email draft',
  className,
  onSent,
}: EmailDraftButtonProps) {
  const [open, setOpen] = useState(false);
  const source = draftText(draft);
  const [edits, setEdits] = useState<{ source: string; draft: EmailDraft } | null>(null);
  const edited = edits?.source === source ? edits.draft : null;
  const setEdited = (next: EmailDraft) => setEdits({ source, draft: next });
  return (
    <>
      <Button variant={variant} icon={Mail} className={className} onPress={() => setOpen(true)}>
        {label}
      </Button>
      <Dialog
        open={open}
        onOpenChange={setOpen}
        title={title}
        size="lg"
      >
        <EmailDraftEditor draft={edited ?? draft} onChange={setEdited} onSent={onSent} />
      </Dialog>
    </>
  );
}
