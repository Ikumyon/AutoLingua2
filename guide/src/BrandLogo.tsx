import type { Translate } from './i18n';
import { siteUrl } from './urls';

export function BrandLogo({ t, theme }: { t: Translate; theme: 'light' | 'dark' }) {
  return <span className="brand-logo"><img src={siteUrl(`/brand/autolingua-desktop.svg${theme === 'dark' ? '#dark' : ''}`)} alt={t('guide.productName')} width="920" height="260" fetchPriority="high" /></span>;
}
