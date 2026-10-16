import type { TextKey } from './i18n';
import { scriptReference } from './script-reference';

export type Definition = { label: TextKey; body: TextKey };
type Block =
  | { kind: 'image'; src: string; caption: TextKey }
  | { kind: 'paragraph' | 'notice' | 'code'; text: TextKey }
  | { kind: 'guideReference'; label: TextKey; slug: string; anchor?: string }
  | { kind: 'definitions'; title?: TextKey; items: Definition[] }
  | { kind: 'links'; title: TextKey; items: { label: TextKey; href: string }[] }
  | { kind: 'guideLinks'; title: TextKey; items: { label: TextKey; slug: string }[] }
  | { kind: 'table'; columns: [TextKey, TextKey]; rows: Definition[] };
export type Section = { id: string; title: TextKey; step?: number; blocks: Block[] };
export type GuidePage = { slug: string; parentSlug?: string; title: TextKey; navTitle?: TextKey; description?: TextKey; sections: Section[] };

export const referencePages: GuidePage[] = [scriptReference];

const setup: GuidePage = {
  slug: 'setup', title: 'setup.title', description: 'setup.description',
  sections: [
    { id: 'overview', title: 'setup.overview.title', blocks: [
      { kind: 'paragraph', text: 'setup.overview.body' },
      { kind: 'notice', text: 'setup.overview.note' },
    ] },
    { id: 'display-language', title: 'setup.displayLanguage.title', step: 1, blocks: [
      { kind: 'paragraph', text: 'setup.displayLanguage.description' },
      { kind: 'definitions', title: 'setup.displayLanguage.items', items: [
        { label: 'setup.displayLanguage.selection.label', body: 'setup.displayLanguage.selection.body' },
        { label: 'setup.displayLanguage.custom.label', body: 'setup.displayLanguage.custom.body' },
      ] },
      { kind: 'paragraph', text: 'setup.displayLanguage.next' },
    ] },
    { id: 'ai-selection', title: 'setup.aiSelection.title', step: 2, blocks: [
      { kind: 'paragraph', text: 'setup.aiSelection.description' },
      { kind: 'image', src: '/images/setup/ai-selection.webp', caption: 'setup.images.aiSelection' },
      { kind: 'definitions', title: 'setup.aiSelection.providers', items: [
        { label: 'setup.aiSelection.chatgpt.label', body: 'setup.aiSelection.chatgpt.body' },
        { label: 'setup.aiSelection.openai.label', body: 'setup.aiSelection.openai.body' },
        { label: 'setup.aiSelection.google.label', body: 'setup.aiSelection.google.body' },
        { label: 'setup.aiSelection.anthropic.label', body: 'setup.aiSelection.anthropic.body' },
      ] },
      { kind: 'paragraph', text: 'setup.aiSelection.next' },
    ] },
    { id: 'ai-connection', title: 'setup.aiConnection.title', step: 3, blocks: [
      { kind: 'paragraph', text: 'setup.aiConnection.description' },
      { kind: 'definitions', items: [
        { label: 'setup.aiConnection.signin.label', body: 'setup.aiConnection.signin.body' },
        { label: 'setup.aiConnection.browser.label', body: 'setup.aiConnection.browser.body' },
        { label: 'setup.aiConnection.return.label', body: 'setup.aiConnection.return.body' },
      ] },
      { kind: 'definitions', items: [
        { label: 'setup.aiConnection.key.label', body: 'setup.aiConnection.key.body' },
      ] },
      { kind: 'links', title: 'setup.aiConnection.links', items: [
        { label: 'setup.aiConnection.openai', href: 'https://platform.openai.com/api-keys' },
        { label: 'setup.aiConnection.google', href: 'https://aistudio.google.com/apikey' },
        { label: 'setup.aiConnection.anthropic', href: 'https://console.anthropic.com/settings/keys' },
      ] },
      { kind: 'definitions', items: [
        { label: 'setup.aiConnection.models.label', body: 'setup.aiConnection.models.body' },
        { label: 'setup.aiConnection.test.label', body: 'setup.aiConnection.test.body' },
      ] },
      { kind: 'notice', text: 'setup.aiConnection.note' },
      { kind: 'image', src: '/images/setup/connection-success.webp', caption: 'setup.images.success' },
      { kind: 'paragraph', text: 'setup.aiConnection.error' },
    ] },
    { id: 'ui-translation', title: 'setup.uiTranslation.title', step: 4, blocks: [
      { kind: 'notice', text: 'setup.uiTranslation.condition' },
      { kind: 'definitions', items: [
        { label: 'setup.uiTranslation.ai.label', body: 'setup.uiTranslation.ai.body' },
        { label: 'setup.uiTranslation.ts.label', body: 'setup.uiTranslation.ts.body' },
      ] },
    ] },
    { id: 'navigation', title: 'setup.navigation.title', blocks: [
      { kind: 'table', columns: ['setup.navigation.button', 'setup.navigation.action'], rows: [
        { label: 'setup.navigation.back.label', body: 'setup.navigation.back.body' },
        { label: 'setup.navigation.next.label', body: 'setup.navigation.next.body' },
        { label: 'setup.navigation.finish.label', body: 'setup.navigation.finish.body' },
        { label: 'setup.navigation.skip.label', body: 'setup.navigation.skip.body' },
      ] },
    ] },
    { id: 'skip-and-reset', title: 'setup.skipAndReset.title', blocks: [
      { kind: 'paragraph', text: 'setup.skipAndReset.body' },
      { kind: 'guideReference', label: 'settings.title', slug: 'settings' },
    ] },
  ],
};

