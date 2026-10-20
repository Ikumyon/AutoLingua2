const base = import.meta.env.BASE_URL;

export function siteUrl(path: string): string {
  return `${base}${path.replace(/^\//, '')}`;
}

export function routePath(): string {
  return location.pathname.startsWith(base) ? `/${location.pathname.slice(base.length)}` : location.pathname;
}
