import { useEffect, useState } from 'react';
import type { Translate } from './i18n';
import { Icon } from './Icon';
import { tokenizeScript } from './scriptTokens';

export function ScriptCode({ source, t }: { source: string; t: Translate }) {
  const [status, setStatus] = useState<'idle' | 'copying' | 'copied' | 'failed'>('idle');
  useEffect(() => {
    if (status !== 'copied' && status !== 'failed') return;
    const timer = window.setTimeout(() => setStatus('idle'), 2500);
    return () => window.clearTimeout(timer);
  }, [status]);

  async function copy() {
    setStatus('copying');
    try {
      await navigator.clipboard.writeText(source);
      setStatus('copied');
    } catch {
      setStatus('failed');
    }
  }

  const label = t(status === 'copied' ? 'guide.code.copied' : status === 'failed' ? 'guide.code.failed' : 'guide.code.copy');
  return <div className="guide-code-block">
    <div className="guide-code-toolbar">
      <button type="button" className="guide-code-copy" data-state={status} onClick={copy} disabled={status === 'copying'}>
        <Icon name={status === 'copied' ? 'check' : 'copy'} />
        <span role="status" aria-live="polite">{label}</span>
      </button>
    </div>
    <pre className="guide-code"><code>{tokenizeScript(source).map((token, index) =>
      token.kind ? <span key={index} className={`syntax-${token.kind}`}>{token.text}</span> : token.text,
    )}</code></pre>
  </div>;
}
