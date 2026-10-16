import test from 'node:test';
import assert from 'node:assert/strict';
import { parseLocale, compareKeys } from './validate-locales.mjs';

test('duplicate keys include filename and line number', () => {
  assert.throws(() => parseLocale('{\n "title": "one",\n "title": "two"\n}', 'ja.json'), /ja.json:3: Duplicate key: title/);
});
test('escaped spellings cannot bypass duplicate detection', () => {
  assert.throws(() => parseLocale(String.raw`{"title":"one","\u0074itle":"two"}`), /Duplicate key: title/);
});
test('punctuation and escaped quotes in text are allowed', () => {
  const data = { title: '日本語 "a": {b}, \\ path\n次の行', body: '本文' };
  assert.deepEqual(parseLocale(JSON.stringify(data)), data);
});
test('only flat objects with non-empty strings are accepted', () => {
  for (const source of ['[]', 'null', '{"a":{}}', '{"a":1}', '{"a":" "}', '{"":"text"}', '{']) {
    assert.throws(() => parseLocale(source));
  }
});
test('language key differences are reported together', () => {
  assert.throws(() => compareKeys({ a: 'a' }, { b: 'b' }, 'en.json'), /missing keys \[a\]; extra keys \[b\]/);
  assert.doesNotThrow(() => compareKeys({ a: '日本語' }, { a: 'English' }, 'en.json'));
});
