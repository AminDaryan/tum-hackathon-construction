import { Button as AriaButton } from 'react-aria-components';
import { HIT_MIN_HEIGHT } from '../../../components/hitTarget.ts';
import { cx } from '../../../utils/classNames.ts';
import { classificationLabel, moneyView, positionsText } from '../../risks/riskModel.ts';
import { TaskSummary } from '../../collaboration/TaskSummary.tsx';
import { PriorityBadge, RiskStatus } from './RiskBits.tsx';
import type { FindingTask, Risk } from '../../../services/apiTypes.ts';

interface RiskRowProps {
  risk: Risk;
  title: string;
  classification: string;
  status: string;
  task?: FindingTask | null;
  selected?: boolean;
  onSelect: (risk: Risk) => void;
}

/**
 * One risk of the Risks list as a full-width button of two lines: the priority badge, the short
 * title and the status; then the positions, the classification, the money when it is known and
 * the finding's task (status, type and assignee) when it has one.
 * The selected risk carries `aria-current`.
 */
export function RiskRow({
  risk,
  title,
  classification,
  status,
  task = null,
  selected = false,
  onSelect,
}: RiskRowProps) {
  const money = moneyView(risk.money);
  const where = positionsText(risk, 2);
  return (
    <AriaButton
      aria-current={selected ? 'true' : undefined}
      data-risk-id={risk.risk_id}
      onPress={() => onSelect(risk)}
      className={cx(
        'state-layer flex cursor-pointer w-full flex-col gap-1 px-4 py-2 text-left',
        HIT_MIN_HEIGHT,
        selected ? 'bg-accent-subtle shadow-[inset_3px_0_0_var(--color-accent)]' : 'bg-surface',
      )}
    >
      <span className="flex w-full min-w-0 items-center gap-3">
        <PriorityBadge tier={risk.tier} className="w-18 justify-center" />
        <span title={risk.title} className="min-w-0 flex-1 truncate text-body font-medium text-ink">
          {title}
        </span>
        <RiskStatus status={status} />
      </span>
      <span className="flex min-w-0 flex-wrap gap-x-4 gap-y-0.5 text-caption text-ink-secondary @md:pl-21">
        {where && <span className="sheet-figures">{where}</span>}
        <span>{classificationLabel(classification)}</span>
        {money.kind !== 'unknown' && <span className="sheet-figures">{money.text}</span>}
        <TaskSummary task={task} />
      </span>
    </AriaButton>
  );
}
