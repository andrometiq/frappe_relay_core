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
