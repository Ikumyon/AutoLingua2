import type { Translate } from './i18n';

export function BrandLogo({ t }: { t: Translate }) {
  return <span className="brand-logo"><img src="/brand/autolingua-desktop.webp" alt={t('guide.productName')} width="1834" height="439" fetchPriority="high" /></span>;
}
