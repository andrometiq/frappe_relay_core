import test from 'node:test'
import assert from 'node:assert/strict'
import { serverError } from '../src/services/serverError.js'

test('Frappe validation messages survive the API boundary as text', () => {
  assert.equal(serverError({ _server_messages: JSON.stringify([JSON.stringify({ message: 'Choose a <b>team member</b>.' })]) }, 'Fallback'), 'Choose a team member.')
  assert.equal(serverError({ _server_messages: '{broken', exception: 'Secret traceback' }, 'Fallback'), 'Fallback')
  assert.equal(serverError({ message: 'Channel disabled' }, 'Fallback'), 'Channel disabled')
})
