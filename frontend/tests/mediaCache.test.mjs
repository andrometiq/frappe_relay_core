import test from 'node:test'
import assert from 'node:assert/strict'
import { loadMedia, formatBytes } from '../src/services/mediaCache.js'
import { documentType } from '../src/components/messageContent.js'

let created = 0
globalThis.URL.createObjectURL = () => 'blob:media-' + ++created
globalThis.URL.revokeObjectURL = () => {}
const media = (bytes = 3) => ({ ok: true, status: 200, blob: async () => ({ type: 'image/jpeg', size: bytes }) })
const failure = (status, message) => ({ ok: false, status,
  json: async () => ({ exc_type: 'MediaGone', _server_messages: JSON.stringify([JSON.stringify({ message })]) }) })

test('one download serves every bubble of the same message for the session', async t => {
  const requests = []
  t.mock.method(globalThis, 'fetch', async url => { requests.push(url); return media() })
  const [first, second] = await Promise.all([loadMedia('RELAY-MSG-0000000101'), loadMedia('RELAY-MSG-0000000101')])
  assert.equal(first, second)
  assert.equal((await loadMedia('RELAY-MSG-0000000101')).url, first.url)
  assert.deepEqual(requests, ['/api/method/relay_core.attachments.read?message=RELAY-MSG-0000000101'])
})

test('expired WhatsApp media shows the server reason without a retry; a busy Hub can be retried', async t => {
  t.mock.method(globalThis, 'fetch', async () => failure(410, 'Media no longer available from WhatsApp'))
  await assert.rejects(loadMedia('RELAY-MSG-0000000102'), { message: 'Media no longer available from WhatsApp', retry: false })
  t.mock.method(globalThis, 'fetch', async () => failure(503, 'Media downloads are busy. Try again shortly.'))
  await assert.rejects(loadMedia('RELAY-MSG-0000000103'), { retry: true })
  t.mock.method(globalThis, 'fetch', async () => media())
  assert.match((await loadMedia('RELAY-MSG-0000000103')).url, /^blob:/, 'a failure is not cached')
  t.mock.method(globalThis, 'fetch', async () => { throw TypeError('network') })
  await assert.rejects(loadMedia('RELAY-MSG-0000000104'), { retry: true, message: /Connection lost/ })
})

test('a thread full of media keeps at most two downloads open at once', async t => {
  let open = 0, peak = 0
  t.mock.method(globalThis, 'fetch', async () => {
    peak = Math.max(peak, ++open)
    await new Promise(resolve => setTimeout(resolve, 5))
    open--
    return media()
  })
  await Promise.all([105, 106, 107, 108, 109].map(id => loadMedia('RELAY-MSG-0000000' + id)))
  assert.equal(peak, 2)
})

test('document cards show a short type and a readable size', () => {
  assert.equal(documentType({ filename: '01.04.2024 to 31.03.2025 final letter.docx', mime_type: 'application/octet-stream' }), 'DOCX')
  assert.equal(documentType({ mime_type: 'application/pdf' }), 'PDF')
  assert.equal(documentType({ mime_type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document' }), 'Document')
  assert.equal(formatBytes(24576), '24 KB')
  assert.equal(formatBytes(1572864), '1.5 MB')
  assert.equal(formatBytes(undefined), '')
})
