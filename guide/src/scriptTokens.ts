export type ScriptToken = { text: string; kind?: 'comment' | 'string' | 'number' | 'type' | 'keyword' | 'function' | 'operator' };

const types = new Set(['string', 'int', 'float', 'bool', 'void']);
const keywords = new Set(['function', 'if', 'else', 'for', 'in', 'return', 'break', 'continue', 'true', 'false']);

// Keep the source intact, including whitespace. Tokenize strings/comments first
// so their contents cannot be mistaken for keywords or executable markup.
export function tokenizeScript(source: string): ScriptToken[] {
  const pattern = /(?<comment>\/\/[^\r\n]*)|(?<string>"(?:\\[^\r\n]|[^"\\\r\n])*"?)|(?<number>\d+(?:\.\d+)?)|(?<name>[\p{L}_][\p{L}\p{N}_]*)|(?<operator>==|!=|<=|>=|&&|\|\||[{}()\[\],:=+*/%<>!\-])/gu;
  const tokens: ScriptToken[] = [];
  let position = 0;
  for (const match of source.matchAll(pattern)) {
    const index = match.index;
    if (index > position) tokens.push({ text: source.slice(position, index) });
    const groups = match.groups!;
    let kind: ScriptToken['kind'];
    if (groups.comment) kind = 'comment';
    else if (groups.string) kind = 'string';
    else if (groups.number) kind = 'number';
    else if (groups.operator) kind = 'operator';
    else if (types.has(match[0])) kind = 'type';
    else if (keywords.has(match[0])) kind = 'keyword';
    else if (/^\s*\(/u.test(source.slice(index + match[0].length))) kind = 'function';
    tokens.push({ text: match[0], kind });
    position = index + match[0].length;
  }
  if (position < source.length) tokens.push({ text: source.slice(position) });
  return tokens;
}
