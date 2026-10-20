import { BrandLogo } from './BrandLogo';
import { GuideLink } from './components';
import { Icon } from './Icon';
import { languages, type Translate } from './i18n';
import { siteUrl } from './urls';
import './product.css';

const distributionUrl = 'https://ikumyon.github.io/IkumyonTools/tool.html?tool=autolingua2';

function DistributionBadge({ t }: { t: Translate }) {
  return <a className="distribution-badge" href={distributionUrl}>
    <Icon name="externalLink" />
    <span><small>{t('product.get')}</small><strong>IkumyonTools</strong></span>
    <Icon name="arrowRight" />
  </a>;
}

export function ProductPage({ t, language, theme, toggleTheme, changeLanguage }: {
  t: Translate; language: string; theme: 'light' | 'dark';
  toggleTheme: () => void; changeLanguage: (language: string) => void;
}) {
  const guide = `/${language}/guide`;
  return <div className="product-page">
    <a className="skip-link" href="#product-content">{t('guide.skipToContent')}</a>
    <header className="site-header product-header">
      <GuideLink href={`/${language}/`} className="brand"><BrandLogo t={t} theme={theme} /></GuideLink>
      <div className="header-actions">
        <GuideLink className="product-guide-link" href={guide}>{t('guide.label')}</GuideLink>
        <label className="language-select"><Icon name="language" /><span className="sr-only">{t('guide.language')}</span>
          <select value={language} onChange={event => changeLanguage(event.target.value)}>
            {languages.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}
          </select>
        </label>
        <button className="theme-toggle" onClick={toggleTheme} aria-label={t(theme === 'dark' ? 'guide.theme.switchToLight' : 'guide.theme.switchToDark')}>
          <Icon name={theme === 'dark' ? 'sun' : 'moon'} />
        </button>
      </div>
    </header>
    <main id="product-content" className="product-main">
      <section className="product-hero">
        <div className="product-intro">
          <p className="product-eyebrow">AUTOlingua Desktop <span>Windows / Linux</span></p>
          <h1>{language === 'ja' ? t('product.headline').split(/(?<=、)/u).map((phrase, index) =>
            <span className="product-headline-phrase" key={index}>{phrase}</span>,
          ) : t('product.headline')}</h1>
          <p className="product-lead">{t('product.description')}</p>
          <div className="product-actions"><DistributionBadge t={t} /><GuideLink href={`${guide}/setup`} className="product-text-link">{t('guide.readSetup')} <Icon name="arrowRight" /></GuideLink></div>
          <p className="product-distribution-note">{t('product.destination')}</p>
        </div>
        <figure className="product-screen">
          <div className="product-screen-bar"><span /><span /><span /><strong>AUTOlingua Desktop</strong></div>
          <img src={siteUrl('/images/translation/overview.webp')} alt={t('product.screen')} width="1876" height="1079" fetchPriority="high" />
          <figcaption>{t('product.sample')}</figcaption>
        </figure>
      </section>
      <section className="product-workflow" aria-label={t('product.features')}>
        <div><span>01</span><p>{t('product.flow.import')}</p></div>
        <Icon name="arrowRight" />
        <div><span>02</span><p>{t('product.flow.translate')}</p></div>
        <Icon name="arrowRight" />
        <div><span>03</span><p>{t('product.flow.export')}</p></div>
      </section>
      <section className="product-feature product-feature-text">
        <div className="product-feature-heading"><p className="product-eyebrow">01 / TRANSLATE</p><h2>{t('product.translate.title')}</h2></div>
        <div><p>{t('product.translate.body')}</p><div className="product-tags"><span>OpenAI</span><span>Gemini</span><span>Claude</span></div><GuideLink href={`${guide}/translation`}>{t('guide.label')} <Icon name="arrowRight" /></GuideLink></div>
      </section>
      <section className="product-feature">
        <div className="product-feature-copy"><p className="product-eyebrow">02 / UPDATE</p><h2>{t('product.update.title')}</h2><p>{t('product.update.body')}</p><GuideLink href={`${guide}/source-updates`}>{t('details.updates.title')} <Icon name="arrowRight" /></GuideLink></div>
        <figure><img src={siteUrl('/images/projects/source-diff.webp')} alt={t('details.images.sourceDiff')} width="1654" height="1079" loading="lazy" /><figcaption>{t('product.sample')}</figcaption></figure>
      </section>
      <section className="product-feature product-feature-reverse">
        <div className="product-feature-copy"><p className="product-eyebrow">03 / COMPARE</p><h2>{t('product.compare.title')}</h2><p>{t('product.compare.body')}</p><GuideLink href={`${guide}/glossary-tone`}>{t('glossaryTone.title')} <Icon name="arrowRight" /></GuideLink></div>
        <figure><img src={siteUrl('/images/translation/model-comparison.webp')} alt={t('details.images.modelComparison')} width="1504" height="1079" loading="lazy" /><figcaption>{t('product.sample')}</figcaption></figure>
      </section>
      <section className="product-start">
        <div><p className="product-eyebrow">GET STARTED</p><h2>{t('product.start.title')}</h2><p>{t('product.start.body')}</p><p className="product-ai-note">{t('product.ai')}</p></div>
        <div className="product-start-actions"><DistributionBadge t={t} /><GuideLink href={guide}>{t('guide.label')} <Icon name="arrowRight" /></GuideLink></div>
      </section>
    </main>
    <footer className="product-footer"><span>AUTOlingua Desktop</span><nav aria-label={t('product.links')}><GuideLink href={guide}>{t('guide.label')}</GuideLink><a href="https://github.com/Ikumyon/AutoLingua2">GitHub <Icon name="externalLink" /></a><a href={distributionUrl}>IkumyonTools <Icon name="externalLink" /></a></nav></footer>
  </div>;
}
