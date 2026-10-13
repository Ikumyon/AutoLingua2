import { Children, Component, useId, useMemo, useState, type ReactNode } from 'react';
import { ActionBindingSchema, VisibilityConditionSchema, defineCatalog, type Spec } from '@json-render/core';
import { schema } from '@json-render/react/schema';
import { ActionProvider, defineRegistry, JSONUIProvider, Renderer, useBoundProp, useStateStore, type Components } from '@json-render/react';
import { z } from 'zod';
import { CodeBlock } from 'streamdown';
import { useChat, useLabel, display } from './bridge';
import { Copy } from './copy';

const nullableText = z.string().nullable();
// The catalog validates allowed components/props. The standard renderer also
// needs typed event bindings, visibility and initial state, which are not
// included in the catalog schema's inferred spec type.
const renderSpecSchema = z.object({
  root: z.string(),
  elements: z.record(z.string(), z.object({
    type: z.string(), props: z.record(z.string(), z.unknown()),
    children: z.array(z.string()).optional(), slots: z.record(z.string(), z.array(z.string())).optional(),
    visible: VisibilityConditionSchema.optional(),
    on: z.record(z.string(), z.union([ActionBindingSchema, z.array(ActionBindingSchema)])).optional(),
    repeat: z.object({ statePath: z.string(), key: z.string().optional() }).optional(),
  }).strict()),
  state: z.record(z.string(), z.unknown()).optional(),
}).strict();
export const catalog = defineCatalog(schema, {
  components: {
    Stack: { props: z.object({ direction: z.enum(['vertical', 'horizontal']) }), slots: ['default'], description: 'Responsive layout' },
    Card: { props: z.object({ title: nullableText }), slots: ['default'], description: 'Group related information' },
    Text: { props: z.object({ text: z.string() }), description: 'Plain text, not executable HTML' },
    Table: { props: z.object({ columns: z.array(z.string()), rows: z.array(z.array(z.string())) }), description: 'Tabular information' },
    Chart: { props: z.object({ kind: z.enum(['bar', 'line']), labels: z.array(z.string()), values: z.array(z.number()) }), description: 'Bar or line chart' },
    Compare: { props: z.object({ labels: z.array(z.string()), values: z.array(z.string()) }), description: 'Side by side alternatives' },
    TextInput: { props: z.object({ label: z.string(), value: z.string(), multiline: z.boolean() }), description: 'Editable text; bind value with $bindState' },
    Select: { props: z.object({ label: z.string(), value: z.string(), options: z.array(z.string()) }), description: 'Choose an option; bind value with $bindState' },
    Radio: { props: z.object({ label: z.string(), value: z.string(), options: z.array(z.string()).min(1) }), description: 'Choose one radio option; bind value with $bindState' },
    Collapsible: { props: z.object({ title: z.string(), open: z.boolean() }), slots: ['default'], description: 'Expandable content; bind open with $bindState' },
    Tabs: { props: z.object({ label: z.string(), value: z.string(), options: z.array(z.string()).min(1) }), slots: ['default'], description: 'Switch content; one child per option in the same order; bind value with $bindState' },
    SegmentedControl: { props: z.object({ label: z.string(), value: z.string(), options: z.array(z.string()).min(1) }), description: 'Choose one option in a connected horizontal control; bind value with $bindState' },
    Checkbox: { props: z.object({ label: z.string(), value: z.boolean() }), description: 'Toggle; bind value with $bindState' },
    Slider: { props: z.object({ label: z.string(), value: z.number(), min: z.number(), max: z.number(), step: z.number().positive() }), description: 'Numeric input; bind value with $bindState' },
    Button: { props: z.object({ label: z.string() }), description: 'User-triggered action', events: ['press'] },
  },
  actions: {
    copy_text: { params: z.object({ text: z.string() }), description: 'Copy text on user click' },
    submit: { params: z.object({ instruction: z.string() }), description: 'Send instruction and current form state to AI on user click' },
  },
});

