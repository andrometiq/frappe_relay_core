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
