import { CopyButton } from '../../../components/CopyButton.tsx';
import { Disclosure } from '../../../components/Disclosure.tsx';
import { t } from '../../../i18n/messages.ts';
import { formatCount } from '../../../utils/format.ts';
import type { OpenQuestion } from '../../../services/apiTypes.ts';

type Question = Pick<OpenQuestion, 'question'> & Partial<Pick<OpenQuestion, 'kind' | 'topic' | 'positions' | 'positions_total'>>;

/** The questions as plain text, one paragraph each, with the positions they concern. */
function questionsText(questions: Question[]): string {
  return questions
    .map((question) => {
      const positions = question.positions?.length ? ` (${question.positions.join(', ')})` : '';
      return `${question.question}${positions}`;
    })
    .join('\n\n');
}

interface ClientQuestionsProps {
  questions?: Question[];
}

/**
 * The report's open questions to the client, grouped by what they need (a missing drawing, a
 * document of another trade), with a button that copies all of them; closed until asked for.
 */
export function ClientQuestions({ questions }: ClientQuestionsProps) {
  if (!questions?.length) return null;
  return (
    <Disclosure
      size="headline"
      className="border-t border-hairline pt-3"
      title={
        <>
          {t('Questions for the client')} <span className="font-normal tabular-nums text-ink-secondary">{formatCount(questions.length)}</span>
        </>
      }
    >
      <div className="-ml-3">
        <CopyButton text={questionsText(questions)} label={t('Copy all questions')} />
      </div>
      <ul className="space-y-3">
        {questions.map(({ positions = [], positions_total: total = 0, ...question }) => (
          <li key={`${question.kind}:${question.topic}:${question.question}`} className="relative min-h-8 pr-10 text-callout text-ink pointer-coarse:min-h-12 pointer-coarse:pr-14">
            <span className="absolute right-0 top-0">
              <CopyButton iconOnly text={questionsText([{ ...question, positions: [...new Set(positions)] }])} label={t('Copy question')} />
            </span>
            <p>{question.question}</p>
            {positions.length > 0 && (
              <p className="mt-0.5 text-caption text-ink-secondary">
                {positions.join(', ')}
                {total > positions.length
                  ? ` ${t('and {count} more', { count: formatCount(total - positions.length) })}`
                  : ''}
              </p>
            )}
          </li>
        ))}
      </ul>
    </Disclosure>
  );
}
