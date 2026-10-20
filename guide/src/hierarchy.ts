import type { GuidePage, Section } from './content';
import type { TextKey } from './i18n';
import { scriptReference } from './script-reference';

function prose(id: string, title: TextKey, ...text: TextKey[]): Section {
  return { id, title, blocks: text.map(text => ({ kind: 'paragraph', text })) };
}

function illustrated(section: Section, src: string, caption: TextKey): Section {
  return { ...section, blocks: [...section.blocks, { kind: 'image', src, caption }] };
}

export function organizeGuide(sources: GuidePage[]) {
  const source = (slug: string) => {
    const page = sources.find(page => page.slug === slug);
    if (!page) throw new Error(`Missing guide source: ${slug}`);
    return page;
  };
  const sections = (slug: string, ...ids: string[]) => ids.map(id => {
    const section = source(slug).sections.find(section => section.id === id);
    if (!section) throw new Error(`Missing guide section: ${slug}#${id}`);
    return section;
  });
  const child = (slug: string, parentSlug: string, title: TextKey, description: TextKey, contents: Section[]): GuidePage =>
    ({ slug, parentSlug, title, description, sections: contents });
  const overview = (id: string, title: TextKey, text: TextKey, slug: string): Section => ({
    ...prose(id, title, text), blocks: [
      { kind: 'paragraph', text }, { kind: 'guideReference', label: title, slug },
    ],
  });
  const projectUpdates = child('source-updates', 'projects', 'details.updates.title', 'details.updates.description', [
    prose('workflow', 'details.updates.workflow.title', 'details.updates.workflow.body', 'details.updates.example'),
    ...sections('settings', 'files'),
    illustrated(prose('register-target', 'details.updates.register.title', 'details.updates.register.body', 'details.updates.register.check'),
      '/images/projects/source-watch.webp', 'details.images.sourceWatch'),
    ...sections('projects', 'source-updates'),
    prose('after-update', 'details.updates.after.title', 'details.updates.after.body', 'details.updates.errors'),
  ]);
  const thumbnail = child('thumbnail', 'projects', 'details.thumbnail.title', 'details.thumbnail.description', [
    prose('open', 'details.thumbnail.open.title', 'details.thumbnail.open.body', 'details.thumbnail.open.example'),
    prose('layers', 'details.thumbnail.layers.title', 'details.thumbnail.layers.body', 'details.thumbnail.layers.order'),
    prose('transform', 'details.thumbnail.transform.title', 'details.thumbnail.transform.body', 'details.thumbnail.transform.interpolation'),
    prose('canvas', 'details.thumbnail.canvas.title', 'details.thumbnail.canvas.body', 'details.thumbnail.canvas.crop'),
    prose('text', 'details.thumbnail.text.title', 'details.thumbnail.text.body', 'details.thumbnail.text.example'),
    prose('apply', 'details.thumbnail.apply.title', 'details.thumbnail.apply.body', 'details.thumbnail.apply.reset'),
    prose('export-image', 'details.thumbnail.export.title', 'details.thumbnail.export.body', 'details.thumbnail.export.png', 'details.thumbnail.export.jpeg'),
    prose('metadata', 'details.thumbnail.metadata.title', 'details.thumbnail.metadata.body', 'details.thumbnail.mod.body', 'details.thumbnail.export.check'),
  ]);
  const glossaryEditor = child('glossary-editor', 'glossary-tone', 'details.glossaryEditor.title', 'details.glossaryEditor.description', [
    ...sections('glossary-tone', 'create-glossary', 'edit-terms'),
    prose('term-example', 'details.glossaryEditor.example.title', 'details.glossaryEditor.example.body', 'details.glossaryEditor.example.variants'),
    ...sections('glossary-tone', 'inheritance'),
    prose('inheritance-example', 'details.glossaryEditor.inheritance.title', 'details.glossaryEditor.inheritance.body', 'details.glossaryEditor.check'),
  ]);
  const glossaryExchange = child('glossary-exchange', 'glossary-tone', 'details.glossaryExchange.title', 'details.glossaryExchange.description', [
    prose('prepare', 'details.glossaryExchange.prepare.title', 'details.glossaryExchange.prepare.body', 'details.glossaryExchange.choose'),
    ...sections('glossary-tone', 'import-glossary'),
    prose('merge-example', 'details.glossaryExchange.merge.title', 'details.glossaryExchange.merge.body', 'details.glossaryExchange.verify'),
    ...sections('glossary-tone', 'export-glossary', 'paratranz-glossary'),
    prose('exchange-example', 'details.glossaryExchange.example.title', 'details.glossaryExchange.example.body', 'details.glossaryExchange.errors'),
  ]);
  const tone = child('tone', 'glossary-tone', 'details.tone.title', 'details.tone.description', [
    ...sections('glossary-tone', 'normal-tone'),
    prose('write-instructions', 'details.tone.instructions.title', 'details.tone.instructions.body', 'details.tone.instructions.example'),
    ...sections('glossary-tone', 'conditional-tone'),
    prose('condition-example', 'details.tone.conditions.title', 'details.tone.conditions.body', 'details.tone.conditions.check'),
    ...sections('glossary-tone', 'use-in-translation'),
    prose('verify-tone', 'details.tone.verify.title', 'details.tone.verify.body'),
  ]);
  const yaml = child('export-yaml', 'export', 'details.yaml.title', 'details.yaml.description', [
    prose('prepare', 'details.yaml.prepare.title', 'details.yaml.prepare.body', 'details.yaml.slot.example'),
    ...sections('export', 'paradox-yaml'),
    prose('layout-example', 'details.yaml.layout.title', 'details.yaml.layout.body', 'details.yaml.encoding.check'),
    prose('verify', 'details.yaml.verify.title', 'details.yaml.verify.body', 'details.yaml.errors'),
  ]);
  const json = child('export-paratranz', 'export', 'details.json.title', 'details.json.description', [
    prose('workflow', 'details.json.workflow.title', 'details.json.workflow.body', 'details.json.workflow.import'),
    ...sections('export', 'paratranz-json'),
    prose('state-example', 'details.json.example.title', 'details.json.example.body', 'details.json.example.loss'),
    prose('verify', 'details.json.verify.title', 'details.json.verify.body', 'details.json.glossary'),
  ]);
  const bmfont = child('export-bmfont', 'export', 'details.bmfont.title', 'details.bmfont.description', [
    prose('purpose', 'details.bmfont.purpose.title', 'details.bmfont.purpose.body', 'details.bmfont.prepare'),
    ...sections('export', 'bmfont'),
    prose('text-selection', 'details.bmfont.selection.title', 'details.bmfont.selection.body', 'details.bmfont.selection.example'),
    prose('use-list', 'details.bmfont.use.title', 'details.bmfont.use.body', 'details.bmfont.verify'),
  ]);
  const ai = child('ai-settings', 'settings', 'details.ai.title', 'details.ai.description', [
    prose('prepare', 'details.ai.prepare.title', 'details.ai.prepare.body', 'details.ai.prepare.auth'),
    ...sections('settings', 'ai'),
    prose('models', 'details.ai.models.title', 'details.ai.models.body', 'details.ai.models.test'),
    ...sections('settings', 'translation'),
    prose('assign-models', 'details.ai.assign.title', 'details.ai.assign.body', 'details.ai.assign.example'),
    prose('verify', 'details.ai.verify.title', 'details.ai.verify.body', 'details.ai.errors'),
  ]);
  const scripts = child('scripts', 'automation', 'details.scripts.title', 'details.scripts.description', [
    illustrated(sections('automation', 'script-files')[0], '/images/automation/script-editor.webp', 'details.images.scriptEditor'),
    prose('prepare-script', 'details.scripts.prepare.title', 'details.scripts.prepare.body', 'details.scripts.prepare.ids'),
    ...sections('automation', 'script-example'),
    prose('adapt-example', 'details.scripts.example.title', 'details.scripts.example.body', 'details.scripts.example.files'),
    ...sections('automation', 'run-script'),
    prose('debug', 'details.scripts.debug.title', 'details.scripts.debug.body', 'details.scripts.debug.retry'),
    ...sections('automation', 'script-reference'),
  ]);
  const triggers = child('automation-triggers', 'automation', 'details.triggers.title', 'details.triggers.description', [
    prose('prepare', 'details.triggers.prepare.title', 'details.triggers.prepare.body', 'details.triggers.prepare.test'),
    illustrated(prose('register', 'details.triggers.register.title', 'details.triggers.register.body', 'details.triggers.register.save'),
      '/images/automation/triggers.webp', 'details.images.triggers'),
    prose('events', 'details.triggers.events.title', 'details.triggers.events.body', 'details.triggers.events.schedule'),
    { id: 'example', title: 'details.triggers.example.title', blocks: [
      { kind: 'paragraph', text: 'details.triggers.example.body' },
      { kind: 'code', text: 'details.triggers.example.code' },
      { kind: 'paragraph', text: 'details.triggers.example.explain' },
    ] },
    prose('confirm', 'details.triggers.confirm.title', 'details.triggers.confirm.body', 'details.triggers.confirm.wait'),
    prose('logs', 'details.triggers.logs.title', 'details.triggers.logs.body', 'details.triggers.logs.errors'),
    prose('disable', 'details.triggers.disable.title', 'details.triggers.disable.body', 'details.triggers.disable.loop'),
  ]);
  const mcpServer = child('mcp-server', 'automation', 'automation.server.title', 'details.mcpServer.description', [
    prose('prepare', 'details.mcpServer.prepare.title', 'details.mcpServer.prepare.body', 'details.mcpServer.prepare.permissions'),
    ...sections('automation', 'mcp-server'),
    prose('connection-example', 'details.mcpServer.example.title', 'details.mcpServer.example.body', 'details.mcpServer.example.change'),
    ...sections('automation', 'mcp-results'),
    prose('troubleshooting', 'details.mcpServer.errors.title', 'details.mcpServer.errors.body', 'details.mcpServer.errors.token'),
  ]);
  const mcpResources = child('mcp-resources', 'automation', 'automation.resources.title', 'details.mcpResources.description', [
    prose('prepare', 'details.mcpResources.prepare.title', 'details.mcpResources.prepare.body', 'details.mcpResources.prepare.types'),
    ...sections('automation', 'external-resources'),
    prose('local-example', 'details.mcpResources.local.title', 'details.mcpResources.local.body', 'details.mcpResources.http.body'),
    prose('use-resources', 'details.mcpResources.use.title', 'details.mcpResources.use.body', 'details.mcpResources.use.verify'),
    prose('maintain', 'details.mcpResources.maintain.title', 'details.mcpResources.maintain.body', 'details.mcpResources.errors'),
  ]);

  const pages: GuidePage[] = [
    source('setup'), source('first-translation'),
    { ...source('projects'), sections: [
      ...sections('projects', 'about-projects', 'save', 'reopen', 'languages'),
      prose('dashboard', 'details.dashboard.title', 'details.dashboard.body', 'details.dashboard.languages', 'details.dashboard.states', 'details.dashboard.example'),
      overview('source-updates', 'details.updates.title', 'details.updates.overview', projectUpdates.slug),
      overview('thumbnail', 'details.thumbnail.title', 'details.thumbnail.overview', thumbnail.slug),
      ...sections('projects', 'switch-projects'),
    ] },
    { ...source('translation'), sections: source('translation').sections.map(section => {
      if (section.id === 'compare-models') return { ...section, blocks: [...section.blocks,
        { kind: 'paragraph' as const, text: 'details.translation.compare' as const },
        { kind: 'paragraph' as const, text: 'details.translation.adopt' as const },
      ] };
      if (section.id === 'review-tools') return { ...section, blocks: [...section.blocks,
        { kind: 'guideReference' as const, label: 'details.support.title' as const, slug: 'support' },
      ] };
      return section;
    }) },
    { ...source('glossary-tone'), sections: [
      ...sections('glossary-tone', 'open-and-apply'),
      prose('workflow', 'details.glossary.workflow.title', 'details.glossary.workflow.body', 'details.glossary.workflow.example'),
      overview('create-glossary', glossaryEditor.title, 'details.glossaryEditor.overview', glossaryEditor.slug),
      overview('import-glossary', glossaryExchange.title, 'details.glossaryExchange.overview', glossaryExchange.slug),
      overview('normal-tone', tone.title, 'details.tone.overview', tone.slug),
      ...sections('glossary-tone', 'use-in-translation'),
    ] },
    { ...source('export'), sections: [
      ...sections('export', 'before-export', 'destination', 'format', 'translation-states'),
      overview('paradox-yaml', yaml.title, 'details.yaml.overview', yaml.slug),
      overview('paratranz-json', json.title, 'details.json.overview', json.slug),
      overview('bmfont', bmfont.title, 'details.bmfont.overview', bmfont.slug),
      ...sections('export', 'run-and-check'),
    ] },
    source('ai-chat'),
    { ...source('settings'), sections: [
      ...sections('settings', 'open-and-save', 'application', 'shortcuts'),
      overview('ai', ai.title, 'details.ai.overview', ai.slug),
      ...sections('settings', 'translation', 'tone-and-glossary', 'filter-rules'),
      prose('plugins', 'details.plugins.title', 'details.plugins.body', 'details.plugins.check'),
      overview('files', projectUpdates.title, 'details.settings.files', projectUpdates.slug),
      overview('mcp-and-plugins', 'automation.title', 'details.settings.mcp', 'automation'),
    ] },
    { ...source('automation'), sections: [
      ...sections('automation', 'choose-method'),
      prose('workflow', 'details.automation.workflow.title', 'details.automation.workflow.body', 'details.automation.workflow.example'),
      overview('script-files', scripts.title, 'details.scripts.overview', scripts.slug),
      overview('triggers', triggers.title, 'details.triggers.overview', triggers.slug),
      ...sections('automation', 'script-reference'),
      overview('mcp-server', mcpServer.title, 'details.mcpServer.overview', mcpServer.slug),
      overview('external-resources', mcpResources.title, 'details.mcpResources.overview', mcpResources.slug),
      prose('results', 'details.automation.results.title', 'details.automation.results.body', 'details.automation.results.stop'),
    ] },
    { slug: 'support', title: 'details.support.title', description: 'details.support.description', sections: [
      prose('first-check', 'details.support.first.title', 'details.support.first.body', 'details.support.first.save'),
      prose('problems', 'translation.review.problems.label', 'translation.review.problems.body', 'details.support.problems.body'),
      prose('connection', 'details.support.connection.title', 'details.support.connection.body', 'details.support.connection.models'),
      prose('translation', 'details.support.translation.title', 'details.support.translation.body', 'details.support.translation.review'),
      prose('export', 'details.support.export.title', 'details.support.export.body', 'details.support.export.state'),
      prose('update', 'details.support.update.title', 'details.support.update.body', 'details.support.update.install', 'details.support.update.errors'),
    ] },
  ];
  const referencePages = [projectUpdates, thumbnail, glossaryEditor, glossaryExchange, tone, yaml, json, bmfont,
    ai, scripts, triggers, scriptReference, mcpServer, mcpResources];

  // Old chapter/anchor URLs continue to open the detailed explanation after it moves.
  const legacyAnchorTargets: Record<string, string> = {};
  for (const page of referencePages) {
    for (const section of page.sections) {
      for (const original of sources) {
        if (original.sections.includes(section) && !pages.find(item => item.slug === original.slug)?.sections.includes(section)) {
          legacyAnchorTargets[`${original.slug}#${section.id}`] = `${page.slug}#${section.id}`;
        }
      }
    }
  }
  const captures: [string, string, string, TextKey][] = [
    ['translation', 'workspace-and-views', 'translation/overview', 'details.images.translationOverview'],
    ['translation', 'search-and-filter', 'translation/search-filter', 'details.images.searchFilter'],
    ['ai-chat', 'open-and-send', 'ai-chat/conversation', 'details.images.aiChat'],
    ['ai-settings', 'models', 'settings/ai-models', 'details.images.aiSettings'],
    ['tone', 'condition-example', 'glossary-tone/conditional-tone', 'details.images.conditionalTone'],
    ['translation', 'compare-models', 'translation/model-comparison', 'details.images.modelComparison'],
    ['glossary-editor', 'inheritance-example', 'glossary-tone/glossary-inheritance', 'details.images.glossaryInheritance'],
    ['source-updates', 'after-update', 'projects/source-diff', 'details.images.sourceDiff'],
    ['thumbnail', 'transform', 'projects/thumbnail-edit', 'details.images.thumbnailEdit'],
    ['ai-chat', 'apply-changes', 'ai-chat/apply-changes', 'details.images.chatApply'],
    ['mcp-server', 'connection-example', 'automation/mcp-settings', 'details.images.mcpSettings'],
    ['support', 'update', 'support/update-error', 'details.images.updateStatus'],
  ];
  for (const [slug, id, file, caption] of captures) {
    const section = [...pages, ...referencePages].find(page => page.slug === slug)?.sections.find(section => section.id === id);
    if (!section) throw new Error(`Missing capture section: ${slug}#${id}`);
    section.blocks.push({ kind: 'image', src: `/images/${file}.webp`, caption });
  }
  return { pages, referencePages, legacyAnchorTargets };
}
