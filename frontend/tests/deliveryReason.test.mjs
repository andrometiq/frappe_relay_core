import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { deliveryReason } from '../src/services/deliveryReason.js'
const read = path => readFile(new URL('../src/components/' + path, import.meta.url), 'utf8')

test('a known WhatsApp error code reads as a plain reason', () => {
  assert.match(deliveryReason('Message undeliverable (code 131026)'), /could not deliver this message/)
  assert.match(deliveryReason('Re-engagement message (code 131047)'), /24-hour reply window is closed/)
  assert.match(deliveryReason('WhatsApp rejected this request (code 131047): Re-engagement message'), /24-hour reply window is closed/)
})

test('an unknown code keeps the provider text, and a missing reason still explains the failure', () => {
  assert.equal(deliveryReason('Something odd (code 1)'), 'Something odd (code 1)')
  assert.equal(deliveryReason(''), 'This message was not delivered.')
  assert.equal(deliveryReason(undefined), 'This message was not delivered.')
  assert.match(deliveryReason('<!doctype html><title>Not Found</title>'), /returned a web page \(Not Found\)/)
})

test('an undelivered sent message shows its reason on tap and offers Retry through the server', async () => {
  const thread = await read('messages/MessageThread.vue'), messages = await read('ConnectedMessages.vue')
  assert.match(thread, /const isUndelivered = message => !message\._pending && message\.direction === 'Outgoing' && message\.status === 'Failed'/)
  assert.match(thread, /if \(isUndelivered\(message\)\) items\.unshift\(\{ label: "Retry"[^}]*emit\("retry", message\)/)
  assert.match(thread, /<button v-if="isUndelivered\(message\)"[^>]*:title="deliveryReason\(message\.delivery_error\)"/)
  assert.match(messages, /@retry="retryMessage"/)
  assert.match(messages, /if \(message\._pending\) return state\.retryPending\(message\);/)
  assert.match(messages, /coreApi\('messaging\.retry', \{ message: message\.name \}, true\)/)
  assert.match(messages, /label:'Delivery failures and retry'[^}]*deliveriesOpen\.value = true/)
})

test('message info always gives a reason for a failed message', async () => {
  const info = await read('messages/MessageInfoDialog.vue')
  assert.match(info, /<div v-if="failed"><dt>Reason<\/dt><dd>\{\{ deliveryReason\(info\.delivery_error\) \}\}/)
})
