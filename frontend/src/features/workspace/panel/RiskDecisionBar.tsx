import { Undo2 } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { Button } from '../../../components/Button.tsx';
import { Dialog } from '../../../components/Dialog.tsx';
import { TextField } from '../../../components/Field.tsx';
import { useAsyncAction } from '../../../hooks/useAsyncAction.ts';
import { msg, t } from '../../../i18n/messages.ts';
import { describeError } from '../../../utils/errors.ts';
import { formatDateTime } from '../../../utils/format.ts';
import { useRaiseClarification } from '../../clarifications/useRaiseClarification.ts';
import { saveDecision, STALE_MESSAGE } from '../context/reviewDecision.ts';
import type { Risk, RiskReview, ValidationIssue } from '../../../services/apiTypes.ts';

const NOTE_LIMIT = 4000;

type Decision = RiskReview['status'];

/** A risk decision as the review status of its findings. */
const FINDING_STATUS: Readonly<Record<Decision, string>> = Object.freeze({
  approved: 'confirmed_error',
  rejected: 'false_positive',
  in_review: 'needs_more_information',
  open: 'pending_review',
});

const DECIDED_WORDS: Readonly<Record<string, string>> = Object.freeze({
  approved: msg('Approved'),
  rejected: msg('Rejected'),
  in_review: msg('In review: waiting for clarification'),
});

const DECISIONS = Object.freeze<{ status: Decision; label: string; hint: string }[]>([
  { status: 'approved', label: msg('Approve'), hint: msg('It is a real risk. Edit the cell next.') },
  { status: 'rejected', label: msg('Reject'), hint: msg('Not a risk. It stays in the list as rejected.') },
]);

/** When the shown decision was made: the newest review time among the findings, or the review's. */
function decidedAt(findings: ValidationIssue[], review: Pick<RiskReview, 'reviewed_at'> | null) {
  if (!findings.length) return review?.reviewed_at ?? null;
  return findings.map((issue) => issue.reviewed_at).filter(Boolean).sort().at(-1) ?? null;
}

interface RiskDecisionBarProps {
  risk: Risk;
  /** The short title shown for the risk, the wording of its clarification. */
  title?: string;
  findings: ValidationIssue[];
  status: Decision;
  review?: Pick<RiskReview, 'comment' | 'reviewed_at'> | null;
  onSaveReview: (riskId: string, status: Decision, comment: string) => Promise<unknown>;
  onIssueUpdated: (issue: ValidationIssue) => void;
  onApproved?: (risk: Risk) => void;
  nextRisk?: Risk | null;
  onOpenRisk: (risk: Risk) => void;
}

/**
 * The decision on one risk, pinned under its detail: Approve, Reject, Needs clarification and an
 * optional note; once decided, the decision with Undo and the next open risk.
 *
 * A risk with findings is decided through every finding that allows the decision (one request
 * each, with the version the reviewer saw; a stale finding is reloaded and the reviewer decides
 * again). A risk without a finding is decided through its risk review. Approve then hands over
 * to the sheet (`onApproved`), where the cell opens for editing. Needs clarification also lists
 * the risk, under `title`, in the Clarifications of the project the bill was opened from.
 */
