// Run before CSS and React to avoid flashing the wrong theme on reload.
(() => {
  let saved;
  try { saved = localStorage.getItem('autolingua2-guide-theme'); } catch { /* Storage can be disabled. */ }
  const theme = saved === 'light' || saved === 'dark'
    ? saved
    : matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  document.documentElement.dataset.theme = theme;
  document.documentElement.style.colorScheme = theme;
  document.querySelector('meta[name="theme-color"]')?.setAttribute('content', theme === 'dark' ? '#0d1b2e' : '#ffffff');
})();
