import { ErrorState } from '../../components/ErrorState.tsx';
import { KeyValueList } from '../../components/KeyValueList.tsx';
import { LoadingState } from '../../components/LoadingState.tsx';
import { Section } from '../../components/Section.tsx';
import { StatusBadge } from '../../components/StatusBadge.tsx';
import { TokenList } from '../../components/TokenList.tsx';
import { useApiResource } from '../../hooks/useApiResource.ts';
import { t } from '../../i18n/messages.ts';
import { getHealth } from '../../services/catalogService.ts';
import { useSession } from '../../stores/useSession.ts';
import { formatCount } from '../../utils/format.ts';

/** Settings, System: the backend's status (GET /health), version, checks and profiles. */
export function SystemPanel() {
  const health = useApiResource((signal) => getHealth({ signal }), []);
  // The session checked the server's health before the application opened: shown until this
  // panel's own check answers, so the panel has no loading state of its own.
  const { health: known } = useSession();
  if (health.error) {
    return <ErrorState error={health.error} title={t('The backend did not answer the health check')} onRetry={health.reload} />;
  }
  const status = health.data ?? known;
  if (!status) {
    return <LoadingState variant="list" label={t('Checking the backend…')} />;
  }
  return (
    <Section title={t('Backend')} padded>
      <KeyValueList
        items={[
          { label: t('Status'), value: <StatusBadge kind="health" status={status.status} /> },
          { label: t('Version'), value: status.version, mono: true },
          { label: t('Detectors registered'), value: formatCount(status.detector_count) },
          { label: t('Profiles'), value: <TokenList items={status.profiles} /> },
          {
            label: t('Default profile'),
            value: status.default_profile_id ?? t('Not reported by this server'),
            mono: Boolean(status.default_profile_id),
          },
        ]}
      />
    </Section>
  );
}
