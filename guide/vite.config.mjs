import { createRequire } from 'node:module';
import { readFileSync, readdirSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { parseLocale, validateLocales } from './scripts/validate-locales.mjs';

const require = createRequire(import.meta.url);
const root = fileURLToPath(new URL('.', import.meta.url));
function packageRoot(name) {
  return dirname(require.resolve(`${name}/package.json`, { paths: [root, resolve(root, '../../auto_lingua')] })).replaceAll('\\', '/');
}

export default {
  base: process.env.GUIDE_BASE_PATH || '/',
  resolve: {
    alias: [
      { find: /^react-dom(?=\/|$)/, replacement: packageRoot('react-dom') },
      { find: /^react(?=\/|$)/, replacement: packageRoot('react') },
    ],
  },
  plugins: [{
    name: 'validate-guide-locales',
    generateBundle: { order: 'post', handler(_options, bundle) {
      // GitHub Pages serves this entry for direct visits to client-side routes.
      const index = bundle['index.html'];
      if (!index || index.type !== 'asset') throw new Error('Missing guide entry');
      this.emitFile({ type: 'asset', fileName: '404.html', source: index.source });
    } },
    resolveId(id) {
      if (id === 'virtual:guide-default-locale') return '\0guide-default-locale';
      if (id === 'virtual:guide-languages') return '\0guide-languages';
    },
    load(id) {
      if (id === '\0guide-languages') {
        const directory = resolve(root, 'public/locales');
        const files = readdirSync(directory).filter(file => file.endsWith('.json'));
        const languages = files.sort((a, b) => a === b ? 0 : a === 'ja.json' ? -1 : b === 'ja.json' ? 1 : a.localeCompare(b)).map(file => {
          const filename = resolve(directory, file);
          const data = parseLocale(readFileSync(filename, 'utf8'), file);
          return { code: file.slice(0, -5), label: data['language.name'] };
        });
        return `export default ${JSON.stringify(languages)};`;
      }
      if (id !== '\0guide-default-locale') return;
      const filename = resolve(root, 'public/locales/ja.json');
      return `export default ${JSON.stringify(parseLocale(readFileSync(filename, 'utf8'), 'ja.json'))};`;
    },
    buildStart() { validateLocales(); },
    handleHotUpdate({ file, server }) {
      if (!file.replaceAll('\\', '/').includes('/public/locales/')) return;
      validateLocales();
      for (const id of ['\0guide-languages', '\0guide-default-locale']) {
        const module = server.moduleGraph.getModuleById(id);
        if (module) server.moduleGraph.invalidateModule(module);
      }
      server.ws.send({ type: 'full-reload' });
      return [];
    },
  }],
  build: { target: 'es2022', outDir: 'dist' },
};
