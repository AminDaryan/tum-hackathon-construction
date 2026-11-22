import { FileText, Printer } from 'lucide-react';
import { useNavigate, useParams } from 'react-router-dom';
import { projectPath } from '../../app/navigation.ts';
import { usePageTitle } from '../../app/pageTitle.tsx';
import { Button } from '../../components/Button.tsx';
import { EmptyState } from '../../components/EmptyState.tsx';
import { ErrorState } from '../../components/ErrorState.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { useDocumentTitle } from '../../hooks/useDocumentTitle.ts';
import { msg, t } from '../../i18n/messages.ts';
import { ApiError } from '../../services/apiClient.ts';
import type { BidOtherReminder, BidPosition, BidReminder, BidReport } from '../../services/apiTypes.ts';
import { getProjectRiskReport } from '../../services/projectsService.ts';
import { formatDateTime, formatDecimal, formatMoney, pluralize } from '../../utils/format.ts';
import { MoneyText, PriorityBadge } from '../workspace/panel/RiskBits.tsx';
import { useProject } from './ProjectContext.tsx';
import { ProjectReportPlaceholder } from './ProjectReportPlaceholder.tsx';

const CARD = 'rounded-lg border border-hairline bg-surface print:rounded-none print:border-0';

/** A share (0 to 1) as a percentage with one decimal: the share of a bill's total. */
function percent(share: string | null): string | null {
  return share == null ? null : `${formatDecimal((Number(share) * 100).toFixed(1))} %`;
}

/**
 * A reminder with its money. An unknown amount's size class describes all the positions the
 * reminder concerns together, so under a position row (which shows its own share) it would
 * read as that position's size: ``inRow`` leaves it out. Elsewhere only a large share is said.
 */
function Reminder({ reminder, inRow }: { reminder: BidReminder; inRow: boolean }) {
  const money = reminder.money;
  const sizeShown = !inRow && money?.size_class === 'large';
  return (
    <div className="flex flex-col gap-1">
      <div className="flex flex-wrap items-center gap-2">
        <PriorityBadge tier={reminder.tier} />
        <span className="text-body font-medium text-ink">{reminder.title}</span>
      </div>
      <div className="flex flex-wrap gap-x-2 text-caption text-ink-secondary">
        <span>{t('Money at stake')}:</span>
        <MoneyText money={money?.kind === 'unknown' && !sizeShown ? { ...money, size_class: undefined } : money} />
      </div>
      {reminder.question && <p className="text-callout text-ink-secondary">{reminder.question}</p>}
    </div>
  );
}

function PositionRow({ row, several }: { row: BidPosition; several: boolean }) {
  const share = percent(row.share_of_total);
  return (
    <tr className="align-top print:break-inside-avoid">
      <td className="sheet-figures px-3 py-3 text-callout text-ink-secondary">{row.rank}</td>
      <td className="px-3 py-3">
        <div className="sheet-figures text-callout font-medium text-ink">{row.label}</div>
        <div className="text-body text-ink">{row.short_text}</div>
        <div className="text-caption text-ink-secondary">
          {row.quantity != null && `${formatDecimal(row.quantity)} ${row.unit ?? ''}`}
          {several && <span className="block">{row.document_name}</span>}
        </div>
      </td>
      <td className="sheet-figures px-3 py-3 text-right text-body text-ink">
        <div>{formatMoney(row.line_total, row.currency)}</div>
        {share && <div className="text-caption text-ink-secondary">{t('{share} of the bill', { share })}</div>}
      </td>
      <td className="px-3 py-3">
        {row.reminders.length === 0 ? (
          <p className="text-callout text-ink-secondary">{t('No reminder: listed for its size')}</p>
        ) : (
          <div className="flex flex-col gap-3">
            {row.reminders.map((reminder) => (
              <Reminder key={reminder.risk_id} reminder={reminder} inRow />
            ))}
          </div>
        )}
      </td>
    </tr>
  );
}

const REASONS: Record<BidOtherReminder['reason'], string> = {
  many_positions: msg('Concerns {count} positions'),
  no_position: msg('Concerns the whole bill'),
  not_a_position: msg('Concerns a total or heading row'),
};