export const pages: GuidePage[] = [
  setup,
  { slug: 'first-translation', title: 'firstTranslation.title', description: 'firstTranslation.description', sections: [
    { id: 'before-starting', title: 'firstTranslation.before.title', blocks: [
      { kind: 'paragraph', text: 'firstTranslation.before.body' },
      { kind: 'guideReference', label: 'setup.title', slug: 'setup' },
      { kind: 'notice', text: 'firstTranslation.before.models' },
    ] },
    { id: 'create-project', title: 'firstTranslation.create.title', step: 1, blocks: [
      { kind: 'paragraph', text: 'firstTranslation.create.body' },
      { kind: 'definitions', items: [
        { label: 'firstTranslation.create.source.label', body: 'firstTranslation.create.source.body' },
        { label: 'firstTranslation.create.inherit.label', body: 'firstTranslation.create.inherit.body' },
      ] },
      { kind: 'paragraph', text: 'firstTranslation.create.next' },
      { kind: 'image', src: '/images/first-translation/create-project.webp', caption: 'firstTranslation.images.create' },
    ] },
    { id: 'target-language', title: 'firstTranslation.language.title', step: 2, blocks: [
      { kind: 'paragraph', text: 'firstTranslation.language.body' },
      { kind: 'image', src: '/images/first-translation/add-language.webp', caption: 'firstTranslation.images.language' },
      { kind: 'notice', text: 'firstTranslation.language.note' },
    ] },
    { id: 'translate', title: 'firstTranslation.translate.title', step: 3, blocks: [
      { kind: 'paragraph', text: 'firstTranslation.translate.body' },
      { kind: 'image', src: '/images/first-translation/list.webp', caption: 'firstTranslation.images.list' },
      { kind: 'definitions', items: [
        { label: 'firstTranslation.translate.all.label', body: 'firstTranslation.translate.all.body' },
        { label: 'firstTranslation.translate.selected.label', body: 'firstTranslation.translate.selected.body' },
      ] },
      { kind: 'notice', text: 'firstTranslation.translate.note' },
    ] },
    { id: 'review', title: 'firstTranslation.review.title', step: 4, blocks: [
      { kind: 'paragraph', text: 'firstTranslation.review.body' },
      { kind: 'image', src: '/images/first-translation/focus.webp', caption: 'firstTranslation.images.focus' },
      { kind: 'paragraph', text: 'firstTranslation.review.save' },
      { kind: 'notice', text: 'firstTranslation.review.filter' },
    ] },
    { id: 'save-project', title: 'firstTranslation.save.title', step: 5, blocks: [
      { kind: 'paragraph', text: 'firstTranslation.save.body' },
    ] },
    { id: 'export', title: 'firstTranslation.export.title', step: 6, blocks: [
      { kind: 'paragraph', text: 'firstTranslation.export.body' },
      { kind: 'guideReference', label: 'export.title', slug: 'export' },
      { kind: 'image', src: '/images/first-translation/export.webp', caption: 'firstTranslation.images.export' },
      { kind: 'notice', text: 'firstTranslation.export.note' },
    ] },
  ] },
  { slug: 'settings', title: 'settings.title', description: 'settings.description', sections: [
    { id: 'open-and-save', title: 'settings.open.title', blocks: [
      { kind: 'paragraph', text: 'settings.open.body' },
      { kind: 'table', columns: ['settings.buttons.name', 'settings.buttons.action'], rows: [
        { label: 'settings.buttons.save.label', body: 'settings.buttons.save.body' },
        { label: 'settings.buttons.apply.label', body: 'settings.buttons.apply.body' },
        { label: 'settings.buttons.cancel.label', body: 'settings.buttons.cancel.body' },
      ] },
      { kind: 'notice', text: 'settings.open.validation' },
    ] },
    { id: 'application', title: 'settings.application.title', blocks: [
      { kind: 'paragraph', text: 'settings.application.body' },
      { kind: 'definitions', items: [
        { label: 'settings.application.language.label', body: 'settings.application.language.body' },
        { label: 'settings.application.appearance.label', body: 'settings.application.appearance.body' },
        { label: 'settings.application.input.label', body: 'settings.application.input.body' },
      ] },
    ] },
    { id: 'shortcuts', title: 'settings.shortcuts.title', blocks: [
      { kind: 'paragraph', text: 'settings.shortcuts.body' },
      { kind: 'paragraph', text: 'settings.shortcuts.conflicts' },
    ] },
    { id: 'ai', title: 'settings.ai.title', blocks: [
      { kind: 'paragraph', text: 'settings.ai.body' },
      { kind: 'definitions', items: [
        { label: 'settings.ai.auth.label', body: 'settings.ai.auth.body' },
        { label: 'settings.ai.models.label', body: 'settings.ai.models.body' },
        { label: 'settings.ai.test.label', body: 'settings.ai.test.body' },
      ] },
    ] },
    { id: 'translation', title: 'settings.translation.title', blocks: [
      { kind: 'paragraph', text: 'settings.translation.body' },
      { kind: 'definitions', items: [
        { label: 'settings.translation.models.label', body: 'settings.translation.models.body' },
        { label: 'settings.translation.range.label', body: 'settings.translation.range.body' },
        { label: 'settings.translation.concurrency.label', body: 'settings.translation.concurrency.body' },
      ] },
    ] },
    { id: 'tone-and-glossary', title: 'settings.terms.title', blocks: [
      { kind: 'definitions', items: [
        { label: 'settings.terms.tone.label', body: 'settings.terms.tone.body' },
        { label: 'settings.terms.glossary.label', body: 'settings.terms.glossary.body' },
      ] },
      { kind: 'notice', text: 'settings.terms.immediate' },
      { kind: 'guideReference', label: 'glossaryTone.title', slug: 'glossary-tone' },
    ] },
    { id: 'filter-rules', title: 'settings.rules.title', blocks: [
      { kind: 'paragraph', text: 'settings.rules.body' },
      { kind: 'paragraph', text: 'settings.rules.edit' },
    ] },
    { id: 'files', title: 'settings.files.title', blocks: [
      { kind: 'paragraph', text: 'settings.files.body' },
      { kind: 'paragraph', text: 'settings.files.watch' },
      { kind: 'guideReference', label: 'projects.updates.title', slug: 'projects', anchor: 'source-updates' },
      { kind: 'notice', text: 'settings.files.pending' },
    ] },
    { id: 'mcp-and-plugins', title: 'settings.integration.title', blocks: [
      { kind: 'definitions', items: [
        { label: 'settings.integration.mcp.label', body: 'settings.integration.mcp.body' },
        { label: 'settings.integration.resources.label', body: 'settings.integration.resources.body' },
        { label: 'settings.integration.plugins.label', body: 'settings.integration.plugins.body' },
      ] },
    ] },
  ] },
  { slug: 'projects', title: 'projects.title', description: 'projects.description', sections: [
    { id: 'about-projects', title: 'projects.about.title', blocks: [
      { kind: 'paragraph', text: 'projects.about.body' },
      { kind: 'notice', text: 'projects.about.export' },
    ] },
    { id: 'save', title: 'projects.save.title', blocks: [
      { kind: 'paragraph', text: 'projects.save.body' },
      { kind: 'paragraph', text: 'projects.save.as' },
    ] },
    { id: 'reopen', title: 'projects.open.title', blocks: [
      { kind: 'definitions', items: [
        { label: 'projects.open.file.label', body: 'projects.open.file.body' },
        { label: 'projects.open.recent.label', body: 'projects.open.recent.body' },
      ] },
      { kind: 'notice', text: 'projects.open.note' },
    ] },
    { id: 'languages', title: 'projects.languages.title', blocks: [
      { kind: 'paragraph', text: 'projects.languages.body' },
      { kind: 'definitions', items: [
        { label: 'projects.languages.add.label', body: 'projects.languages.add.body' },
        { label: 'projects.languages.custom.label', body: 'projects.languages.custom.body' },
        { label: 'projects.languages.switch.label', body: 'projects.languages.switch.body' },
        { label: 'projects.languages.remove.label', body: 'projects.languages.remove.body' },
      ] },
      { kind: 'notice', text: 'projects.languages.save' },
    ] },
    { id: 'source-updates', title: 'projects.updates.title', blocks: [
      { kind: 'paragraph', text: 'projects.updates.prepare' },
      { kind: 'guideReference', label: 'settings.files.title', slug: 'settings', anchor: 'files' },
      { kind: 'paragraph', text: 'projects.updates.compare' },
      { kind: 'table', columns: ['projects.updates.kind', 'projects.updates.result'], rows: [
        { label: 'projects.updates.add.label', body: 'projects.updates.add.body' },
        { label: 'projects.updates.change.label', body: 'projects.updates.change.body' },
        { label: 'projects.updates.remove.label', body: 'projects.updates.remove.body' },
      ] },
      { kind: 'paragraph', text: 'projects.updates.review' },
      { kind: 'notice', text: 'projects.updates.save' },
    ] },
    { id: 'switch-projects', title: 'projects.switch.title', blocks: [
      { kind: 'paragraph', text: 'projects.switch.body' },
      { kind: 'paragraph', text: 'projects.switch.unsaved' },
    ] },
  ] },
  { slug: 'translation', title: 'translation.title', description: 'translation.description', sections: [
    { id: 'workspace-and-views', title: 'translation.views.title', blocks: [
      { kind: 'paragraph', text: 'translation.views.body' },
      { kind: 'definitions', items: [
        { label: 'translation.views.list.label', body: 'translation.views.list.body' },
        { label: 'translation.views.focus.label', body: 'translation.views.focus.body' },
      ] },
    ] },
    { id: 'search-and-filter', title: 'translation.search.title', blocks: [
      { kind: 'paragraph', text: 'translation.search.body' },
      { kind: 'paragraph', text: 'translation.search.syntax' },
      { kind: 'notice', text: 'translation.search.note' },
    ] },
    { id: 'ai-translation', title: 'translation.ai.title', blocks: [
      { kind: 'definitions', items: [
        { label: 'translation.ai.single.label', body: 'translation.ai.single.body' },
        { label: 'translation.ai.selected.label', body: 'translation.ai.selected.body' },
        { label: 'translation.ai.all.label', body: 'translation.ai.all.body' },
      ] },
      { kind: 'paragraph', text: 'translation.ai.stop' },
      { kind: 'guideReference', label: 'settings.ai.title', slug: 'settings', anchor: 'ai' },
      { kind: 'notice', text: 'translation.ai.exclusions' },
    ] },
    { id: 'compare-models', title: 'translation.models.title', blocks: [
      { kind: 'paragraph', text: 'translation.models.body' },
    ] },
    { id: 'edit-and-confirm', title: 'translation.edit.title', blocks: [
      { kind: 'paragraph', text: 'translation.edit.body' },
      { kind: 'paragraph', text: 'translation.edit.confirm' },
      { kind: 'definitions', items: [
        { label: 'translation.edit.save.label', body: 'translation.edit.save.body' },
        { label: 'translation.edit.revert.label', body: 'translation.edit.revert.body' },
      ] },
      { kind: 'notice', text: 'translation.edit.project' },
    ] },
    { id: 'translation-states', title: 'translation.states.title', blocks: [
      { kind: 'paragraph', text: 'translation.states.body' },
      { kind: 'table', columns: ['translation.states.name', 'translation.states.meaning'], rows: [
        { label: 'translation.states.untranslated.label', body: 'translation.states.untranslated.body' },
        { label: 'translation.states.translated.label', body: 'translation.states.translated.body' },
        { label: 'translation.states.reviewed.label', body: 'translation.states.reviewed.body' },
        { label: 'translation.states.pending.label', body: 'translation.states.pending.body' },
        { label: 'translation.states.doubtful.label', body: 'translation.states.doubtful.body' },
        { label: 'translation.states.protected.label', body: 'translation.states.protected.body' },
        { label: 'translation.states.errors.label', body: 'translation.states.errors.body' },
      ] },
    ] },
    { id: 'shared-translations', title: 'translation.shared.title', blocks: [
      { kind: 'paragraph', text: 'translation.shared.exact' },
      { kind: 'paragraph', text: 'translation.shared.similar' },
    ] },
    { id: 'replace', title: 'translation.replace.title', blocks: [
      { kind: 'paragraph', text: 'translation.replace.body' },
      { kind: 'paragraph', text: 'translation.replace.scope' },
      { kind: 'notice', text: 'translation.replace.pending' },
    ] },
    { id: 'review-tools', title: 'translation.review.title', blocks: [
      { kind: 'definitions', items: [
        { label: 'translation.review.ai.label', body: 'translation.review.ai.body' },
        { label: 'translation.review.display.label', body: 'translation.review.display.body' },
        { label: 'translation.review.problems.label', body: 'translation.review.problems.body' },
      ] },
      { kind: 'paragraph', text: 'translation.review.finish' },
      { kind: 'guideReference', label: 'export.title', slug: 'export' },
    ] },
  ] },
  { slug: 'glossary-tone', title: 'glossaryTone.title', description: 'glossaryTone.description', sections: [
    { id: 'open-and-apply', title: 'glossaryTone.open.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.open.body' },
      { kind: 'paragraph', text: 'glossaryTone.open.apply' },
    ] },
    { id: 'create-glossary', title: 'glossaryTone.glossary.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.glossary.languages' },
      { kind: 'paragraph', text: 'glossaryTone.glossary.create' },
      { kind: 'notice', text: 'glossaryTone.glossary.save' },
    ] },
    { id: 'edit-terms', title: 'glossaryTone.terms.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.terms.add' },
      { kind: 'definitions', items: [
        { label: 'glossaryTone.terms.variants.label', body: 'glossaryTone.terms.variants.body' },
        { label: 'glossaryTone.terms.case.label', body: 'glossaryTone.terms.case.body' },
        { label: 'glossaryTone.terms.memo.label', body: 'glossaryTone.terms.memo.body' },
      ] },
      { kind: 'paragraph', text: 'glossaryTone.terms.search' },
    ] },
    { id: 'inheritance', title: 'glossaryTone.inheritance.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.inheritance.body' },
      { kind: 'paragraph', text: 'glossaryTone.inheritance.edit' },
      { kind: 'notice', text: 'glossaryTone.inheritance.delete' },
    ] },
    { id: 'import-glossary', title: 'glossaryTone.import.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.import.body' },
      { kind: 'definitions', items: [
        { label: 'glossaryTone.import.merge.label', body: 'glossaryTone.import.merge.body' },
        { label: 'glossaryTone.import.new.label', body: 'glossaryTone.import.new.body' },
      ] },
      { kind: 'notice', text: 'glossaryTone.import.note' },
    ] },
    { id: 'export-glossary', title: 'glossaryTone.export.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.export.body' },
      { kind: 'definitions', items: [
        { label: 'glossaryTone.export.own.label', body: 'glossaryTone.export.own.body' },
        { label: 'glossaryTone.export.flat.label', body: 'glossaryTone.export.flat.body' },
        { label: 'glossaryTone.export.tree.label', body: 'glossaryTone.export.tree.body' },
      ] },
    ] },
      { id: 'paratranz-glossary', title: 'glossaryTone.paratranz.title', blocks: [
        { kind: 'paragraph', text: 'glossaryTone.paratranz.import' },
        { kind: 'paragraph', text: 'glossaryTone.paratranz.merge' },
        { kind: 'paragraph', text: 'glossaryTone.paratranz.export' },
        { kind: 'notice', text: 'glossaryTone.paratranz.omitted' },
      ] },
      { id: 'normal-tone', title: 'glossaryTone.tone.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.tone.create' },
      { kind: 'paragraph', text: 'glossaryTone.tone.example' },
      { kind: 'notice', text: 'glossaryTone.tone.save' },
    ] },
    { id: 'conditional-tone', title: 'glossaryTone.conditions.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.conditions.create' },
      { kind: 'paragraph', text: 'glossaryTone.conditions.edit' },
      { kind: 'paragraph', text: 'glossaryTone.conditions.example' },
      { kind: 'paragraph', text: 'glossaryTone.conditions.advanced' },
    ] },
    { id: 'use-in-translation', title: 'glossaryTone.use.title', blocks: [
      { kind: 'paragraph', text: 'glossaryTone.use.select' },
      { kind: 'paragraph', text: 'glossaryTone.use.effect' },
      { kind: 'paragraph', text: 'glossaryTone.use.confirm' },
      { kind: 'guideReference', label: 'translation.title', slug: 'translation' },
    ] },
  ] },
  { slug: 'export', title: 'export.title', description: 'export.description', sections: [
    { id: 'before-export', title: 'export.before.title', blocks: [
      { kind: 'paragraph', text: 'export.before.body' },
      { kind: 'paragraph', text: 'export.before.scope' },
      { kind: 'notice', text: 'export.before.pending' },
    ] },
    { id: 'destination', title: 'export.destination.title', step: 1, blocks: [
      { kind: 'paragraph', text: 'export.destination.open' },
      { kind: 'paragraph', text: 'export.destination.navigate' },
      { kind: 'notice', text: 'export.destination.existing' },
    ] },
    { id: 'format', title: 'export.format.title', step: 2, blocks: [
      { kind: 'paragraph', text: 'export.format.body' },
      { kind: 'table', columns: ['export.format.name', 'export.format.use'], rows: [
        { label: 'export.format.yaml.label', body: 'export.format.yaml.body' },
        { label: 'export.format.json.label', body: 'export.format.json.body' },
        { label: 'export.format.bmfont.label', body: 'export.format.bmfont.body' },
      ] },
    ] },
    { id: 'translation-states', title: 'export.states.title', step: 3, blocks: [
      { kind: 'paragraph', text: 'export.states.body' },
      { kind: 'paragraph', text: 'export.states.fallback' },
      { kind: 'guideReference', label: 'translation.states.title', slug: 'translation', anchor: 'translation-states' },
      { kind: 'notice', text: 'export.states.exchange' },
    ] },
    { id: 'paradox-yaml', title: 'export.yaml.title', blocks: [
      { kind: 'paragraph', text: 'export.yaml.slot' },
      { kind: 'definitions', items: [
        { label: 'export.yaml.layout.label', body: 'export.yaml.layout.body' },
        { label: 'export.yaml.encoding.label', body: 'export.yaml.encoding.body' },
      ] },
      { kind: 'paragraph', text: 'export.yaml.files' },
    ] },
    { id: 'paratranz-json', title: 'export.json.title', blocks: [
      { kind: 'paragraph', text: 'export.json.body' },
      { kind: 'table', columns: ['export.json.state', 'export.json.stage'], rows: [
        { label: 'export.json.untranslated.label', body: 'export.json.untranslated.body' },
        { label: 'export.json.translated.label', body: 'export.json.translated.body' },
        { label: 'export.json.reviewed.label', body: 'export.json.reviewed.body' },
        { label: 'export.json.doubtful.label', body: 'export.json.doubtful.body' },
        { label: 'export.json.locked.label', body: 'export.json.locked.body' },
        { label: 'export.json.hidden.label', body: 'export.json.hidden.body' },
      ] },
      { kind: 'notice', text: 'export.json.reviewNote' },
      { kind: 'links', title: 'export.json.referenceTitle', items: [
        { label: 'export.json.referenceLabel', href: 'https://paratranz.apifox.cn/schema-20805451' },
      ] },
    ] },
    { id: 'bmfont', title: 'export.bmfont.title', blocks: [
      { kind: 'paragraph', text: 'export.bmfont.body' },
      { kind: 'paragraph', text: 'export.bmfont.files' },
    ] },
    { id: 'run-and-check', title: 'export.run.title', step: 4, blocks: [
      { kind: 'paragraph', text: 'export.run.body' },
      { kind: 'paragraph', text: 'export.run.errors' },
    ] },
  ] },
  { slug: 'ai-chat', title: 'aiChat.title', description: 'aiChat.description', sections: [
    { id: 'open-and-send', title: 'aiChat.start.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.start.open' },
      { kind: 'paragraph', text: 'aiChat.start.send' },
      { kind: 'notice', text: 'aiChat.start.model' },
    ] },
    { id: 'references', title: 'aiChat.references.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.references.rows' },
      { kind: 'paragraph', text: 'aiChat.references.inspect' },
      { kind: 'notice', text: 'aiChat.references.snapshot' },
    ] },
    { id: 'attachments', title: 'aiChat.attachments.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.attachments.body' },
      { kind: 'definitions', items: [
        { label: 'aiChat.attachments.images.label', body: 'aiChat.attachments.images.body' },
        { label: 'aiChat.attachments.text.label', body: 'aiChat.attachments.text.body' },
      ] },
    ] },
    { id: 'scope-and-execution', title: 'aiChat.options.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.options.open' },
      { kind: 'table', columns: ['aiChat.options.scope', 'aiChat.options.meaning'], rows: [
        { label: 'aiChat.options.project.label', body: 'aiChat.options.project.body' },
        { label: 'aiChat.options.file.label', body: 'aiChat.options.file.body' },
        { label: 'aiChat.options.selection.label', body: 'aiChat.options.selection.body' },
      ] },
      { kind: 'definitions', items: [
        { label: 'aiChat.options.confirm.label', body: 'aiChat.options.confirm.body' },
        { label: 'aiChat.options.direct.label', body: 'aiChat.options.direct.body' },
      ] },
      { kind: 'notice', text: 'aiChat.options.references' },
    ] },
    { id: 'requests', title: 'aiChat.requests.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.requests.body' },
      { kind: 'definitions', items: [
        { label: 'aiChat.requests.consult.label', body: 'aiChat.requests.consult.body' },
        { label: 'aiChat.requests.find.label', body: 'aiChat.requests.find.body' },
        { label: 'aiChat.requests.edit.label', body: 'aiChat.requests.edit.body' },
        { label: 'aiChat.requests.review.label', body: 'aiChat.requests.review.body' },
      ] },
      { kind: 'paragraph', text: 'aiChat.requests.other' },
      { kind: 'guideReference', label: 'automation.resources.title', slug: 'automation', anchor: 'external-resources' },
    ] },
    { id: 'apply-changes', title: 'aiChat.changes.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.changes.compare' },
      { kind: 'paragraph', text: 'aiChat.changes.apply' },
      { kind: 'paragraph', text: 'aiChat.changes.undo' },
      { kind: 'notice', text: 'aiChat.changes.save' },
    ] },
    { id: 'progress-and-stop', title: 'aiChat.progress.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.progress.body' },
      { kind: 'notice', text: 'aiChat.progress.stop' },
    ] },
    { id: 'voice-input', title: 'aiChat.voice.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.voice.body' },
    ] },
    { id: 'conversation', title: 'aiChat.conversation.title', blocks: [
      { kind: 'paragraph', text: 'aiChat.conversation.display' },
      { kind: 'paragraph', text: 'aiChat.conversation.new' },
      { kind: 'paragraph', text: 'aiChat.conversation.switch' },
    ] },
  ] },
  { slug: 'automation', title: 'automation.title', description: 'automation.description', sections: [
    { id: 'choose-method', title: 'automation.methods.title', blocks: [
      { kind: 'definitions', items: [
        { label: 'automation.methods.script.label', body: 'automation.methods.script.body' },
        { label: 'automation.methods.server.label', body: 'automation.methods.server.body' },
        { label: 'automation.methods.resources.label', body: 'automation.methods.resources.body' },
      ] },
    ] },
    { id: 'script-files', title: 'automation.script.title', blocks: [
      { kind: 'paragraph', text: 'automation.script.open' },
      { kind: 'paragraph', text: 'automation.script.files' },
      { kind: 'paragraph', text: 'automation.script.search' },
    ] },
    { id: 'script-example', title: 'automation.example.title', blocks: [
      { kind: 'paragraph', text: 'automation.example.before' },
      { kind: 'code', text: 'automation.example.code' },
      { kind: 'paragraph', text: 'automation.example.explanation' },
      { kind: 'notice', text: 'automation.example.ids' },
    ] },
    { id: 'script-reference', title: 'automation.reference.title', blocks: [
      { kind: 'paragraph', text: 'automation.reference.body' },
      { kind: 'guideLinks', title: 'automation.reference.links', items: [
        { label: 'scriptReference.title', slug: 'script-reference' },
      ] },
    ] },
    { id: 'run-script', title: 'automation.run.title', blocks: [
      { kind: 'paragraph', text: 'automation.run.start' },
      { kind: 'paragraph', text: 'automation.run.stop' },
      { kind: 'notice', text: 'automation.run.results' },
    ] },
    { id: 'mcp-server', title: 'automation.server.title', blocks: [
      { kind: 'paragraph', text: 'automation.server.enable' },
      { kind: 'paragraph', text: 'automation.server.connect' },
      { kind: 'definitions', items: [
        { label: 'automation.server.read.label', body: 'automation.server.read.body' },
        { label: 'automation.server.edit.label', body: 'automation.server.edit.body' },
        { label: 'automation.server.translate.label', body: 'automation.server.translate.body' },
        { label: 'automation.server.export.label', body: 'automation.server.export.body' },
      ] },
    ] },
    { id: 'mcp-results', title: 'automation.results.title', blocks: [
      { kind: 'paragraph', text: 'automation.results.proposals' },
      { kind: 'paragraph', text: 'automation.results.jobs' },
      { kind: 'paragraph', text: 'automation.results.disable' },
    ] },
    { id: 'external-resources', title: 'automation.resources.title', blocks: [
      { kind: 'paragraph', text: 'automation.resources.add' },
      { kind: 'definitions', items: [
        { label: 'automation.resources.local.label', body: 'automation.resources.local.body' },
        { label: 'automation.resources.http.label', body: 'automation.resources.http.body' },
      ] },
      { kind: 'paragraph', text: 'automation.resources.check' },
      { kind: 'guideReference', label: 'aiChat.title', slug: 'ai-chat' },
      { kind: 'notice', text: 'automation.resources.scope' },
    ] },
  ] },
];
