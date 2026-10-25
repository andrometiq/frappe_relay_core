import test from 'node:test'
import assert from 'node:assert/strict'
import { messageData, stickerURL, mapURL, reactionLabels } from '../src/components/messageContent.js'

test('message data preserves typed values and only creates protected same-origin sticker paths', () => {
  assert.equal(messageData({message_data:'{"kind":"location","location":{"latitude":0,"longitude":0}}'}).location.latitude, 0)
  assert.equal(stickerURL('RELAY-MSG-0000000001'), '/api/method/relay_core.messaging.sticker?message=RELAY-MSG-0000000001')
  for (const value of ['https://evil.invalid', '../token', 'RELAY-MSG-1', '<svg>']) assert.equal(stickerURL(value), '')
  assert.deepEqual(messageData({content:'fallback'}), {kind:'text',text:'fallback'})
})
test('maps accept zero coordinates but reject nonfinite and injected values', () => {
  assert.match(mapURL({latitude:0, longitude:0}), /^https:\/\/www.openstreetmap.org\//)
  for(const location of [{latitude:NaN,longitude:0},{latitude:91,longitude:0},{latitude:'javascript:alert(1)',longitude:0}]) assert.equal(mapURL(location), '')
})
test('aggregate reaction counts supersede actor observations without double counting', () => {
  assert.deepEqual(reactionLabels({'1':[{type:'emoji',emoji:'👍'}],_counts:[{type:{type:'emoji',emoji:'👍'},count:3}]}), ['👍 3'])
  assert.deepEqual(reactionLabels({'1':[]}), [])
  assert.equal(reactionLabels({_counts:Array(100).fill({type:{emoji:'👍'},count:1})}).length,20)
})

test('voice transcripts show stored text or an honest status', async () => {
  const { transcriptState } = await import('../src/components/messageContent.js')
  assert.deepEqual(transcriptState({ transcript: 'Send the blue shirts', transcript_status: 'Completed' }), { state: 'available', text: 'Send the blue shirts' })
  assert.equal(transcriptState({ transcript_status: 'Pending' }).text, 'Transcript pending…')
  assert.match(transcriptState({ transcript_status: 'Unavailable' }).text, /^Transcript unavailable/)
  assert.match(transcriptState({ transcript_status: 'Failed' }).text, /failed/)
  assert.equal(transcriptState({}).state, 'legacy')
})
test('unsupported messages show the WhatsApp reason and order lines stay readable', async () => {
  const { unsupportedNotice, orderLines } = await import('../src/components/messageContent.js')
  assert.deepEqual(unsupportedNotice({ kind: 'unsupported', unsupported: { reason: 'Poll messages are not supported by WhatsApp Business', details: 'Message type is currently not supported.', code: 131051 } }),
    { reason: 'Poll messages are not supported by WhatsApp Business', meta: 'Message type is currently not supported. · code 131051' })
  assert.equal(unsupportedNotice({ kind: 'unsupported' }).reason, 'This message type is not supported')
  assert.deepEqual(orderLines({ order: { items: [{ product_retailer_id: 'shirt', quantity: 2, item_price: 30, currency: 'INR' }, { product_retailer_id: 'cap' }] } }),
    ['2 × shirt · INR 30', '1 × cap'])
})
