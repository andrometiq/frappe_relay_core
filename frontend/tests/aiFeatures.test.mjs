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
  assert.match(messages, /businessName\.value && capabilities\.value\?\.ai \? \[\{label:'Conversation summary'/)
  assert.match(messages, /<ConversationSummary v-if="[^"]*capabilities\.ai"/)
  const tickets = await read('components/TicketsWorkspace.vue')
  assert.match(tickets, /aiEnabled\.value \? refreshWindow\('ai_history'/)
  assert.match(tickets, /<section v-if="aiEnabled" aria-label="AI history"/)
  assert.match(tickets, /<div v-if="aiEnabled && selected\.conversation_key/)
})

test('only a System Manager sees the AI switch in Settings', async () => {
  assert.match(await read('components/SiteSettings.vue'), /v-if="config\.can_switch_ai"[^>]*><FormControl type="checkbox" label="Enable AI features"/)
})
