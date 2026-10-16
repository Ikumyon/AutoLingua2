import { useEffect, useRef, useState } from 'react';
import { pages, referencePages } from './content';
import { fallback, languages, loadDictionary, type Dictionary, type Translate } from './i18n';
import { GuideLink, GuideSection, PageNavigation, PageToc } from './components';
import { Icon } from './Icon';
import { useTheme } from './useTheme';
import { BrandLogo } from './BrandLogo';

function readRoute() {
  const match = /^\/([^/]+)\/guide(?:\/([^/]+))?\/?$/.exec(location.pathname);
  return { language: match?.[1] ?? 'ja', slug: match?.[2] ?? '', valid: Boolean(match) };
}

export default function App() {
  const { theme, toggleTheme } = useTheme();
  const [route, setRoute] = useState(readRoute);
  const [dictionary, setDictionary] = useState<Dictionary | null>(null);
  const [error, setError] = useState(false);
  const [retry, setRetry] = useState(0);
  const [menuOpen, setMenuOpen] = useState(false);
  const [activeSection, setActiveSection] = useState('');
  const main = useRef<HTMLElement>(null);
  const firstRoute = useRef(true);
  const languageSupported = languages.some(language => language.code === route.language);
  const language = languageSupported ? route.language : 'ja';
  const t: Translate = key => (dictionary ?? fallback)[key];
  const pageIndex = pages.findIndex(page => page.slug === route.slug);
  const page = pages[pageIndex] ?? referencePages.find(page => page.slug === route.slug);
  const parentPage = pages.find(item => item.slug === page?.parentSlug);
  const home = route.valid && languageSupported && !route.slug;
  const notFound = !route.valid || !languageSupported || (!home && !page);

  useEffect(() => {
    if (location.pathname === '/') history.replaceState(null, '', '/ja/guide');
    setRoute(readRoute());
    const update = () => { setRoute(readRoute()); setMenuOpen(false); };
    window.addEventListener('popstate', update);
    return () => window.removeEventListener('popstate', update);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setDictionary(null);
    setError(false);
    loadDictionary(language, controller.signal).then(setDictionary).catch(() => {
      if (!controller.signal.aborted) setError(true);
    });
    return () => controller.abort();
  }, [language, retry]);

  useEffect(() => {
    document.documentElement.lang = language;
    const text = dictionary ?? fallback;
    document.title = `${text[notFound ? 'guide.notFound' : home ? 'guide.home' : page?.title ?? 'guide.notFound']} | ${text['guide.title']}`;
  }, [language, dictionary, home, notFound, page]);

  useEffect(() => {
    if (!dictionary) return;
    let id = location.hash.slice(1);
    try { id = decodeURIComponent(id); } catch { /* Ignore malformed URL escapes. */ }
    const target = id ? document.getElementById(id) : null;
    if (target) target.scrollIntoView();
    else window.scrollTo(0, 0);
    if (!firstRoute.current) main.current?.focus({ preventScroll: true });
    firstRoute.current = false;
    setActiveSection(page?.sections[0]?.id ?? '');
    const observer = new IntersectionObserver(entries => {
      const visible = entries.filter(entry => entry.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setActiveSection(visible[0].target.id);
    }, { rootMargin: '-90px 0px -55% 0px' });
    document.querySelectorAll('.guide-section').forEach(section => observer.observe(section));
    return () => observer.disconnect();
  }, [route.slug, dictionary]);

  return <>
    <a className="skip-link" href="#content">{t('guide.skipToContent')}</a>
    <header className="site-header">
      <GuideLink href={`/${language}/guide`} className="brand"><BrandLogo t={t} /><span className="brand-divider" /><span className="brand-guide">{t('guide.label')}</span></GuideLink>
      <div className="header-actions"><label className="language-select"><Icon name="language" /><span className="sr-only">{t('guide.language')}</span><select value={language} onChange={event => {
        history.pushState(null, '', `/${event.target.value}/guide${route.slug ? `/${route.slug}` : ''}${location.hash}`);
        window.dispatchEvent(new PopStateEvent('popstate'));
      }}>{languages.map(item => <option key={item.code} value={item.code}>{item.label}</option>)}</select></label>
      <button className="theme-toggle" onClick={toggleTheme} aria-label={t(theme === 'dark' ? 'guide.theme.switchToLight' : 'guide.theme.switchToDark')} title={t(theme === 'dark' ? 'guide.theme.switchToLight' : 'guide.theme.switchToDark')}><Icon name={theme === 'dark' ? 'sun' : 'moon'} /></button>
      <button className="menu-toggle" aria-label={t('guide.menu')} aria-expanded={menuOpen} aria-controls="guide-sidebar" onClick={() => setMenuOpen(!menuOpen)}><Icon name={menuOpen ? 'close' : 'menu'} /></button></div>
    </header>
    <div className="layout">
      <aside id="guide-sidebar" className={`sidebar ${menuOpen ? 'is-open' : ''}`}>
        <nav aria-label={t('guide.toc')}>
          <GuideLink href={`/${language}/guide`} current={home} className="home-link">{t('guide.home')}</GuideLink>
          <div className="sidebar-label">{t('guide.toc')}</div>
          <ol>{pages.map((item, index) => <li key={item.slug}><GuideLink href={`/${language}/guide/${item.slug}`} current={page?.slug === item.slug && !notFound}><span className="chapter-number">{String(index + 1).padStart(2, '0')}</span><span>{t(item.title)}{!item.sections.length && <small>{t('guide.preparing')}</small>}</span></GuideLink>{referencePages.filter(reference => reference.parentSlug === item.slug).map(reference => <GuideLink key={reference.slug} href={`/${language}/guide/${reference.slug}`} className="reference-link" current={page?.slug === reference.slug && !notFound}>{t(reference.navTitle ?? reference.title)}</GuideLink>)}</li>)}</ol>
        </nav>
        <div className="sidebar-footer">{t('guide.productName')}</div>
      </aside>
      <main id="content" ref={main} tabIndex={-1}>
        <div className="breadcrumb"><GuideLink href={`/${language}/guide`}>{t('guide.label')}</GuideLink><Icon name="chevronRight" />{parentPage && <><GuideLink href={`/${language}/guide/${parentPage.slug}`}>{t(parentPage.title)}</GuideLink><Icon name="chevronRight" /></>}<span>{t(notFound ? 'guide.notFound' : home ? 'guide.home' : page!.title)}</span></div>
        {!dictionary ? <div className="load-state" role={error ? 'alert' : 'status'}><p>{t(error ? 'guide.loadError' : 'guide.loading')}</p>{error && <button onClick={() => setRetry(value => value + 1)}>{t('guide.retry')}</button>}</div> : notFound ? <><h1>{t('guide.notFound')}</h1><p>{t('guide.notFoundDescription')}</p><GuideLink href={`/${language}/guide`}>{t('guide.home')} <Icon name="arrowRight" /></GuideLink></> : home ? <>
          <div className="guide-hero"><div><div className="eyebrow">{t('guide.productName')}</div><h1>{t('guide.label')}</h1><p className="lead">{t('guide.description')}</p>
          <GuideLink href={`/${language}/guide/setup`} className="primary-link">{t('guide.readSetup')} <Icon name="arrowRight" /></GuideLink></div><img className="hero-mascot" src="/brand/app.webp" alt="" width="320" height="320" /></div>
          <h2 className="home-toc-title">{t('guide.toc')}</h2><div className="chapter-grid">{pages.map((item, index) => <GuideLink key={item.slug} href={`/${language}/guide/${item.slug}`} className="chapter-card"><span className="card-number">{String(index + 1).padStart(2, '0')}</span><strong>{t(item.title)}</strong><span className="card-status">{!item.sections.length ? t('guide.preparing') : <Icon name="arrowRight" />}</span></GuideLink>)}</div>
        </> : <>
          <div className="eyebrow">{parentPage ? t('guide.reference') : `${String(pageIndex + 1).padStart(2, '0')} / ${String(pages.length).padStart(2, '0')}`}</div>
          <h1>{t(page!.title)}</h1>{page!.description && <p className="lead">{t(page!.description)}</p>}
          <div className="mobile-page-toc"><PageToc sections={page!.sections} t={t} active={activeSection} /></div>
          {!page!.sections.length && <div className="empty-state"><span className="status-pill">{t('guide.preparing')}</span><p>{t('guide.preparingDescription')}</p></div>}
          {page!.sections.map(section => <GuideSection key={section.id} section={section} t={t} language={language} />)}
          <PageNavigation previous={parentPage ?? pages[pageIndex - 1]} next={pageIndex >= 0 ? pages[pageIndex + 1] : undefined} language={language} t={t} />
        </>}
        <footer className="content-footer">{t('guide.productName')}<span>{t('guide.label')}</span></footer>
      </main>
      <aside className="right-rail">{dictionary && !notFound && page && <PageToc sections={page.sections} t={t} active={activeSection} />}</aside>
    </div>
  </>;
}
