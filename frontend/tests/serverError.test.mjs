import test from 'node:test'
import assert from 'node:assert/strict'
import { serverError } from '../src/services/serverError.js'

test('Frappe validation messages survive the API boundary as text', () => {
  assert.equal(serverError({ _server_messages: JSON.stringify([JSON.stringify({ message: 'Choose a <b>team member</b>.' })]) }, 'Fallback'), 'Choose a team member.')
  assert.equal(serverError({ _server_messages: '{broken', exception: 'Secret traceback' }, 'Fallback'), 'Fallback')
  assert.equal(serverError({ message: 'Channel disabled' }, 'Fallback'), 'Channel disabled')
})

test('a web page stored as a delivery error shows as a short reason', async () => {
  const { deliveryError } = await import('../src/services/serverError.js')
  const page = '<!DOCTYPE html> <!-- Built on Frappe --> <html lang="en"><head><meta name="title" content="404"><title>Page not found</title></head></html>'
  assert.equal(deliveryError(page), 'Send failed: the server returned a web page (404) instead of a WhatsApp reply.')
  assert.equal(deliveryError('<html><body>oops</body></html>'), 'Send failed: the server returned a web page instead of a WhatsApp reply.')
  assert.equal(deliveryError('Recipient is not on WhatsApp'), 'Recipient is not on WhatsApp')
})

test('escaped angle brackets are shown as characters', async () => {
  const { serverError } = await import('../src/services/serverError.js')
  assert.equal(serverError({ message: 'Name cannot contain &lt; or &gt;' }, 'x'), 'Name cannot contain < or >')
})
