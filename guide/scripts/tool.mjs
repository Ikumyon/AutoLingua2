import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';

// Prefer guide-local dependencies; reuse the existing sibling installation when available.
const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('../', import.meta.url));
const [tool, ...args] = process.argv.slice(2);
const entries = { vite: 'bin/vite.js', typescript: 'bin/tsc' };
if (!Object.hasOwn(entries, tool)) throw new Error(`Unknown tool: ${tool}`);
const manifest = require.resolve(`${tool}/package.json`, { paths: [root, resolve(root, '../../auto_lingua')] });
process.argv = [process.argv[0], resolve(dirname(manifest), entries[tool]), ...args];
await import(pathToFileURL(process.argv[1]).href);
