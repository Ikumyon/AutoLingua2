import { readFileSync, readdirSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

export function parseLocale(source, filename = 'locale.json') {
  const fail = (message, offset = 0) => {
    const line = source.slice(0, offset).split('\n').length;
    throw new Error(`${filename}:${line}: ${message}`);
  };
  let data;
  try { data = JSON.parse(source); } catch (error) { fail(error.message); }
  if (!data || Array.isArray(data) || typeof data !== 'object') fail('Expected a flat JSON object.');
  for (const [key, value] of Object.entries(data)) {
    if (!key.trim() || typeof value !== 'string' || !value.trim()) fail(`"${key}" must have a non-empty string value.`);
  }
  // Scan the original text: JSON.parse alone silently discards duplicate keys.
  const token = /"(?:[^"\\]|\\.)*"|[{}:,]/gy;
  let offset = 0;
  const next = () => {
    while (/\s/.test(source[offset] ?? '') && offset < source.length) offset++;
    token.lastIndex = offset;
    const match = token.exec(source);
    if (!match) fail('Expected a string or JSON delimiter.', offset);
    offset = token.lastIndex;
    return match[0];
  };
  const seen = new Set();
  next(); // Opening brace; syntax has already been checked by JSON.parse.
  let current = next();
  while (current !== '}') {
    const key = JSON.parse(current);
    if (seen.has(key)) fail(`Duplicate key: ${key}`, offset - current.length);
    seen.add(key);
    next(); // Colon.
    next(); // String value.
    current = next();
    if (current === ',') current = next();
  }
  return data;
}

export function compareKeys(reference, translated, filename) {
  const missing = Object.keys(reference).filter(key => !Object.hasOwn(translated, key));
  const extra = Object.keys(translated).filter(key => !Object.hasOwn(reference, key));
  if (missing.length || extra.length) {
    throw new Error(`${filename}: missing keys [${missing.join(', ')}]; extra keys [${extra.join(', ')}]`);
  }
}

export function validateLocales() {
  const directory = new URL('../public/locales/', import.meta.url);
  const files = readdirSync(directory).filter(file => file.endsWith('.json'));
  const locales = new Map(files.map(file => [file, parseLocale(readFileSync(new URL(file, directory), 'utf8'), file)]));
  const reference = locales.get('ja.json');
  if (!reference) throw new Error('ja.json is required as the reference language.');
  for (const [filename, data] of locales) compareKeys(reference, data, filename);
  return files.length;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  console.log(`Validated ${validateLocales()} language file(s).`);
}
