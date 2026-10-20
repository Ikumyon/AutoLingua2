import { defineConfig } from 'vite';

function vendorChunk(moduleId: string): string | null {
  const path = moduleId.replace(/\\/g, '/');
  const marker = '/node_modules/';
  const index = path.lastIndexOf(marker);
  if (index < 0) return null;
  const relative = path.slice(index + marker.length);
  // Preserve the existing per-language and per-diagram dynamic import
  // boundaries instead of merging these assets into an eager vendor chunk.
  if (/^(?:@shikijs\/(?:langs|themes)\/|mermaid\/dist\/chunks\/)/.test(relative)) return null;
  const parts = relative.split('/');
  const name = relative.startsWith('@') ? parts.slice(0, 2).join('/') : parts[0];
  return `vendor-${name.replace(/[^a-zA-Z0-9_-]/g, '-')}`;
}

export default defineConfig({
  base: './',
  build: {
    outDir: '../assets/chat', emptyOutDir: true, target: 'es2022',
    rolldownOptions: {
      output: {
        strictExecutionOrder: true,
        codeSplitting: {
          groups: [{ name: vendorChunk, maxSize: 400_000, includeDependenciesRecursively: false }],
        },
      },
    },
  },
});