function OtherReminders({ items, several }: { items: BidOtherReminder[]; several: boolean }) {
  return (
    <section aria-labelledby="bid-other-heading" className={CARD}>
      <div className="border-b border-hairline px-4 py-3 print:px-0">
        <h3 id="bid-other-heading" className="text-headline text-ink">
          {t('Reminders about several positions')}
        </h3>
        <p className="text-caption text-ink-secondary">{t('Listed once; their money is not spread over the positions.')}</p>
      </div>
      <ul className="divide-y divide-hairline">
        {items.map((item) => (
          <li key={`${item.run_id}/${item.reminder.risk_id}`} className="flex flex-col gap-1 px-4 py-3 print:break-inside-avoid print:px-0">
            <Reminder reminder={item.reminder} inRow={false} />
            <p className="text-caption text-ink-secondary">
              {t(REASONS[item.reason], { count: item.reminder.positions_total })}
              {item.positions.length > 0 && `: ${item.positions.join(', ')}`}
              {item.positions.length < item.reminder.positions_total && ' …'}
              {several && ` (${item.document_name})`}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

function Summary({ report }: { report: BidReport }) {
  return (
    <section aria-labelledby="bid-bills-heading" className={`${CARD} px-4 py-3 print:px-0`}>
      <h3 id="bid-bills-heading" className="text-headline text-ink">
        {t('Bills in this report')}
      </h3>
      <ul className="mt-2 flex flex-col gap-1 text-callout text-ink">
        {report.bills.map((bill) => (
          <li key={bill.document_id}>
            <span className="font-medium">{bill.document_name}</span>
            {': '}
            {bill.priced
              ? t('{positions}, total {total}', { positions: pluralize(bill.positions, 'position'), total: formatMoney(bill.counted_total, bill.currency) })
              : t('{positions}, no prices', { positions: pluralize(bill.positions, 'position') })}
          </li>
        ))}
        {report.skipped.map((file) => (
          <li key={file.document_id} className="text-ink-secondary">
            {t('Not in this report: {name} ({reason})', { name: file.document_name, reason: file.reason })}
          </li>
        ))}
      </ul>
    </section>
  );
}

/**
 * The bid risk report of a project, to print or save as PDF and hand over (issue #112): the
 * positions of its bills that drive price and risk, each with its line total and the money of
 * its reminders, then the reminders about several positions, then how the list was made.
 * Printing hides the app's frame (AppShell) and this page's Print button. Before the project
 * is validated it says so and leads back to the project, where Validate project is.
 */
export function ProjectReportPage() {
  const { projectId = '' } = useParams();
  const { project } = useProject();
  const navigate = useNavigate();
  const resource = useApiResource((signal) => getProjectRiskReport(projectId, 20, signal), [projectId]);
  const report = resource.data?.project_id === projectId ? resource.data : null;
  useDocumentTitle(report ? t('Bid risk report: {name}', { name: report.project_name }) : t('Bid risk report'));
  usePageTitle({
    title: t('Bid risk report'),
    back: { label: t('Back to reports'), to: `/projects/${encodeURIComponent(projectId)}/reports` },
  });

  // 409 while the project is not being validated: it has no validation (never run, or its files
  // changed since), which is a next step to take, not a failure.
  const notValidated = resource.error instanceof ApiError && resource.error.status === 409 && project?.validation?.status !== 'running';
  if (notValidated && !report) {
    return (
      <EmptyState
        icon={FileText}
        title={t('Validate the project to see its bid risk report')}
        action={
          <Button variant="primary" onPress={() => navigate(projectPath(projectId))}>
            {t('Open the project overview')}
          </Button>
        }
      />
    );
  }
  if (resource.error && !report) return <ErrorState error={resource.error} onRetry={resource.reload} />;
  if (!report) return <ProjectReportPlaceholder />;

  const several = report.bills.length > 1;
  return (
    <article className="flex flex-col gap-4 print:text-[10pt]">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-headline text-ink">{t('Bid risk report: {name}', { name: report.project_name })}</h2>
          <p className="text-callout text-ink-secondary">{t('Made on {time} from the last validation.', { time: formatDateTime(report.generated_at) })}</p>
        </div>
        <Button variant="primary" icon={Printer} onPress={() => window.print()} className="print:hidden">
          {t('Print or save as PDF')}
        </Button>
      </header>
      <Summary report={report} />
      <section aria-labelledby="bid-positions-heading" className={CARD}>
        <div className="border-b border-hairline px-4 py-3 print:px-0">
          <h3 id="bid-positions-heading" className="text-headline text-ink">
            {t('Positions that drive price and risk')}
          </h3>
          <p className="text-caption text-ink-secondary">
            {t('{shown} of {total} with reminders', {
              shown: report.positions.filter((p) => p.kind === 'reminders').length,
              total: pluralize(report.positions_with_reminders, 'position'),
            })}
          </p>
        </div>
        {report.positions.length === 0 ? (
          <p className="px-4 py-4 text-body text-ink-secondary">{t('No position has a reminder.')}</p>
        ) : (
          <div className="overflow-x-auto print:overflow-visible">
            <table className="w-full min-w-[48rem] border-collapse text-left print:min-w-0">
              <thead className="border-b border-hairline text-caption text-ink-secondary">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">#</th>
                  <th scope="col" className="px-3 py-2 font-medium">{t('Position')}</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">{t('Line total')}</th>
                  <th scope="col" className="px-3 py-2 font-medium">{t('Reminders')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-hairline">
                {report.positions.map((row) => (
                  <PositionRow key={`${row.run_id}/${row.table_id}/${row.row_id}`} row={row} several={several} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
      {report.other_reminders.length > 0 && <OtherReminders items={report.other_reminders} several={several} />}
      <section aria-labelledby="bid-notes-heading" className={`${CARD} px-4 py-3 print:px-0`}>
        <h3 id="bid-notes-heading" className="text-headline text-ink">
          {t('How this list was made')}
        </h3>
        <ul className="mt-2 list-disc pl-5 text-callout text-ink-secondary">
          <li>{report.order_basis}</li>
          {report.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>
    </article>
  );
}
