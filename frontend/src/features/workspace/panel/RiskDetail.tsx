import { ChevronLeft, ChevronRight, Crosshair } from 'lucide-react';
import { useEffect, useId, useMemo, useRef } from 'react';
import { Badge } from '../../../components/Badge.tsx';
import { Button } from '../../../components/Button.tsx';
import { CopyButton } from '../../../components/CopyButton.tsx';
import { Disclosure } from '../../../components/Disclosure.tsx';
import { IconButton } from '../../../components/IconButton.tsx';
import { useApiResource } from '../../../hooks/useApiResource.ts';
import { t } from '../../../i18n/messages.ts';
import { getIssue } from '../../../services/issuesService.ts';
import { formatCount } from '../../../utils/format.ts';
import {
  CERTAINTY_DESCRIPTIONS,
  CERTAINTY_LABELS,
  HARM_LABELS,
  isModelSuggested,
  plainExplanation,
  riskMethods,
} from '../../risks/riskModel.ts';
import { IssueDetails } from '../context/IssueDetails.tsx';
import { RiskDecisionBar } from './RiskDecisionBar.tsx';
import { RiskEvidence } from './RiskEvidence.tsx';
import { FindingComments } from '../../collaboration/FindingComments.tsx';
import { useMarkEmailSent } from '../../clarifications/useRaiseClarification.ts';
import { EmailDraftButton } from '../../email/EmailDraft.tsx';
import { riskEmailDraft } from '../../email/emailDraft.ts';
import { priceFacts } from '../../risks/pricing.ts';
import { ClassificationChip, MethodBadges, MoneyText, PriorityBadge, RiskStatus } from './RiskBits.tsx';
import type { ReactNode } from 'react';
import type {
  DetectorDescriptor,
  Risk,
  RiskPosition,
  RiskReview,
  Row,
  TableSummary,
  ValidationIssue,
} from '../../../services/apiTypes.ts';
import type { RiskStatus as Decision } from '../../risks/riskModel.ts';
import type { SheetTarget } from '../issueTarget.ts';

const NAV_BUTTON = 'disabled:cursor-not-allowed disabled:opacity-40';

interface SectionProps {
  title: string;
  children?: ReactNode;
}

function Section({ title, children }: SectionProps) {
  return (
    <section className="space-y-1.5">
      <h3 className="text-callout font-semibold text-ink">{title}</h3>
      {children}
    </section>
  );
}

interface PositionsProps {
  risk: Risk;
  onShowPosition: (position: RiskPosition) => void;
}

/** The risk's positions, each with "Show in the sheet". */
function Positions({ risk, onShowPosition }: PositionsProps) {
  const positions = risk.positions ?? [];
  if (!positions.length) return <p className="text-body text-ink">{t('This risk is about the bill as a whole.')}</p>;
  const more = (risk.positions_total ?? positions.length) - positions.length;
  return (
    <ul className="space-y-1">
      {positions.map((position) => (
        <li key={`${position.row_id ?? ''}:${position.label}`} className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <span className="sheet-figures min-w-0 flex-1 text-body text-ink">{position.label}</span>
          {position.row_id && (
            <Button variant="ghost" icon={Crosshair} onPress={() => onShowPosition(position)}>
              {t('Show in the sheet')}
            </Button>
          )}
        </li>
      ))}
      {more > 0 && <li className="text-caption text-ink-secondary">{t('and {count} more positions', { count: formatCount(more) })}</li>}
    </ul>
  );
}

interface FindingSwitchProps {
  findings: ValidationIssue[];
  shownId?: string;
  onSelect: (issue: ValidationIssue) => void;
}

/** A segmented switch between the findings of a risk with more than one. */
function FindingSwitch({ findings, shownId, onSelect }: FindingSwitchProps) {
  return (
    <div role="group" aria-label={t('Findings behind this risk')} className="flex flex-wrap gap-1.5">
      {findings.map((issue, index) => {
        const active = issue.issue_id === shownId;
        return (
          <Button
            key={issue.issue_id}
            variant={active ? 'secondary' : 'ghost'}
            aria-pressed={active}
            onPress={() => onSelect(issue)}
          >
            {t('Finding {index} of {total}', { index: formatCount(index + 1), total: formatCount(findings.length) })}
          </Button>
        );
      })}
    </div>
  );
}

interface RiskDetailProps {
  risk?: Risk | null;
  title: string;
  classification: string;
  status: Decision;
  review?: RiskReview | null;
  findings: ValidationIssue[];
  issue?: ValidationIssue | null;
  position?: { index: number; total: number } | null;
  onBack: () => void;
  onPrevious: () => void;
  onNext: () => void;
  onSelectFinding: (issue: ValidationIssue) => void;
  onIssueUpdated: (issue: ValidationIssue) => void;
  onSaveReview: (riskId: string, status: Decision, comment: string) => Promise<unknown>;
  onApproved?: (risk: Risk) => void;
  nextRisk?: Risk | null;
  onOpenRisk: (risk: Risk) => void;
  /** The price of the risk's position (`PriceSection`), when its row is priced. */
  price?: ReactNode;
  row?: Row | null;
  /** The sheet row of the risk's position, for the figures in the email draft. */
  positionRow?: Row | null;
  table?: TableSummary | null;
  catalogue?: ReadonlyMap<string, DetectorDescriptor>;
  onRevealCell: (target: SheetTarget) => void;
  onShowPosition: (position: RiskPosition) => void;
  focusDecisionKey?: number | null;
  /** The file name of the bill, named in the email draft. */
  billName?: string | null;
  currency?: string | null;
}

