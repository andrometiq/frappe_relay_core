import test from 'node:test'
import assert from 'node:assert/strict'
import { legacyConversation, openLegacyConversation } from '../src/services/legacyLinks.js'

const place = hash => ({ hash, replaced: null, replace(target) { this.replaced = target } })

test('only a messages link with a legacy conversation is resolved', () => {
  assert.equal(legacyConversation('#/messages?legacy_conversation=vs31'), 'vs31')
  assert.equal(legacyConversation('#/messages?contact=CON-1'), null)
  assert.equal(legacyConversation('#/flows?legacy_conversation=vs31'), null)
})

test('an imported chat opens its Relay contact', async () => {
  const location = place('#/messages?legacy_conversation=vs31')
  await openLegacyConversation(location, async (method, values) => {
    assert.equal(method, 'whatsapp_redirects.conversation_contact')
    assert.deepEqual(values, { conversation: 'vs31' })
    return { contact: 'CON-0001' }
  })
  assert.equal(location.replaced, '#/messages?contact=CON-0001')
})

test('an unknown or forbidden chat falls back to the inbox', async () => {
  for (const api of [async () => ({ contact: null }), async () => { throw new Error('Forbidden') }]) {
    const location = place('#/messages?legacy_conversation=vs31')
    await openLegacyConversation(location, api)
    assert.equal(location.replaced, '#/messages')
  }
  const untouched = place('#/messages')
  await openLegacyConversation(untouched, async () => assert.fail('no request'))
  assert.equal(untouched.replaced, null)
})
