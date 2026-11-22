import { SearchX } from 'lucide-react';
import { useLocation } from 'react-router-dom';
import { ButtonLink } from '../components/Button.tsx';
import { EmptyState } from '../components/EmptyState.tsx';
import { useDocumentTitle } from '../hooks/useDocumentTitle.ts';
import { useI18n } from '../i18n/useI18n.ts';
import { usePageTitle } from './pageTitle.tsx';

/**
 * Fallback for unknown routes and for the pages of a project that does not exist
 * (`projectMissing`), which it names instead of the address.
 */
export function NotFoundPage({ projectMissing = false }: { projectMissing?: boolean }) {
  const { t } = useI18n();
  useDocumentTitle(t('page.notFound'));
  usePageTitle({ title: t('nav.notFound') });
  const { pathname } = useLocation();
  return (
    <>
      <EmptyState
        icon={SearchX}
        title={t('page.notFound.empty')}
        description={
          projectMissing ? (
            t('This project does not exist.')
          ) : (
            <>
              {t('page.notFound.noMatch')} <span className="font-mono text-callout">{pathname}</span>.
            </>
          )
        }
        action={
          <ButtonLink to="/projects" variant="primary">
            {t('page.notFound.action')}
          </ButtonLink>
        }
      />
    </>
  );
}