/**
 * One risk drilled into from the Risks list. Back to the list with previous and next; then the
 * priority, status and classification; what is wrong in one or two plain sentences; what to do
 * (with the question for the client); the price of the position; where it is; and, behind
 * "Details and evidence", the money basis, certainty, evidence, rules and the finding itself.
 * The decision (Approve, Reject, Needs clarification) is pinned at the bottom.
 *
 * The shown finding is loaded with its history (`getIssue`); whichever copy has the higher
 * `version` is shown and decided on.
 */
export function RiskDetail({
  risk,
  title,
  classification,
  status,
  review = null,
  findings,
  issue,
  position,
  onBack,
  onPrevious,
  onNext,
  onSelectFinding,
  onIssueUpdated,
  onSaveReview,
  onApproved,
  nextRisk = null,
  onOpenRisk,
  price = null,
  row,
  positionRow = null,
  table,
  catalogue,
  onRevealCell,
  onShowPosition,
  focusDecisionKey,
  billName = null,
  currency = null,
}: RiskDetailProps) {
  const titleId = useId();
  const scrollRef = useRef<HTMLDivElement>(null);
  const decisionRef = useRef<HTMLDivElement>(null);
  const handledFocusKey = useRef<number | null>(null);
  const syncedVersion = useRef<string | null>(null);
  const issueId = issue?.issue_id ?? null;
  const riskId = risk?.risk_id ?? null;

  // Only fetched with an issue id (enabled).
  const detail = useApiResource((signal) => getIssue(issueId!, { signal }), [issueId], { enabled: Boolean(issueId) });
  const loaded = detail.data?.issue?.issue_id === issueId ? detail.data : null;
  const current = issue && loaded && loaded.issue.version >= issue.version ? loaded.issue : issue;
  const decided = useMemo(
    () => findings.map((finding) => (current && finding.issue_id === current.issue_id ? current : finding)),
    [findings, current],
  );

  // A newer copy from the server (decided elsewhere) also updates the list and the sheet, once.
  useEffect(() => {
    if (!issue || !loaded || loaded.issue.version <= issue.version) return;
    const key = `${loaded.issue.issue_id}:${loaded.issue.version}`;
    if (syncedVersion.current === key) return;
    syncedVersion.current = key;
    onIssueUpdated(loaded.issue);
  }, [issue, loaded, onIssueUpdated]);

  useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = 0;
  }, [riskId]);

  // "Review" from the sheet asks for the decision buttons (a new key each time).
  useEffect(() => {
    if (focusDecisionKey == null || focusDecisionKey === handledFocusKey.current || !risk) return;
    const button = decisionRef.current?.querySelector<HTMLElement>('[data-decision]:not([disabled])');
    if (button) {
      handledFocusKey.current = focusDecisionKey;
      button.focus();
    }
  }, [focusDecisionKey, risk]);

  const markSent = useMarkEmailSent();

  const handleIssueUpdated = (next: ValidationIssue) => {
    if (next.issue_id === issueId) detail.setData((previous) => (previous ? { ...previous, issue: next } : previous));
    onIssueUpdated(next);
  };

  const known = position && position.index >= 0 && position.total > 0;
  const explanation = plainExplanation(risk?.why_risk_here);
  const question = risk?.question ?? null;
  const missing = risk?.missing_information ?? [];
  const certainty = risk?.factors?.certainty ?? '';
  const harm = risk?.factors?.harm ? HARM_LABELS[risk.factors.harm] : undefined;
  const emailDraft = risk
    ? riskEmailDraft({
        risk,
        title,
        facts: priceFacts(positionRow, table),
        billName,
      })
    : null;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex min-h-10 shrink-0 items-center gap-1 border-b border-hairline py-1 pl-1 pr-2">
        <Button variant="ghost" icon={ChevronLeft} onPress={onBack}>
          {t('All risks')}
        </Button>
        <p className="min-w-0 flex-1 text-center text-callout text-ink-secondary" aria-live="polite">
          {known ? t('Risk {index} of {total}', { index: formatCount(position.index + 1), total: formatCount(position.total) }) : t('Risk')}
        </p>
        <IconButton
          icon={ChevronLeft}
          label={t('Previous risk in the list')}
          className={NAV_BUTTON}
          isDisabled={!known || position.index === 0}
          onPress={onPrevious}
        />
        <IconButton
          icon={ChevronRight}
          label={t('Next risk in the list')}
          className={NAV_BUTTON}
          isDisabled={!known || position.index >= position.total - 1}
          onPress={onNext}
        />
      </div>

      <div ref={scrollRef} className="relative min-h-0 flex-1 overflow-y-auto px-3 py-3">
        {risk ? (
          <div
            key={riskId}
            className="space-y-4 transition-opacity duration-160 ease-out starting:opacity-0 motion-reduce:transition-none"
          >
            <header className="space-y-2">
              <div className="flex flex-wrap items-center gap-2">
                <PriorityBadge tier={risk.tier} />
                <RiskStatus status={status} />
                <ClassificationChip classification={classification} />
              </div>
              <h2 id={titleId} className="text-title text-ink">
                {title}
              </h2>
              <Positions risk={risk} onShowPosition={onShowPosition} />
            </header>

            <Section title={t("What's wrong")}>
              {risk.title && risk.title !== title && <p className="text-body text-ink">{risk.title}</p>}
              {explanation && <p className="text-body text-ink-secondary">{explanation}</p>}
            </Section>

            <Section title={t('What to do')}>
              {risk.suggested_action && <p className="text-body text-ink">{risk.suggested_action}</p>}
              {question && (
                <div className="flex items-start gap-1 rounded-md bg-surface-muted py-1.5 pl-3 pr-1">
                  <p className="min-w-0 flex-1 text-callout text-ink">
                    <span className="text-caption text-ink-tertiary">{t('Ask the client')}: </span>
                    {question}
                  </p>
                  <CopyButton text={question} label={t('Copy question')} variant="ghost" iconOnly />
                </div>
              )}
              {missing.length > 0 && (
                <>
                  <p className="text-caption text-ink-tertiary">{t('Missing information')}</p>
                  <ul className="list-disc space-y-0.5 pl-5 text-callout text-ink-secondary">
                    {missing.map((item) => (
                      <li key={item}>{item}</li>
                    ))}
                  </ul>
                </>
              )}
              {emailDraft && (
                <div className="pt-1">
                  <EmailDraftButton
                    draft={emailDraft}
                    label={t('Draft an email')}
                    title={t('Email about this risk')}
                    onSent={markSent ? (draft) => markSent(risk, title, issueId, draft) : undefined}
                  />
                </div>
              )}
            </Section>

            {issueId && <FindingComments key={issueId} issueId={issueId} />}

            {price}

            <Disclosure title={t('Details and evidence')} className="border-t border-hairline pt-3">
              <div className="flex flex-wrap gap-1.5">
                <MethodBadges methods={riskMethods(risk)} />
                {findings.some(isModelSuggested) && <Badge>Model-suggested match</Badge>}
              </div>
              <dl className="grid grid-cols-1 gap-x-4 gap-y-2 @md:grid-cols-3">
                <div className="min-w-0">
                  <dt className="text-caption text-ink-tertiary">{t('Money at stake')}</dt>
                  <dd className="mt-0.5 text-body text-ink">
                    <MoneyText money={risk.money} showBasis />
                  </dd>
                </div>
                <div className="min-w-0" title={t(CERTAINTY_DESCRIPTIONS[certainty])}>
                  <dt className="text-caption text-ink-tertiary">{t('Evidence certainty')}</dt>
                  <dd className="mt-0.5 text-body text-ink">{t(CERTAINTY_LABELS[certainty] ?? 'Unclear')}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-caption text-ink-tertiary">{t('Harm')}</dt>
                  <dd className="mt-0.5 text-body text-ink">{harm ? t(harm) : t('Not stated')}</dd>
                </div>
              </dl>
              {risk.tier_reason && <p className="text-callout text-ink-secondary">{risk.tier_reason}</p>}
              <RiskEvidence risk={risk} />
              {current && (
                <div aria-label={t('Finding behind this risk')} role="group" className="space-y-3 border-t border-hairline pt-3">
                  {findings.length > 1 && (
                    <FindingSwitch findings={findings} shownId={current.issue_id} onSelect={onSelectFinding} />
                  )}
                  <IssueDetails
                    issue={current}
                    history={loaded?.history}
                    historyLoading={detail.loading}
                    historyError={detail.error}
                    onRetryHistory={detail.reload}
                    row={row}
                    table={table ?? undefined}
                    catalogue={catalogue}
                    onRevealCell={onRevealCell}
                  />
                </div>
              )}
            </Disclosure>
          </div>
        ) : (
          <p className="text-body text-ink-secondary">{t('This risk is no longer in the report.')}</p>
        )}
      </div>

      {risk && (
        <div ref={decisionRef} className="shrink-0">
          <RiskDecisionBar
            key={riskId}
            risk={risk}
            title={title}
            findings={decided}
            status={status}
            review={review}
            onSaveReview={onSaveReview}
            onIssueUpdated={handleIssueUpdated}
            onApproved={onApproved}
            nextRisk={nextRisk}
            onOpenRisk={onOpenRisk}
          />
        </div>
      )}
    </div>
  );
}
