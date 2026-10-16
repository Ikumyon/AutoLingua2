import { useEffect, useState } from 'react';

type Theme = 'light' | 'dark';
const storageKey = 'autolingua2-guide-theme';
function savedTheme(): Theme | null {
  try {
    const value = localStorage.getItem(storageKey);
    return value === 'light' || value === 'dark' ? value : null;
  } catch { return null; }
}

export function useTheme() {
  const [preference, setPreference] = useState(savedTheme);
  const [systemDark, setSystemDark] = useState(() => matchMedia('(prefers-color-scheme: dark)').matches);
  const theme = preference ?? (systemDark ? 'dark' : 'light');

  useEffect(() => {
    const media = matchMedia('(prefers-color-scheme: dark)');
    const change = () => setSystemDark(media.matches);
    const sync = (event: StorageEvent) => {
      if (event.key === storageKey || event.key === null) setPreference(savedTheme());
    };
    change();
    media.addEventListener('change', change);
    window.addEventListener('storage', sync);
    return () => {
      media.removeEventListener('change', change);
      window.removeEventListener('storage', sync);
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.style.colorScheme = theme;
    document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0d1b2e' : '#ffffff');
  }, [theme]);

  function toggleTheme() {
    const next = theme === 'dark' ? 'light' : 'dark';
    setPreference(next);
    try { localStorage.setItem(storageKey, next); } catch { /* Keep the selection in memory. */ }
  }
  return { theme, toggleTheme };
}
