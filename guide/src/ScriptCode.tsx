import { tokenizeScript } from './scriptTokens';

export function ScriptCode({ source }: { source: string }) {
  return <pre className="guide-code"><code>{tokenizeScript(source).map((token, index) =>
    token.kind ? <span key={index} className={`syntax-${token.kind}`}>{token.text}</span> : token.text,
  )}</code></pre>;
}
