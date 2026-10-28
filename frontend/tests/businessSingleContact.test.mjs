import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const connected = await readFile(new URL('../src/components/ConnectedMessages.vue', import.meta.url), 'utf8')

test('a business record with one contact opens on that contact so the composer shows', () => {
  assert.match(connected, /const only = linkedContacts\.value\.length === 1 \? linkedContacts\.value\[0\]\.value : ""/)
  assert.match(connected, /if \(!pickSingleContact \|\| busy\.value \|\| !businessName\.value \|\| !messagesByContact\.value\.has\(only\)\) return/)
  assert.match(connected, /if \(!source\.value && \[only, ""\]\.includes\(activeBusinessContact\.value\)\) chooseContact\(only\)/)
})

test('each business record picks its single contact once and "All" keeps the user choice', () => {
  assert.match(connected, /activeBusinessContact\.value = "";\n  pickSingleContact = true;/)
  assert.match(connected, /function showAllContacts\(\) \{\n  if \(busy\.value\) return;\n  pickSingleContact = false;/)
  assert.match(connected, /const chooseRecipient = computed\(\(\) => !!businessName\.value && linkedContacts\.value\.length > 1\)/)
})
