import test from 'node:test'
import assert from 'node:assert/strict'
import { deliveryDetails } from '../src/services/deliveryDetails.js'

test('sparse Hub deliveries retain the provider reference and correctly labelled schedule', () => {
  assert.deepEqual(deliveryDetails({id:'123',next_attempt:'2026-10-30',result:{messages:[{id:'wamid.sim.123'}]}}),
    {recipient:'',message:'wamid.sim.123',time:'2026-10-30',timeLabel:'Scheduled attempt'})
  assert.deepEqual(deliveryDetails({id:'124'}), {recipient:'',message:'',time:'',timeLabel:''})
})
test('recipient and actual send time are preferred when present', () => {
  assert.deepEqual(deliveryDetails({recipient:'+918000000001',message_id:'msg',sent_at:'2026-10-30',next_attempt:'2026-10-29'}),
    {recipient:'+918000000001',message:'msg',time:'2026-10-30',timeLabel:'Sent'})
})
