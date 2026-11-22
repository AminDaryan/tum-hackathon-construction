import { Banner } from '../../components/Banner.tsx';
import { Button } from '../../components/Button.tsx';
import { t } from '../../i18n/messages.ts';
import type { DatasetSummary } from '../../services/apiTypes.ts';

interface ExtractionQualityBannerProps {
  dataset: DatasetSummary;
  onShowDetails: () => void;
}

/**
 * Notice shown when the extraction failed: the server does not validate such a dataset.
 */
export function ExtractionQualityBanner({ dataset, onShowDetails }: ExtractionQualityBannerProps) {
  if (dataset.extraction.quality !== 'failed') return null;
  return (
    <Banner tone="danger" title={t('Extraction failed')}>
      {t('The server does not validate a dataset whose extraction failed.')}{' '}
      <Button variant="link" onPress={onShowDetails}>
        {t('Show how the file was read')}
      </Button>
    </Banner>
  );
}
