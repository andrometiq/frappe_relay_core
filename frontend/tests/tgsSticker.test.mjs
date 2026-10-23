import test from 'node:test'
import assert from 'node:assert/strict'
import { gzipSync } from 'node:zlib'
import { validateTgs, decodeTgs, boundedBytes, stickerSource, fetchTgs, MAX_TGS_BYTES } from '../src/components/tgsSticker.js'
const valid = () => ({ v: '5.5.2', w: 512, h: 512, ip: 0, op: 180, fr: 60, assets: [], layers: [{ ty: 4, ddd: 0, ip: 0, op: 180, shapes: [] }] })

test('bounded gzip TGS preserves validated vector animation', async () => {
  const data = valid(), compressed = new Uint8Array(gzipSync(JSON.stringify(data)))
  assert.deepEqual(await decodeTgs(compressed), data)
})
test('rejects invalid canvas/timing, scripts, assets and hazardous layer features', () => {
  for (const change of [
    d => { d.w = 4096 }, d => { d.h = 100 }, d => { d.fr = 120 }, d => { d.op = 181 }, d => { d.op = 0 },
    d => { d.ip = -1 }, d => { d.fr = 1 }, d => { d.layers[0].ty = 2 }, d => { d.layers[0].ty = 5 },
    d => { d.layers[0].ddd = 1 }, d => { d.layers[0].ks = { x: 'fetch("https://evil.invalid")' } },
    d => { d.assets = [{ id: 'img', p: 'https://evil.invalid/file', layers: [] }] },
    d => { d.assets = [{ id: 'img', p: 'data:image/png;base64,abc', layers: [] }] },
    d => { d.layers[0].nm = '<script>alert(1)</script>' }, d => { d.fonts = [] }, d => { d.chars = [] },
    d => { d.layers[0].ef = [] }, d => { d.layers[0].masksProperties = [] }, d => { d.layers[0].tm = { k: 1 } },
    d => { d.layers[0].shapes = [{ ty: 'rp', c: { k: 1000000 } }] },
  ]) { const data = valid(); change(data); assert.throws(() => validateTgs(data), /invalid|limits/) }
  assert.throws(() => validateTgs(JSON.parse('{"v":"5.5.2","w":512,"h":512,"fr":60,"ip":0,"op":60,"layers":[],"__proto__":{"polluted":true}}')))
  assert.equal({}.polluted, undefined)
})
test('valid precomposition renders but cycles and graph expansion are bounded', () => {
  const data = valid(); data.layers = [{ ty: 0, refId: 'asset' }]; data.assets = [{ id: 'asset', layers: [{ ty: 4, shapes: [] }] }]
  assert.equal(validateTgs(data), data)
  data.assets[0].layers = [{ ty: 0, refId: 'asset' }]
  assert.throws(() => validateTgs(data))
  const many = valid(); many.layers = Array.from({ length: 101 }, () => ({ ty: 4, shapes: [] }))
  assert.throws(() => validateTgs(many))
  const deep = valid(); let cursor = deep
  for (let i = 0; i < 34; i++) { cursor.nested = {}; cursor = cursor.nested }
  assert.throws(() => validateTgs(deep))
  const expansion = valid()
  expansion.assets = [{ id: 'expensive', layers: [{ ty: 4, shapes: Array.from({ length: 1000 }, () => ({ ty: 'el', p: { a: 0, k: [0, 0] } })) }] }]
  expansion.layers = Array.from({ length: 20 }, () => ({ ty: 0, refId: 'expensive' }))
  assert.throws(() => validateTgs(expansion))
})
test('rejects corrupted gzip, plain JSON and gzip expansion above 2 MiB', async () => {
  await assert.rejects(decodeTgs(new TextEncoder().encode(JSON.stringify(valid()))))
  await assert.rejects(decodeTgs(new Uint8Array([0x1f, 0x8b, 0, 0])))
  await assert.rejects(decodeTgs(new Uint8Array(gzipSync(' '.repeat(MAX_TGS_BYTES + 1)))))
})
test('bounded read cancels oversized streams and responds to abort', async () => {
  let cancelled = false
  const stream = new ReadableStream({ pull(controller) { controller.enqueue(new Uint8Array(1024)) }, cancel() { cancelled = true } })
  await assert.rejects(boundedBytes(stream, 512)); assert.equal(cancelled, true)
  const abort = new AbortController(); abort.abort()
  await assert.rejects(boundedBytes(new Blob(['x']).stream(), 512, abort.signal), /abort/i)
})
test('only the exact same-site credential-checked message proxy may be fetched', async () => {
  const origin = 'https://relay.example.invalid'
  const source = '/api/method/relay_core.messaging.sticker?message=RELAY-MSG-0001'
  assert.equal(stickerSource(source, origin), origin + source)
  for (const value of ['https://evil.invalid' + source, '//evil.invalid' + source, source + '&url=https://evil.invalid', source + '&message=other', '/api/method/other?message=a', source + '#fragment']) assert.throws(() => stickerSource(value, origin))
  let seen
  const compressed = gzipSync(JSON.stringify(valid()))
  const decoded = await fetchTgs(source, undefined, { origin, fetcher: async (url, opts) => {
    seen = { url, opts }; return new Response(compressed, { status: 200, headers: { 'Content-Type': 'application/x-tgsticker' } })
  } })
  assert.equal(decoded.w, 512); assert.equal(seen.opts.redirect, 'error'); assert.equal(seen.opts.credentials, 'same-origin')
  await assert.rejects(fetchTgs(source, undefined, { origin, fetcher: async () => new Response('', { status: 403 }) }))
})