export const renderingInstructions = [
  '回答は読みやすいMarkdownにしてください。挨拶や通常の説明は文章だけで回答してください。コードには言語名を付けてください。',
  '数式はLaTeXで記述し、文中の数式は$...$、独立した数式は開始と終了の$$をそれぞれ単独行に置いて囲んでください。数式はコードブロックやインラインコードに入れないでください。',
  String.raw`数式の区切りに\(...\)や\[...\]は使用しないでください。LaTeXコマンドにはバックスラッシュを使い、百分率は\%と記述してください。`,
  '独立した数式の例：\n$$\n\\frac{150}{200} \\times 100\\% = 75\\%\n$$',
  '操作できる画面が役立つ場合、下記カタログで表現できるものは構造化UIを優先してください。',
  'UI仕様はrootとelementsを持つ完全なJSONを言語名json-uiのフェンスコードブロックに入れてください。JSONLやJSON Patchは使用しません。通常のJSON例にはjsonを使います。',
  '入力のvalueは{$bindState:"/field"}でstateに結び付け、Buttonのon.pressにsubmitまたはcopy_textを指定します。submitはparams.instructionに依頼文、copy_textはparams.textにコピーする文字列を指定します。',
  'Radio・SegmentedControl・Tabsのoptionsは重複しない選択肢文字列、valueはそのいずれかでstateに結び付けます。Tabsのchildrenにはoptionsと同じ順序・同じ数の表示内容を指定してください。Collapsibleのchildrenには折り畳む内容を置き、openは真偽値または{$bindState:"/expanded"}で指定します。',
  '例: {"root":"card","elements":{"card":{"type":"Card","props":{"title":"入力"},"children":["field","send"]},"field":{"type":"TextInput","props":{"label":"希望","value":{"$bindState":"/request"},"multiline":false},"children":[]},"send":{"type":"Button","props":{"label":"相談する"},"children":[],"on":{"press":{"action":"submit","params":{"instruction":"入力内容について回答してください"}}}}},"state":{"request":""}}',
  '対応する部品がない表現に限り、自己完結したHTML・CSS・JavaScriptをhtmlコードブロックで生成できます。',
  'HTMLは隔離して表示され、外部通信、外部ライブラリ、ローカルファイル、アプリAPIは利用できません。',
  '必要な場合だけUIを生成してください。公開・保存・編集は画面表示とは別の操作です。',
  '構造化UIのJSON Schema（使用できる部品とプロパティ）：',
  JSON.stringify(catalog.jsonSchema()),
].join('\n');