export function RiskDecisionBar({
  risk,
  title,
  findings,
  status,
  review = null,
  onSaveReview,
  onIssueUpdated,
  onApproved,
  nextRisk = null,
  onOpenRisk,
}: RiskDecisionBarProps) {
  const noteId = useId();
  const noteRef = useRef<HTMLInputElement & HTMLTextAreaElement>(null);
  const groupRef = useRef<HTMLDivElement>(null);
  const [note, setNote] = useState('');
  const [noteOpen, setNoteOpen] = useState(false);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<Decision | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState('');
  const [focusAfter, setFocusAfter] = useState<'after-decision' | 'first-decision' | 'add-note' | null>(null);
  const raiseClarification = useRaiseClarification();

  const action = useAsyncAction(async (signal, target: Decision, comment: string) => {
    if (!findings.length) {
      await onSaveReview(risk.risk_id, target, comment);
      return { stale: false };
    }
    const wanted = FINDING_STATUS[target];
    let stale = false;
    for (const issue of findings) {
      if (issue.review_status === wanted || !(issue.allowed_review_actions ?? []).includes(wanted)) continue;
      const outcome = await saveDecision(issue, wanted, comment, signal);
      onIssueUpdated(outcome.detail.issue);
      stale = stale || outcome.stale;
    }
    return { stale };
  });

  useEffect(() => {
    if (!focusAfter) return;
    const group = groupRef.current;
    const target =
      (focusAfter === 'add-note' && group?.querySelector<HTMLElement>('[data-focus="add-note"]')) ||
      (focusAfter === 'after-decision' && group?.querySelector<HTMLElement>('[data-focus="after-decision"]')) ||
      group?.querySelector<HTMLElement>('button:not([disabled])');
    target?.focus();
    setFocusAfter(null);
  }, [focusAfter]);

  useEffect(() => {
    if (noteOpen) noteRef.current?.focus();
  }, [noteOpen]);

  const discardNote = () => {
    setNote('');
    setNoteOpen(false);
    setConfirmDiscard(false);
    setFocusAfter('add-note');
  };

  const decide = async (target: Decision) => {
    setPendingStatus(target);
    setNotice(null);
    setAnnouncement('');
    const outcome = await action.execute(target, noteOpen ? note : '');
    setPendingStatus(null);
    if (!outcome) return;
    if (outcome.stale) {
      setNotice(t(STALE_MESSAGE));
      return;
    }
    setNote('');
    setNoteOpen(false);
    if (target === 'open') {
      setAnnouncement(t('Decision undone. The risk is open again.'));
      setFocusAfter('first-decision');
      return;
    }
    setAnnouncement(t('Saved. {decision}.', { decision: t(DECIDED_WORDS[target]) }));
    if (target === 'in_review') {
      // The decision is saved by now; listing the question in the project must not undo it.
      raiseClarification(risk, title).then(
        (raised) => raised && setNotice(t('Listed in the Clarifications of the project.')),
        () => setNotice(t('The decision is saved, but the risk was not added to the Clarifications of the project.')),
      );
    }
    if (target === 'approved') onApproved?.(risk);
    else setFocusAfter('after-decision');
  };

  const allows = (target: Decision) =>
    !findings.length || findings.some((issue) => (issue.allowed_review_actions ?? []).includes(FINDING_STATUS[target]));
  const decided = status === 'approved' || status === 'rejected';
  const busy = action.pending;
  const failure = action.error && !busy ? describeError(action.error) : null;
  const when = decidedAt(findings, review);
  const comment = findings.length ? findings.find((issue) => issue.reviewer_comment)?.reviewer_comment : review?.comment;

  let content;
  if (decided) {
    content = (
      <>
        <p className="text-callout font-medium text-ink">
          {when
            ? t('{decision} on {date}', { decision: t(DECIDED_WORDS[status]), date: formatDateTime(when) })
            : `${t(DECIDED_WORDS[status])}.`}
        </p>
        {comment && <p className="whitespace-pre-line border-l-2 border-hairline pl-3 text-callout text-ink-secondary">{comment}</p>}
        <div className="-ml-3 flex flex-wrap items-center gap-2">
          {allows('open') && (
            <Button
              variant="ghost"
              icon={Undo2}
              loading={pendingStatus === 'open'}
              isDisabled={busy && pendingStatus !== 'open'}
              data-focus={nextRisk ? undefined : 'after-decision'}
              onPress={() => decide('open')}
            >
              {t('Undo decision')}
            </Button>
          )}
          {nextRisk ? (
            <Button variant="primary" className="ml-auto" isDisabled={busy} data-focus="after-decision" onPress={() => onOpenRisk(nextRisk)}>
              {t('Next risk')}
            </Button>
          ) : (
            <p className="ml-auto text-callout text-ink-secondary">{t('Every risk is reviewed.')}</p>
          )}
        </div>
      </>
    );
  } else {
    const offered = DECISIONS.filter((decision) => allows(decision.status));
    content = (
      <>
        {status === 'in_review' && (
          <p className="text-callout text-ink">
            {when
              ? t('{status} since {date}.', { status: t(DECIDED_WORDS.in_review), date: formatDateTime(when) })
              : `${t(DECIDED_WORDS.in_review)}.`}
          </p>
        )}
        {status === 'in_review' && comment && (
          <p className="whitespace-pre-line border-l-2 border-hairline pl-3 text-callout text-ink-secondary">{comment}</p>
        )}
        {offered.length > 0 && (
          <div className="grid grid-cols-2 gap-2">
            {offered.map((decision, index) => (
              <div key={decision.status} title={t(decision.hint)}>
                <Button
                  variant={index === 0 ? 'primary' : 'secondary'}
                  loading={pendingStatus === decision.status}
                  isDisabled={busy && pendingStatus !== decision.status}
                  data-decision={decision.status}
                  className="w-full text-center"
                  onPress={() => decide(decision.status)}
                >
                  {t(decision.label)}
                </Button>
              </div>
            ))}
          </div>
        )}
        <div className="-ml-3 flex flex-wrap items-center gap-2">
          {status === 'open' && allows('in_review') && (
            <Button
              variant="ghost"
              loading={pendingStatus === 'in_review'}
              isDisabled={busy && pendingStatus !== 'in_review'}
              data-decision="in_review"
              onPress={() => decide('in_review')}
            >
              {t('Needs clarification')}
            </Button>
          )}
          {noteOpen ? (
            <Button variant="ghost" isDisabled={busy} onPress={() => note.trim() ? setConfirmDiscard(true) : discardNote()}>
              {t('Cancel')}
            </Button>
          ) : (
            <Button variant="ghost" data-focus="add-note" aria-expanded="false" aria-controls={noteId} onPress={() => setNoteOpen(true)}>
              {t('Add a note')}
            </Button>
          )}
        </div>
        {noteOpen && (
          <TextField
            id={noteId}
            label={t('Note (optional)')}
            multiline
            rows={2}
            inputRef={noteRef}
            value={note}
            maxLength={NOTE_LIMIT}
            isDisabled={busy}
            onChange={setNote}
          />
        )}
        {offered.length === 0 && !allows('in_review') && (
          <p className="text-callout text-ink-secondary">{t('No decision can be recorded for this risk in its current state.')}</p>
        )}
      </>
    );
  }

  return (
    <div className="shrink-0 space-y-2 border-t border-hairline bg-surface px-4 py-3">
      <p role="status" className="sr-only">
        {announcement}
      </p>
      {notice && (
        <p role="alert" className="text-callout text-ink">
          {notice}
        </p>
      )}
      {failure && (
        <p role="alert" className="text-callout text-danger">
          {t('The decision was not saved.')} {failure.message}
          {failure.hint && <span className="block text-ink-secondary">{failure.hint}</span>}
        </p>
      )}
      <div ref={groupRef} role="group" aria-label={t('Review decision')} className="space-y-2">
        {content}
      </div>
      <Dialog
        open={confirmDiscard}
        onOpenChange={setConfirmDiscard}
        role="alertdialog"
        title={t('Discard unsaved note?')}
        description={t('Only this unsaved draft will be discarded. Saved notes and the review decision will stay unchanged.')}
        size="sm"
      >
        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" autoFocus onPress={() => setConfirmDiscard(false)}>
            {t('Continue editing')}
          </Button>
          <Button variant="danger" onPress={discardNote}>
            {t('Discard changes')}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
