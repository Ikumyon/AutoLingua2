import type { GuidePage } from './content';

export const scriptReference: GuidePage = {
  slug: 'script-reference',
  parentSlug: 'automation',
  title: 'scriptReference.title',
  navTitle: 'scriptReference.navTitle',
  description: 'scriptReference.description',
  sections: [
    { id: 'script-syntax', title: 'automation.spec.syntax.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.syntax.body' },
      { kind: 'paragraph', text: 'automation.spec.syntax.names' },
      { kind: 'paragraph', text: 'automation.spec.syntax.literals' },
      { kind: 'code', text: 'automation.spec.syntax.code' },
    ] },
    { id: 'script-types', title: 'automation.spec.types.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.types.body' },
      { kind: 'paragraph', text: 'automation.spec.types.initialization' },
      { kind: 'paragraph', text: 'automation.spec.types.arrays' },
      { kind: 'code', text: 'automation.spec.types.code' },
    ] },
    { id: 'script-operators', title: 'automation.spec.operators.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.operators.body' },
      { kind: 'table', columns: ['automation.spec.operators.symbol', 'automation.spec.operators.rule'], rows: [
        { label: 'automation.spec.operators.unary.label', body: 'automation.spec.operators.unary.body' },
        { label: 'automation.spec.operators.product.label', body: 'automation.spec.operators.product.body' },
        { label: 'automation.spec.operators.sum.label', body: 'automation.spec.operators.sum.body' },
        { label: 'automation.spec.operators.order.label', body: 'automation.spec.operators.order.body' },
        { label: 'automation.spec.operators.equal.label', body: 'automation.spec.operators.equal.body' },
        { label: 'automation.spec.operators.and.label', body: 'automation.spec.operators.and.body' },
        { label: 'automation.spec.operators.or.label', body: 'automation.spec.operators.or.body' },
      ] },
      { kind: 'notice', text: 'automation.spec.operators.division' },
    ] },
    { id: 'script-control', title: 'automation.spec.control.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.control.if' },
      { kind: 'paragraph', text: 'automation.spec.control.for' },
      { kind: 'paragraph', text: 'automation.spec.control.scope' },
      { kind: 'code', text: 'automation.spec.control.code' },
    ] },
    { id: 'script-functions', title: 'automation.spec.functions.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.functions.definition' },
      { kind: 'paragraph', text: 'automation.spec.functions.return' },
      { kind: 'paragraph', text: 'automation.spec.functions.scope' },
      { kind: 'code', text: 'automation.spec.functions.code' },
    ] },
    { id: 'script-commands', title: 'automation.commands.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.screen.body' },
      { kind: 'table', columns: ['automation.commands.name', 'automation.commands.action'], rows: [
        { label: 'automation.commands.click.label', body: 'automation.commands.click.body' },
        { label: 'automation.commands.row.label', body: 'automation.commands.row.body' },
        { label: 'automation.commands.combo.label', body: 'automation.commands.combo.body' },
        { label: 'automation.commands.spin.label', body: 'automation.commands.spin.body' },
        { label: 'automation.spec.screen.add.label', body: 'automation.spec.screen.add.body' },
        { label: 'automation.spec.screen.sub.label', body: 'automation.spec.screen.sub.body' },
      ] },
    ] },
    { id: 'script-auto-wait', title: 'automation.spec.autoWait.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.autoWait.body' },
      { kind: 'code', text: 'automation.spec.autoWait.code' },
      { kind: 'notice', text: 'automation.spec.autoWait.result' },
    ] },
    { id: 'script-reading', title: 'automation.spec.read.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.read.body' },
      { kind: 'table', columns: ['automation.commands.name', 'automation.commands.action'], rows: [
        { label: 'automation.spec.read.spin.label', body: 'automation.spec.read.spin.body' },
        { label: 'automation.spec.read.combo.label', body: 'automation.spec.read.combo.body' },
        { label: 'automation.spec.read.text.label', body: 'automation.spec.read.text.body' },
        { label: 'automation.spec.read.check.label', body: 'automation.spec.read.check.body' },
        { label: 'automation.spec.read.slider.label', body: 'automation.spec.read.slider.body' },
        { label: 'automation.spec.read.row.label', body: 'automation.spec.read.row.body' },
      ] },
      { kind: 'code', text: 'automation.spec.read.code' },
    ] },
    { id: 'script-limits', title: 'automation.spec.limits.title', blocks: [
      { kind: 'paragraph', text: 'automation.spec.limits.wait' },
      { kind: 'paragraph', text: 'automation.spec.limits.unsupported' },
      { kind: 'table', columns: ['automation.spec.limits.error', 'automation.spec.limits.fix'], rows: [
        { label: 'automation.spec.limits.syntax.label', body: 'automation.spec.limits.syntax.body' },
        { label: 'automation.spec.limits.target.label', body: 'automation.spec.limits.target.body' },
        { label: 'automation.spec.limits.value.label', body: 'automation.spec.limits.value.body' },
        { label: 'automation.spec.limits.active.label', body: 'automation.spec.limits.active.body' },
      ] },
    ] },
    { id: 'back-to-automation', title: 'scriptReference.back.title', blocks: [
      { kind: 'guideLinks', title: 'scriptReference.back.links', items: [
        { label: 'automation.title', slug: 'automation' },
      ] },
    ] },
  ],
};