const components: Components<typeof catalog> = {
  Stack: ({ props, children }) => <div className={`gen-stack ${props.direction}`}>{children}</div>,
  Card: ({ props, children }) => <section className="gen-card">{props.title && <h3>{props.title}</h3>}{children}</section>,
  Text: ({ props }) => <p>{props.text}</p>,
  Table: ({ props }) => {
    return <div className="gen-table"><Copy label="table" text={() => [props.columns, ...props.rows].map(row => row.join('\t')).join('\n')} />
      <div className="horizontal-scroll"><table><thead><tr>{props.columns.map((column, i) => <th key={i}>{column}</th>)}</tr></thead>
        <tbody>{props.rows.map((row, i) => <tr key={i}>{row.map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div></div>;
  },
  Chart: ({ props }) => {
    const minimum = Math.min(0, ...props.values); const maximum = Math.max(0, ...props.values);
    const span = maximum - minimum || 1;
    const y = (value: number) => 170 - (value - minimum) / span * 140;
    const x = (i: number) => 50 + i * 460 / Math.max(1, props.values.length - 1);
    return <svg className="gen-chart" viewBox="0 0 560 220" role="img" aria-label={props.labels.join(', ')}>
      <line x1="25" y1={y(0)} x2="535" y2={y(0)} stroke="currentColor" opacity=".4" />
      {props.kind === 'line' && <polyline points={props.values.map((value, i) => `${x(i)},${y(value)}`).join(' ')} fill="none" stroke="var(--chat-accent)" strokeWidth="3" />}
      {props.values.map((value, i) => <g key={i}>
        {props.kind === 'bar' ? <rect x={x(i) - Math.min(16, 180 / props.values.length)} y={Math.min(y(value), y(0))} width={Math.min(32, 360 / props.values.length)} height={Math.abs(y(value) - y(0))} fill="var(--chat-accent)" /> : <circle cx={x(i)} cy={y(value)} r="4" fill="var(--chat-accent)" />}
        <text x={x(i)} y={y(value) - 8} textAnchor="middle" fill="currentColor" fontSize="12">{value}</text>
        <text x={x(i)} y="200" textAnchor="middle" fill="currentColor" fontSize="11">{props.labels[i]}</text>
      </g>)}
    </svg>;
  },
  Compare: ({ props }) => <div className="gen-stack horizontal">{props.values.map((value, i) => <section className="gen-card" key={i}><h4>{props.labels[i]}</h4><p>{value}</p></section>)}</div>,
  TextInput: ({ props, bindings }) => {
    const [value, setValue] = useBoundProp(props.value, bindings?.value);
    return <label className="gen-field">{props.label}{props.multiline
      ? <textarea value={value ?? ''} onChange={event => setValue(event.target.value)} />
      : <input value={value ?? ''} onChange={event => setValue(event.target.value)} />}</label>;
  },
  Select: ({ props, bindings }) => {
    const [value, setValue] = useBoundProp(props.value, bindings?.value);
    return <label className="gen-field">{props.label}<select value={value ?? ''} onChange={event => setValue(event.target.value)}>
      {props.options.map(option => <option key={option}>{option}</option>)}</select></label>;
  },
  Checkbox: ({ props, bindings }) => {
    const [value, setValue] = useBoundProp(props.value, bindings?.value);
    return <label className="gen-check"><input type="checkbox" checked={value ?? false} onChange={event => setValue(event.target.checked)} />{props.label}</label>;
  },
  Radio: ({ props, bindings }) => {
    const [value, setValue] = useBoundProp(props.value, bindings?.value);
    const name = useId();
    return <fieldset className="gen-options"><legend>{props.label}</legend>{props.options.map(option =>
      <label className="gen-check" key={option}><input type="radio" name={name} value={option} checked={value === option} onChange={() => setValue(option)} />{option}</label>
    )}</fieldset>;
  },
  Collapsible: ({ props, bindings, children }) => {
    const [open, setOpen] = useBoundProp(props.open, bindings?.open);
    return <details className="gen-collapsible" open={open ?? false} onToggle={event => {
      if (event.currentTarget.open !== open) setOpen(event.currentTarget.open);
    }}><summary>{props.title}</summary><div>{children}</div></details>;
  },
  Tabs: ({ props, bindings, children }) => {
    const [value, setValue] = useBoundProp(props.value, bindings?.value);
    const id = useId();
    const panels = Children.toArray(children);
    return <section className="gen-tabs"><div className="gen-tab-list" role="tablist" aria-label={props.label}>
      {props.options.map((option, index) => <button type="button" role="tab" key={option} id={`${id}-tab-${index}`}
        aria-selected={value === option} aria-controls={`${id}-panel-${index}`} tabIndex={value === option ? 0 : -1}
        onClick={() => setValue(option)} onKeyDown={event => {
          let next: number;
          if (event.key === 'ArrowRight') next = (index + 1) % props.options.length;
          else if (event.key === 'ArrowLeft') next = (index + props.options.length - 1) % props.options.length;
          else if (event.key === 'Home') next = 0;
          else if (event.key === 'End') next = props.options.length - 1;
          else return;
          const option = props.options[next];
          if (option === undefined) throw new Error('Missing tab option');
          event.preventDefault(); setValue(option);
          document.getElementById(`${id}-tab-${next}`)?.focus();
        }}>{option}</button>)}
    </div>{props.options.map((option, index) => <div role="tabpanel" key={option} id={`${id}-panel-${index}`}
      aria-labelledby={`${id}-tab-${index}`} hidden={value !== option} tabIndex={0}>{panels[index]}</div>)}</section>;
  },
  SegmentedControl: ({ props, bindings }) => {
    const [value, setValue] = useBoundProp(props.value, bindings?.value);
    const name = useId();
    return <fieldset className="gen-options"><legend>{props.label}</legend><div className="gen-segments">{props.options.map(option =>
      <label key={option}><input type="radio" name={name} value={option} checked={value === option} onChange={() => setValue(option)} /><span>{option}</span></label>
    )}</div></fieldset>;
  },
  Slider: ({ props, bindings }) => {
    const [value, setValue] = useBoundProp(props.value, bindings?.value);
    return <label className="gen-field">{props.label}: {value}<input type="range" min={props.min} max={props.max} step={props.step} value={value ?? props.min} onChange={event => setValue(event.target.valueAsNumber)} /></label>;
  },
  Button: ({ props, emit }) => {
    const { snapshot } = useChat();
    return <button className="primary" disabled={snapshot.busy} onClick={() => emit('press')}>{props.label}</button>;
  },
};

class UiBoundary extends Component<{ children: ReactNode; error: string; source: string }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <section className="error">{this.props.error}<pre>{this.props.source}</pre></section> : this.props.children; }
}

export function StructuredUI({ source, itemId }: { source: string; itemId: string }) {
  const { act } = useChat(); const label = useLabel();
  const parsed = useMemo(() => {
    try {
      const value: unknown = JSON.parse(source);
      const result = catalog.zodSchema().safeParse(value);
      if (!result.success) return { error: result.error.message };
      const spec: Spec = renderSpecSchema.parse(value);
      // Validate references and cycles before the recursive React renderer runs.
      const active = new Set<string>(); const visited = new Set<string>();
      const visit = (id: string, depth: number) => {
        const element = spec.elements[id];
        if (!element || active.has(id) || depth > 64) throw new Error(`Invalid UI element reference: ${id}`);
        if (visited.has(id)) return;
        active.add(id);
        for (const child of element.children ?? []) visit(child, depth + 1);
        for (const children of Object.values(element.slots ?? {})) for (const child of children) visit(child, depth + 1);
        active.delete(id); visited.add(id);
      };
      visit(spec.root, 0);
      return { spec };
    } catch (error) { return { error: error instanceof Error ? error.message : 'Invalid JSON' }; }
  }, [source]);
  const registry = useMemo(() => defineRegistry(catalog, {
    components,
    actions: {
      copy_text: async params => { if (params) act({ type: 'copy', text: params.text }); },
      submit: async (params, _setState, state) => {
        if (params) act({ type: 'submit', itemId, text: `${params.instruction}\n\nUI操作結果：\n${JSON.stringify(state, null, 2)}` });
      },
    },
  }), [act, itemId]);
  if (!parsed.spec) return <section className="error">{label('invalid')}<p>{parsed.error}</p><details><summary>{label('source')}</summary><pre>{source}</pre></details></section>;
  return <UiBoundary error={label('invalid')} source={source}>
    <JSONUIProvider registry={registry.registry} initialState={parsed.spec.state ?? {}}>
      <LiveActions registry={registry}>
        <Renderer spec={parsed.spec} registry={registry.registry} />
      </LiveActions>
    </JSONUIProvider>
  </UiBoundary>;
}

// The action provider's handlers need access to the current state, not the
// initial model. This component installs handlers through the provider below.
function LiveActions({ registry, children }: { registry: ReturnType<typeof defineRegistry<typeof catalog>>; children: ReactNode }) {
  const state = useStateStore();
  const handlers = useMemo(() => registry.handlers(() => undefined, state.getSnapshot), [registry, state.getSnapshot]);
  return <ActionProvider handlers={handlers}>{children}</ActionProvider>;
}

const previewPolicy = "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'none'; form-action 'none'; base-uri 'none';";
export function HtmlUI({ source }: { source: string }) {
  const [code, setCode] = useState(false); const [expanded, setExpanded] = useState(false);
  const label = useLabel();
  const document = `<!doctype html><meta http-equiv="Content-Security-Policy" content="${previewPolicy}"><meta name="viewport" content="width=device-width,initial-scale=1">${source}`;
  return <section className={`html-ui ${expanded ? 'expanded' : ''}`}>
    <header><button aria-pressed={!code} onClick={() => setCode(false)}>{label('preview')}</button><button aria-pressed={code} onClick={() => setCode(true)}>{label('code')}</button>
      <Copy text={source} /><button onClick={() => setExpanded(value => !value)}>{label(expanded ? 'close' : 'expand')}</button></header>
    <div className="html-code" hidden={!code}><CodeBlock code={source} language="html" lineNumbers /></div>
    <iframe hidden={code} title={label('preview')} sandbox="allow-scripts" srcDoc={document} />
  </section>;
}

export function Value({ value }: { value: unknown }) {
  const label = useLabel();
  if (Array.isArray(value)) return <ul>{value.map((item: unknown, i: number) => <li key={i}><Value value={item} /></li>)}</ul>;
  if (value !== null && typeof value === 'object') return <dl className="value-fields">{Object.entries(value).map(([key, item]) =>
    <div key={key}><dt>{label(`field:${key}`)}</dt><dd><Value value={item} /></dd></div>)}</dl>;
  return <pre className="value">{display(value)}</pre>;
}
