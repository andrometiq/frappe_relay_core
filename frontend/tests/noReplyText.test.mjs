import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { canStartChat, noReplyText } from '../src/services/chatErrors.js'

test('a business contact with a mobile but no chat is offered a WhatsApp template', () => {
  assert.equal(noReplyText({ contact: { label: 'Karthikeyan S', phone: '7790844803' } }), 'No WhatsApp chat with Karthikeyan S yet. Start one with a template.')
})

test('a contact without a mobile, an unpicked contact and an empty chat each get their own sentence', () => {
  assert.equal(noReplyText({ contact: { label: 'Ajith', phone: '' } }), 'Ajith has no mobile number for WhatsApp. Add one to the contact first.')
  assert.equal(noReplyText({ choosing: true }), 'Choose a contact above to reply on WhatsApp.')
  assert.equal(noReplyText(), 'No WhatsApp chat yet. Start one with a template.')
})

test('the chat never says that no channel is available', async () => {
  const connected = await readFile(new URL('../src/components/ConnectedMessages.vue', import.meta.url), 'utf8')
  assert.doesNotMatch(connected, /No channel is available/)
  assert.equal((connected.match(/\{\{ noReplyCopy \}\}/g) || []).length, 2)
})

test('a number saved on another contact gives that reason instead of offering a template', () => {
  const contact = { label: 'Karthikeyan S', phone: '7790844803', number_elsewhere: true }
  assert.match(noReplyText({ contact }), /saved on another contact too, so WhatsApp cannot start here/)
  assert.doesNotMatch(noReplyText({ contact }), /Start one with a template/)
})

test('the start button shows only when the chat can start', async () => {
  assert.equal(canStartChat({ label: 'sajini', phone: '9150031035' }), true)
  assert.equal(canStartChat({ label: 'Ajith', phone: '' }), false)
  assert.equal(canStartChat({ label: 'Karthikeyan S', phone: '7790844803', number_elsewhere: true }), false)
  assert.equal(canStartChat(null), true)
  const connected = await readFile(new URL('../src/components/ConnectedMessages.vue', import.meta.url), 'utf8')
  assert.match(connected, /<Button v-if="canStartChat\(replyContact\)"[^>]*@click="startInChat\(\)"/)
})
