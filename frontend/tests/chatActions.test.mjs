import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { channelOffText, plainChatError } from '../src/services/chatErrors.js'
import { ownReaction } from '../src/components/messageContent.js'
const read = path => readFile(new URL('../src/components/' + path, import.meta.url), 'utf8')

test('a switched-off channel error reads as a plain sentence', () => {
  assert.equal(plainChatError('Conversation channel is disabled or belongs to another account'), 'This WhatsApp number is switched off. Ask your manager.')
  assert.equal(plainChatError('Choose a file up to 4 MiB.'), 'Choose a file up to 4 MiB.')
  assert.equal(plainChatError(undefined), '')
  assert.equal(channelOffText('Telegram'), 'This Telegram channel is switched off. Ask your manager.')
})

test('own reaction is the emoji stored for this site, else empty', () => {
  assert.equal(ownReaction({ bot: [{ type: 'emoji', emoji: '👍' }], '9198': [{ emoji: '❤' }] }), '👍')
  assert.equal(ownReaction(JSON.stringify({ bot: [] })), '')
  assert.equal(ownReaction({ '9198': [{ emoji: '❤' }] }), '')
})

test('one chevron opens one menu: reply first, info before the divider, team actions after', async () => {
  const thread = await read('messages/MessageThread.vue')
  assert.equal((thread.match(/aria-label="Message actions"/g) || []).length, 1)
  assert.doesNotMatch(thread, /label="Add reaction"|label="Reply"|Close reactions/)
  const actions = thread.split('function actions(message)')[1].split('return items')[0]
  const labels = [...actions.matchAll(/label: ["']([^"']+)["']|divider: true/g)].map(match => match[1] || '---')
  assert.deepEqual(labels, ['Reply', 'Copy text', 'Download', 'Message info', 'Resend sticker', '---', 'Add internal note', 'Create ticket'])
  assert.match(thread, /<MessageMenu v-if="menu"[^>]*:area="viewport"/)
})

test('the reaction pill has no close buttons and offers removal only after a reaction', async () => {
  const picker = await read('messages/ReactionPicker.vue')
  assert.doesNotMatch(picker, /icon="x"|×|Close/)
  assert.match(picker, /<button v-if="props\.current"[^>]*>Remove reaction<\/button>/)
  assert.match(picker, /event\.key === 'Escape'/)
})

test('message info has no internal reference or coverage jargon', async () => {
  const info = await read('messages/MessageInfoDialog.vue')
  assert.doesNotMatch(info, /Message reference|coverage requirement|assigned operators/)
  for (const label of ['Sent', 'Delivered', 'Read']) assert.match(info, new RegExp(`label: '${label}'`))
})
