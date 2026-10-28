import test from 'node:test'
import assert from 'node:assert/strict'
import { phoneCaption } from '../src/services/phoneNumber.js'

test('a bare number becomes a readable phone caption', () => {
  assert.equal(phoneCaption('918549974206'), '+91 85499 74206')
  assert.equal(phoneCaption('+918549974206'), '+91 85499 74206')
  assert.equal(phoneCaption('8549974206'), '85499 74206')
  assert.equal(phoneCaption('+44 20 7946 0958'), '+442079460958')
})

test('names, record keys and short codes are not phone captions', () => {
  for (const value of ['DEEPAK KUMAR', 'RELAY-CON-0000032984', '12345', '', null, 'a1b2c3d4e5f6']) assert.equal(phoneCaption(value), '')
})
