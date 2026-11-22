/** The statuses of a project: their labels, icons and badge tones. */
import { CircleCheck, CircleDashed } from 'lucide-react';
import { msg, t } from '../../i18n/messages.ts';
import type { BadgeTone } from '../../components/Badge.tsx';
import type { StatusOption } from '../../components/StatusSelect.tsx';
import type { LucideIcon } from 'lucide-react';
import type { Project } from '../../services/apiTypes.ts';

export const PROJECT_STATUS: Readonly<Record<Project['status'], { label: string; icon: LucideIcon; tone: BadgeTone }>> = Object.freeze({
  in_progress: { label: msg('In progress'), icon: CircleDashed, tone: 'accent' },
  finished: { label: msg('Finished'), icon: CircleCheck, tone: 'neutral' },
});

/** The statuses to choose from, in the UI language. */
export function projectStatusOptions(): StatusOption<Project['status']>[] {
  return (Object.keys(PROJECT_STATUS) as Project['status'][]).map((value) => ({ value, ...PROJECT_STATUS[value], label: t(PROJECT_STATUS[value].label) }));
}
