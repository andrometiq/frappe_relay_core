import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { navAllowed } from '../src/services/navigation.js'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')
const skills = { name: 'Skills', ai: true, skills: true }
const manager = { enabled_channels: ['WhatsApp'], manage: true, skills: true }

test('the AI skills page shows only while AI features are on', () => {
  assert.equal(navAllowed(skills, { ...manager, ai: false }), false)
  assert.equal(navAllowed(skills, { ...manager, ai: true }), true)
  assert.equal(navAllowed({ name: 'Business events', business_events: true }, { ...manager, ai: false, business_events: true }), true)
})

test('the sidebar AI skills item carries the AI gate', async () => {
  assert.match(await read('SiteApp.vue'), /name: 'Skills'[^}]*ai: true/)
})

test('conversation summary and ticket AI controls follow the AI flag', async () => {
  const messages = await read('components/ConnectedMessages.vue')
  assert.match(messages, /<ConversationSummary v-if="[^"]*capabilities\.ai"/)
  const tickets = await read('components/TicketsWorkspace.vue')
  assert.match(tickets, /<TicketDialog [^>]*:ai-enabled="aiEnabled"/)
  const dialog = await read('components/tickets/TicketDialog.vue')
  assert.match(dialog, /<section v-if="aiEnabled && ticket\.conversation_key/)
})

test('only a System Manager sees the AI switch in Settings', async () => {
  const settings = await read('components/SiteSettings.vue')
  assert.match(settings, /v-if="config\.can_switch_ai" class="workflow-card settings-features"/)
  assert.match(settings, /\{ key: 'ai', label: 'Enable AI features'/)
})


test('knowledge and events pages and direct content loads require AI', async () => {
  const app = await read('SiteApp.vue')
  for (const name of ['Knowledge', 'Events']) {
    assert.match(app, new RegExp("name: '" + name + "'[^}]*ai: true"))
    assert.equal(navAllowed({name, ai:true, skills:true}, {...manager, ai:false}), false)
    assert.equal(navAllowed({name, ai:true, skills:true}, {...manager, ai:true}), true)
  }
  const content = await read('components/AIContentWorkspace.vue')
  assert.match(content, /capabilities.value.ai && capabilities.value.skills/)
  assert.match(content, /if \(!allowed.value\)/)
  assert.match(content, /ai.knowledge/)
  assert.match(content, /ai.events/)
  const editor = await read('components/AutomationWorkspace.vue')
  assert.match(editor, /capabilities.value.ai && capabilities.value.skills/)
  assert.match(editor, /Configured reports/)
  assert.doesNotMatch(editor, /label="Memory and rules"/)
})

test('flow picker and existing AI step controls follow live capabilities without dropping nodes', async () => {
  const Vue = await import('vue')
  const { compile } = await import('@vue/compiler-dom')
  const { renderToString } = await import('vue/server-renderer')
  const editor = await import('../src/services/flowEditor.js')
  const source = await read('components/FlowsWorkspace.vue')
  const template = source.match(/<ol class="flow-steps">[\s\S]*?<\/ol>/)[0]
    + source.match(/<div class="flow-add">[^\n]+/)[0]
  const render = new Function('Vue', compile(template, { prefixIdentifiers: true }).code)(Vue)
  const capabilities = Vue.ref({ flows: true, manage: true, ai: true })
  const draft = Vue.ref({ nodes: [{ ...editor.newStep('ai_skill', []), ai_skill: 'Local support' }] })
  const stepKind = Vue.ref('ai_skill')
  const availableStepKinds = new Function('computed', 'STEP_KINDS', 'capabilities',
    source.match(/const availableStepKinds = [^\n]+/)[0] + '; return availableStepKinds')(
      Vue.computed, editor.STEP_KINDS, capabilities)
  const addStep = new Function('availableStepKinds', 'draft', 'stepKind', 'newStep',
    source.match(/function addStep\(\) \{[\s\S]*?\n\}/)[0] + '; return addStep')(
      availableStepKinds, draft, stepKind, editor.newStep)
  const view = { ...editor, capabilities, draft, stepKind, availableStepKinds, addStep,
    stepGroup: 'Standard', canEdit: true, busy: false, stepOptions: [], stepReference: () => ({ label: 'AI skill' }) }
  const FormControl = { props: ['label', 'options'], setup: props => () => Vue.h('label', [props.label,
    ...(props.options || []).map(option => Vue.h('option', option.label || option))]) }
  const app = Vue.createSSRApp({ render, setup: () => view, components: {
    FormControl, RemoteLinkField: { setup: () => () => Vue.h('input', { 'aria-label': 'AI skill' }) },
    Button: { props: ['label'], setup: props => () => Vue.h('button', props.label) },
  } })
  assert.match(await renderToString(app), /Run AI skill/)
  assert.match(await renderToString(app), /After the skill completes/)
  for (const ai of [false, undefined]) {
    capabilities.value.ai = ai
    const html = await renderToString(app)
    assert.doesNotMatch(html, /Run AI skill|After the skill completes|aria-label="AI skill"|Repeat limit/)
    assert.match(html, /Ask a question/)
    assert.match(html, /AI features are turned off/)
    addStep() // A stale selection cannot add AI after the switch is turned off.
    assert.equal(draft.value.nodes.length, 1)
    assert.equal(draft.value.nodes[0].ai_skill, 'Local support')
  }
  capabilities.value.ai = true
  addStep()
  assert.equal(draft.value.nodes.length, 2)
  assert.match(await renderToString(app), /After the skill completes/)
})
