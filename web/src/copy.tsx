import { useEffect, useState } from 'react';
import { useChat, useLabel } from './bridge';

export function Copy({ text, label: labelKey = 'copy' }: { text: string | (() => string | null); label?: string }) {
  const { act } = useChat(); const label = useLabel();
  const [copied, setCopied] = useState(false);
  useEffect(() => { if (!copied) return; const timer = setTimeout(() => setCopied(false), 1500); return () => clearTimeout(timer); }, [copied]);
  const title = label(copied ? 'copied' : labelKey);
  return <button type="button" className="icon-button copy-button" title={title} aria-label={title} onClick={() => {
    const value = typeof text === 'function' ? text() : text;
    if (value === null) return;
    act({ type: 'copy', text: value }); setCopied(true);
  }}><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
    {copied ? <path d="m5 12 4 4L19 6" /> : <><rect x="8" y="8" width="12" height="12" rx="2" /><path d="M16 8V4a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v10a2 2 0 0 0 2 2h4" /></>}
  </svg></button>;
}
