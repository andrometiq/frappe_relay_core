import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'

const read = path => readFile(new URL('../src/' + path, import.meta.url), 'utf8')

test('a mobile number and an email each carry their own icon and spoken label', async () => {
  const component = await read('components/messages/ContactEndpoints.vue')
  assert.match(component, /<span v-if="phone"[^>]*title="Mobile"><FeatherIcon name="phone"[^]*Mobile:<\/span>\{\{ phone \}\}/)
  assert.match(component, /<span v-if="email"[^>]*title="Email"><FeatherIcon name="mail"[^]*Email:<\/span>\{\{ email \}\}/)
  const start = await read('components/messages/StartConversation.vue')
  assert.match(start, /<ContactEndpoints :phone="row\.phone" :email="row\.email"/)
})

test('phone dialogs open as bottom sheets as tall as their content', async () => {
  const mobile = await read('mobile.css')
  const sheet = mobile.match(/\.relay-dialog,\.relay-dialog--sm,\.relay-dialog--lg,\.relay-dialog--xl\{([^}]*)\}/)[1]
  assert.match(sheet, /height:auto;max-height:calc\(var\(--relay-viewport-height,100dvh\) - 24px\)/)
  assert.match(sheet, /border-radius:16px 16px 0 0/)
  assert.match(mobile, /\.relay-dialog-mask\{align-items:flex-end;padding:0\}/)
  assert.match(mobile, /\.relay-dialog::before\{content:''/, 'A grab handle marks the sheet')
})
