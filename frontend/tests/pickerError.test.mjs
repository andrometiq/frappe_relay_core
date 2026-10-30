import test from 'node:test'
import assert from 'node:assert/strict'
import { pickerError } from '../src/services/pickerError.js'

test('picker errors give field-specific staff guidance without technical terms', () => {
  assert.match(pickerError('Business type'), /business type.*Try again/)
  assert.match(pickerError('Audience business types', true), /saved selection for audience business types/)
  assert.doesNotMatch(pickerError('Business type'), /DocType/)
})
