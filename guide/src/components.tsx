import { useRef, type MouseEvent, type ReactNode } from 'react';
import type { Definition, GuidePage, Section } from './content';
import type { Translate } from './i18n';
import { Icon } from './Icon';
import { ScriptCode } from './ScriptCode';
import { imageLabels } from './imageLabels';
import { imageSizes } from './firstTranslationImageLabels';

export function GuideLink({ href, children, className, current, onNavigate }: {
  href: string; children: ReactNode; className?: string; current?: boolean; onNavigate?: () => void;
}) {
  function follow(event: MouseEvent<HTMLAnchorElement>) {
    if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    history.pushState(null, '', href);
    window.dispatchEvent(new PopStateEvent('popstate'));
    onNavigate?.();
  }
  return <a href={href} className={className} aria-current={current ? 'page' : undefined} onClick={follow}>{children}</a>;
}

export function Notice({ children, t }: { children: ReactNode; t: Translate }) {
  return <aside className="notice"><Icon name="info" className="notice-icon" /><div><strong>{t('guide.note')}</strong><p>{children}</p></div></aside>;
}

export function GuideImage({ src, caption, t, language }: { src: string; caption: string; t: Translate; language: string }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const labels = language === 'ja' ? [] : imageLabels[src] ?? [];
  const [width, height] = imageSizes[src] ?? [934, 796];
  function picture() {
    return <span className="guide-image-picture">
      <img src={src} alt={[caption, ...labels.map(label => t(label.text))].join(' ')} loading="lazy" decoding="async" />
      {labels.length > 0 && <svg className="guide-image-labels" viewBox={`0 0 ${width} ${height}`} aria-hidden="true">
        {labels.map(label => <g key={`${label.x}-${label.y}`}>
          <rect x={label.x} y={label.y} width={label.width} height={label.height} fill={label.background ?? (label.button ? '#2b2b2b' : '#1f1f1f')} />
          <text x={label.button ? label.x + label.width / 2 : label.x + 3} y={label.y + label.height / 2} textAnchor={label.button ? 'middle' : 'start'} dominantBaseline="central" fontSize={label.fontSize ?? 18}>{t(label.text)}</text>
        </g>)}
      </svg>}
    </span>;
  }
  return <figure className="guide-image">
    <button type="button" className="guide-image-trigger" aria-label={`${caption} — ${t('guide.image.expand')}`} onClick={() => dialog.current?.showModal()}>
      {picture()}
    </button>
    <figcaption>{caption}<span> · {t('guide.image.expand')}</span></figcaption>
    <dialog ref={dialog} className="guide-image-dialog" aria-label={caption} onClick={event => { if (event.target === event.currentTarget) dialog.current?.close(); }}>
      <form method="dialog"><button autoFocus>{t('guide.image.close')}</button></form>
      {picture()}
    </dialog>
  </figure>;
}

// Render button symbols as inline Font Awesome icons, inheriting the text color and size.
function InlineText({ text }: { text: string }) {
  return <>{text.split(/([▶→←])/).map((part, index) => {
    const name = part === '▶' ? 'play' : part === '→' ? 'arrowRight' : part === '←' ? 'arrowLeft' : null;
    return name ? <Icon key={index} name={name} /> : part;
  })}</>;
}

function DefinitionList({ items, t }: { items: Definition[]; t: Translate }) {
  return <dl className="definitions">{items.map(item => <div key={item.label}><dt><InlineText text={t(item.label)} /></dt><dd><InlineText text={t(item.body)} /></dd></div>)}</dl>;
}

export function GuideSection({ section, t, language }: { section: Section; t: Translate; language: string }) {
  return <section id={section.id} className="guide-section" aria-labelledby={`${section.id}-title`}>
    {section.step && <div className="step-label">{t('guide.step')} {String(section.step).padStart(2, '0')}</div>}
    <h2 id={`${section.id}-title`}><InlineText text={t(section.title)} /></h2>
    {section.blocks.map((block, index) => {
      switch (block.kind) {
        case 'image': return <GuideImage key={index} src={block.src} caption={t(block.caption)} t={t} language={language} />;
        case 'paragraph': return <p key={index}><InlineText text={t(block.text)} /></p>;
        case 'guideReference': return <p key={index}>{t('guide.inlineReference').split('{guide}').map((part, partIndex) => <span key={partIndex}>{partIndex > 0 && <GuideLink href={`/${language}/guide/${block.slug}${block.anchor ? `#${block.anchor}` : ''}`}>{t(block.label)}</GuideLink>}{part}</span>)}</p>;
        case 'code': return <ScriptCode key={index} source={t(block.text)} />;
        case 'notice': return <Notice key={index} t={t}><InlineText text={t(block.text)} /></Notice>;
        case 'definitions': return <div key={index}>{block.title && <h3>{t(block.title)}</h3>}<DefinitionList items={block.items} t={t} /></div>;
        case 'links': return <div key={index} className="resource-links"><h3>{t(block.title)}</h3><ul>{block.items.map(item => <li key={item.href}><a href={item.href} target="_blank" rel="noreferrer">{t(item.label)} <Icon name="externalLink" /></a></li>)}</ul></div>;
        case 'guideLinks': return <div key={index} className="resource-links"><h3>{t(block.title)}</h3><ul>{block.items.map(item => <li key={item.slug}><GuideLink href={`/${language}/guide/${item.slug}`}>{t(item.label)} <Icon name="arrowRight" /></GuideLink></li>)}</ul></div>;
        case 'table': return <div key={index} className="table-wrap"><table><caption className="sr-only">{t(section.title)}</caption><thead><tr>{block.columns.map(key => <th key={key} scope="col">{t(key)}</th>)}</tr></thead><tbody>{block.rows.map(row => <tr key={row.label}><th scope="row"><span className="button-label">{t(row.label)}</span></th><td>{t(row.body)}</td></tr>)}</tbody></table></div>;
      }
    })}
  </section>;
}

export function PageToc({ sections, t, active }: { sections: Section[]; t: Translate; active: string }) {
  if (!sections.length) return null;
  return <nav className="page-toc" aria-label={t('guide.onThisPage')}><h2>{t('guide.onThisPage')}</h2><ul>{sections.map(section => <li key={section.id}><a href={`#${section.id}`} aria-current={active === section.id ? 'location' : undefined}><InlineText text={t(section.title)} /></a></li>)}</ul></nav>;
}

export function PageNavigation({ previous, next, language, t }: {
  previous?: GuidePage; next?: GuidePage; language: string; t: Translate;
}) {
  return <nav className="page-navigation" aria-label={t('guide.toc')}>
    {previous ? <GuideLink href={`/${language}/guide/${previous.slug}`}><span><Icon name="arrowLeft" /> {t('guide.previous')}</span><strong>{t(previous.title)}</strong></GuideLink> : <span />}
    {next && <GuideLink href={`/${language}/guide/${next.slug}`} className="next-page"><span>{t('guide.next')} <Icon name="arrowRight" /></span><strong>{t(next.title)}</strong></GuideLink>}
  </nav>;
}
