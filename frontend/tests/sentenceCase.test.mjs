import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { sentenceCase } from '../src/services/textCase.js'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')

test('provider codes and labels show in sentence case, never in capitals', async () => {
  assert.equal(sentenceCase('PENDING_DELETION'), 'Pending deletion')
  assert.equal(sentenceCase('MARKETING'), 'Marketing')
  assert.equal(sentenceCase(null), '')
  for (const path of ['style.css', 'mobile.css', 'components/messages/ReadByBubble.vue']) assert.doesNotMatch(await read(path), /text-transform:\s*uppercase|\buppercase\b/)
})
