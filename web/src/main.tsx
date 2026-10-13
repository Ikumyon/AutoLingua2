import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { Streamdown, CodeBlock, defaultComponents, type Components, type CustomRendererProps } from 'streamdown';
import { code } from '@streamdown/code';
import { createMathPlugin } from '@streamdown/math';
import { mermaid } from '@streamdown/mermaid';
import { cjk } from '@streamdown/cjk';
import 'katex/dist/katex.min.css';
import './style.css';
import { ChatContext, snapshotSchema, useChat, useLabel, display, type Item, type NativeBridge, type Snapshot, type UiAction } from './bridge';
import { HtmlUI, StructuredUI, Value, renderingInstructions } from './genui';
import { Copy } from './copy';

const markdownComponents: Components = {
  code: ({ children, className, ...props }) => {
    const language = className?.match(/language-(\S+)/)?.[1];
    if (language === 'json-ui' || language === 'html' || language === 'mermaid') {
      const Code = defaultComponents.code;
      return <Code {...props} className={className}>{children}</Code>;
    }
    if (!language) return <code className={className}>{children}</code>;
    const text = typeof children === 'string' ? children.replace(/\n$/, '') : '';
    return <CodeBlock code={text} language={language} lineNumbers><Copy text={text} /></CodeBlock>;
  },
  a: ({ href, children }) => {
    const { act } = useChat();
    return <a href={href} onClick={event => {
      event.preventDefault();
      if (href && /^https?:\/\//i.test(href)) act({ type: 'open_link', url: href });
    }}>{children}</a>;
  },
  table: ({ children }) => {
    const ref = useRef<HTMLTableElement>(null);
    return <section className="markdown-table"><Copy label="table" text={() => {
      const table = ref.current;
      if (table === null) return null;
      return Array.from(table.rows).map(row => Array.from(row.cells).map(cell => {
        const value = cell.innerText;
        return /[\t\n"]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
      }).join('\t')).join('\n');
    }} /><div className="horizontal-scroll"><table ref={ref}>{children}</table></div></section>;
  },
};

const math = createMathPlugin({ singleDollarTextMath: true });
function Markdown({ text, itemId }: { text: string; itemId: string }) {
  const [selectedMath, setSelectedMath] = useState<string | null>(null);
  const plugins = useMemo(() => ({ code, math, mermaid, cjk, renderers: [
    { language: 'json-ui', component: ({ code: source, isIncomplete }: CustomRendererProps) => isIncomplete
      ? <pre>{source}</pre> : <StructuredUI source={source} itemId={itemId} /> },
    { language: 'html', component: ({ code: source, isIncomplete }: CustomRendererProps) => isIncomplete
      ? <pre>{source}</pre> : <HtmlUI source={source} /> },
  ] }), [itemId]);
  return <div className="markdown" onClick={event => {
    if (event.target instanceof Element) {
      const annotation = event.target.closest('.katex')?.querySelector('annotation[encoding="application/x-tex"]');
      if (annotation?.textContent) setSelectedMath(annotation.textContent);
    }
  }}>
    <Streamdown mode="static" parseIncompleteMarkdown={false} skipHtml plugins={plugins} components={markdownComponents}
      lineNumbers controls={{ code: false, table: false, mermaid: { copy: false, download: false, fullscreen: true, panZoom: true }, image: false }}>
      {text}
    </Streamdown>
    {selectedMath !== null && <Copy text={selectedMath} label="math" />}
  </div>;
}

function Message({ item }: { item: Extract<Item, { kind: 'message' }> }) {
  const [source, setSource] = useState(false); const label = useLabel();
  const { snapshot } = useChat();
  return <article className={`message ${item.role}`}>
    {item.role === 'assistant' && <header className="message-header">{item.icon && <img src={item.icon} width="20" height="20" alt="" />}AI <span>{item.model}</span></header>}
    {item.role !== 'user' && item.role !== 'assistant' && <header>{label(item.role)}</header>}
    {item.role === 'assistant' ? <>
      <div hidden={source}><Markdown text={item.text} itemId={item.id} /></div>
      {source && <pre className="source">{item.text}</pre>}
      <footer><Copy text={item.text} /><button type="button" className="icon-button" title={label('markdown')} aria-label={label('markdown')} aria-pressed={source} onClick={() => setSource(value => !value)}>
        <img src={snapshot.markdownIcon} width="20" height="20" alt="" />
      </button></footer>
    </> : <p className="plain-message">{item.text}</p>}
  </article>;
}

function Operation({ item }: { item: Extract<Item, { kind: 'operation' }> }) {
  const { act } = useChat(); const label = useLabel(); const document = item.document;
  const [selected, setSelected] = useState(() => new Set(document.changes.map(change => change.id)));
  const pending = document.status === 'awaiting_confirmation';
  return <section className="operation gen-card">
    <header><h3>{label(`name:${document.name}`)}</h3><span>{label(`status:${document.status}`)}</span></header>
    <label className="gen-check"><input type="checkbox" checked={document.changes.every(change => selected.has(change.id))} disabled={!pending}
      onChange={event => setSelected(event.target.checked ? new Set(document.changes.map(change => change.id)) : new Set())} />{label('selectAll')}</label>
    <div className="change-list">{document.changes.map(change => <div className="change" key={change.id}>
      <label className="gen-check"><input type="checkbox" checked={selected.has(change.id)} disabled={!pending} onChange={event => setSelected(previous => {
        const next = new Set(previous); if (event.target.checked) next.add(change.id); else next.delete(change.id); return next;
      })} />{change.label ?? change.key ?? change.id}</label>
      <div className="change-values"><section><small>{label('before')}</small><Value value={change.before} /></section><section><small>{label('after')}</small><Value value={change.after} /></section></div>
    </div>)}</div>
    <footer>
      <button disabled={!document.changes.some(change => change.language)} onClick={() => act({ type: 'view_operation', id: document.operation_id })}>{label('view')}</button>
      <button className="primary" disabled={!pending || selected.size === 0} onClick={() => act({ type: 'apply_operation', id: document.operation_id, ids: document.changes.filter(change => selected.has(change.id)).map(change => change.id) })}>{label('apply')}</button>
      <button disabled={!pending} onClick={() => act({ type: 'discard_operation', id: document.operation_id })}>{label('discard')}</button>
      {document.can_undo && <button onClick={() => act({ type: 'undo_operation', id: document.operation_id })}>{label('undo')}</button>}
    </footer>
  </section>;
}

function Job({ item }: { item: Extract<Item, { kind: 'job' }> }) {
  const { act } = useChat(); const label = useLabel(); const document = item.document;
  const running = document.status === 'waiting' || document.status === 'running';
  const progress = document.total ? (document.completed ?? 0) / document.total : 0;
  return <section className="job gen-card"><header><h3>{label(`name:${document.kind}`)}</h3><span>{label(`status:${document.status}`)}</span></header>
    {running && <progress max={1} value={document.total ? progress : undefined} />}
    {!!document.total && <p>{document.completed ?? 0} / {document.total}</p>}
    {document.error && <p className="error">{document.error}</p>}
    {!!document.results?.length && <details><summary>{label('results')}</summary><Value value={document.results} /></details>}
    {running && <button onClick={() => act({ type: 'cancel_job', id: document.id })}>{label('cancel')}</button>}
  </section>;
}

function Transcript() {
  const { snapshot } = useChat(); const label = useLabel();
  const scroll = useRef<HTMLDivElement>(null); const content = useRef<HTMLDivElement>(null);
  const follow = useRef(true); const previous = useRef<string | null>(null); const [latest, setLatest] = useState(false);
  const end = () => { const node = scroll.current; if (node) { node.scrollTop = node.scrollHeight; follow.current = true; setLatest(false); } };
  useLayoutEffect(() => {
    const first = snapshot.items[0]?.id ?? null;
    if (first !== previous.current) { follow.current = true; setLatest(false); previous.current = first; }
    if (follow.current) end(); else setLatest(true);
  }, [snapshot.items]);
  useEffect(() => {
    const node = content.current; if (!node) return;
    const observer = new ResizeObserver(() => { if (follow.current) end(); });
    observer.observe(node); return () => observer.disconnect();
  }, []);
  return <><div className="transcript" ref={scroll} onScroll={() => {
    const node = scroll.current; if (!node) return;
    follow.current = node.scrollHeight - node.scrollTop - node.clientHeight < 48;
    if (follow.current) setLatest(false);
  }}><div className="transcript-content" ref={content}>
    {snapshot.items.length === 0 && <p className="empty">{label('empty')}</p>}
    {snapshot.items.map(item => item.kind === 'message' ? <Message key={item.id} item={item} /> : item.kind === 'operation' ? <Operation key={item.id} item={item} /> : <Job key={item.id} item={item} />)}
    {snapshot.busy && <p className="thinking" role="status">{label('thinking')}</p>}
  </div></div>{latest && <button className="latest" onClick={end}>{label('latest')} ↓</button>}</>;
}

function App({ bridge }: { bridge: NativeBridge }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const act = useMemo(() => (action: UiAction) => bridge.act(JSON.stringify(action)), [bridge]);
  useEffect(() => {
    bridge.changed.connect(payload => {
      try {
        const value: unknown = JSON.parse(payload);
        const next = snapshotSchema.parse(value);
        for (const [name, color] of Object.entries(next.colors)) document.documentElement.style.setProperty(`--chat-${name}`, color);
        document.documentElement.classList.toggle('dark', next.dark);
        document.documentElement.style.colorScheme = next.dark ? 'dark' : 'light';
        setSnapshot(next); setError(null);
      } catch (failure) { setError(failure instanceof Error ? failure.message : display(failure)); }
    });
    bridge.ready(renderingInstructions);
  }, [bridge]);
  if (error !== null) return <pre className="error">{error}</pre>;
  if (snapshot === null) return null;
  return <ChatContext.Provider value={{ snapshot, act }}><Transcript /></ChatContext.Provider>;
}

const root = document.getElementById('root');
if (root === null) throw new Error('Missing chat root');
const renderer = createRoot(root);
new window.QWebChannel(window.qt.webChannelTransport, channel => renderer.render(<App bridge={channel.objects.chat} />));
