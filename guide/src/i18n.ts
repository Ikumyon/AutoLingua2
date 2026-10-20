import type ja from '../public/locales/ja.json';
import reference from 'virtual:guide-default-locale';
import localeLanguages from 'virtual:guide-languages';
import { siteUrl } from './urls';

export type TextKey = keyof typeof ja;
export type Dictionary = Record<TextKey, string>;
export type Translate = (key: TextKey) => string;
export const fallback = reference;

export const languages = localeLanguages;

export function browserLanguage(preferences: readonly string[] = navigator.languages): string {
  for (const preference of preferences) {
    const tag = preference.replaceAll('_', '-').toLowerCase();
    const exact = languages.find(language => language.code.toLowerCase() === tag);
    if (exact) return exact.code;
    const base = tag.split('-')[0];
    if (base === 'zh') {
      return tag.split('-').some(part => ['tw', 'hk', 'mo', 'hant'].includes(part)) ? 'zh-TW' : 'zh-CN';
    }
    const match = languages.find(language => language.code.toLowerCase().split('-')[0] === base);
    if (match) return match.code;
  }
  return 'en';
}

export async function loadDictionary(language: string, signal: AbortSignal): Promise<Dictionary> {
  const response = await fetch(siteUrl(`/locales/${encodeURIComponent(language)}.json`), { signal });
  if (!response.ok) throw new Error(`Locale HTTP ${response.status}`);
  const data: unknown = await response.json();
  if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error('Invalid locale');
  const entries = data as Record<string, unknown>;
  const keys = Object.keys(fallback) as TextKey[];
  // Body text, image captions and screenshot subtitles are required in every language.
  if (keys.some(key => !Object.hasOwn(entries, key)) ||
      Object.entries(entries).some(([key, value]) => !Object.hasOwn(fallback, key) || typeof value !== 'string' || !value.trim())) {
    throw new Error('Locale keys do not match the reference language');
  }
  return entries as Dictionary;
}
