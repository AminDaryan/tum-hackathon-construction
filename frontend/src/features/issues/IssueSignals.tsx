import { KeyValueList } from '../../components/KeyValueList.tsx';
import { t } from '../../i18n/messages.ts';
import { formatScore } from '../../utils/format.ts';
import type { ValidationIssue } from '../../services/apiTypes.ts';

interface IssueSignalsProps {
  issue: ValidationIssue;
}

/**
 * Extraction confidence and anomaly score, shown only when the issue carries them. Neither is
 * ever rendered as a percentage: confidence is reported by OCR/PDF engines only, and an anomaly
 * score is a raw detector score unless it is calibrated against a documented reference.
 */
export function IssueSignals({ issue }: IssueSignalsProps) {
  const { extraction_confidence: confidence, anomaly_score: score } = issue;
  const hasConfidence = typeof confidence === 'number';
  if (!hasConfidence && !score) {
    return null;
  }
  return (
    <div className="space-y-3">
      {hasConfidence && (
        <KeyValueList
          layout="inline"
          items={[
            {
              label: t('Extraction confidence'),
              value: (
                <>
                  <span className="font-mono tabular-nums">{formatScore(confidence)}</span>
                  <span className="block text-caption text-ink-tertiary">
                    {t('Lowest confidence the extraction engine reported for the cells involved (0 to 1).')}
                  </span>
                </>
              ),
            },
          ]}
        />
      )}
      {score && (
        <KeyValueList
          layout="inline"
          items={[
            { label: t('Anomaly score'), value: <span className="font-mono tabular-nums">{formatScore(score.value)}</span> },
            score.threshold != null && {
              label: t('Threshold'),
              value: <span className="font-mono tabular-nums">{formatScore(score.threshold)}</span>,
            },
            { label: t('Method'), value: score.method, mono: true },
            { label: t('Interpretation'), value: score.interpretation },
            {
              label: t('Calibration'),
              value: score.calibrated
                ? t('Calibrated against {reference}', { reference: score.calibration_reference ?? '' })
                : t('Not calibrated: a raw score, not a probability of error.'),
            },
          ]}
        />
      )}
    </div>
  );
}
