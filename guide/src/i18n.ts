import type ja from '../public/locales/ja.json';
import reference from 'virtual:guide-default-locale';
import localeLanguages from 'virtual:guide-languages';

export type TextKey = keyof typeof ja;
export type Dictionary = Record<TextKey, string>;
export type Translate = (key: TextKey) => string;
export const fallback = reference;

export const languages = localeLanguages;

export async function loadDictionary(language: string, signal: AbortSignal): Promise<Dictionary> {
  const response = await fetch(`/locales/${encodeURIComponent(language)}.json`, { signal });
  if (!response.ok) throw new Error(`Locale HTTP ${response.status}`);
  const data: unknown = await response.json();
  if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error('Invalid locale');
  const entries = data as Record<string, unknown>;
  const keys = Object.keys(fallback) as TextKey[];
  if (Object.keys(entries).length !== keys.length || keys.some(key => typeof entries[key] !== 'string' || !entries[key]?.trim())) {
    throw new Error('Locale keys do not match the reference language');
  }
  return entries as Dictionary;
}
