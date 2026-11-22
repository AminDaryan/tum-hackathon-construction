import { Copy, Mail, Monitor, MessageCircle, Share2 } from 'lucide-react';
import { useState } from 'react';
import { Button } from '../components/Button.tsx';
import { useI18n } from '../i18n/useI18n.ts';

const APP_URL = 'https://twb-hackathon.fly.dev/';

/** A lightweight handoff for the narrow touch screen where the full workbench is not useful. */
export function PhoneLanding({ onContinue }: { onContinue: () => void }) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);
  const shareText = t('phone.shareText');

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(APP_URL);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
    }
  };

  const share = async () => {
    if (!navigator.share) return;
    try {
      await navigator.share({ title: t('app.name'), text: shareText, url: APP_URL });
    } catch {
      // Closing the native share sheet is not an error for the page.
    }
  };

  return (
    <section className="phone-landing" aria-labelledby="phone-landing-title">
      <div className="phone-landing-card">
        <div className="phone-landing-mark" aria-hidden="true"><Monitor className="size-7" strokeWidth={1.5} /></div>
        <p className="text-callout font-semibold tracking-wide text-accent">{t('app.name')}</p>
        <h1 id="phone-landing-title" className="mt-2 text-title">{t('phone.title')}</h1>
        <p className="mt-3 text-body text-ink-secondary">{t('phone.description')}</p>
        <div className="mt-6 grid gap-2">
          <Button variant="primary" size="lg" icon={MessageCircle} onPress={() => window.open(`https://wa.me/?text=${encodeURIComponent(`${shareText} ${APP_URL}`)}`, '_blank', 'noopener,noreferrer')}>
            {t('phone.whatsapp')}
          </Button>
          <Button variant="secondary" size="lg" icon={Mail} onPress={() => { window.location.href = `mailto:?subject=${encodeURIComponent(t('phone.emailSubject'))}&body=${encodeURIComponent(`${shareText}\n\n${APP_URL}`)}`; }}>
            {t('phone.email')}
          </Button>
          {typeof navigator !== 'undefined' && typeof navigator.share === 'function' && (
            <Button variant="secondary" size="lg" icon={Share2} onPress={share}>{t('phone.share')}</Button>
          )}
          <Button variant="secondary" size="lg" icon={Copy} onPress={copyLink}>{copied ? t('phone.copied') : t('phone.copy')}</Button>
        </div>
        <button type="button" className="phone-landing-continue" onClick={onContinue}>{t('phone.continue')}</button>
      </div>
    </section>
  );
}
