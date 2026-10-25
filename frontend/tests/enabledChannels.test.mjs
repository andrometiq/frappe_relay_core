import test from 'node:test'
import assert from 'node:assert/strict'
import { channelEnabled, mediumOptions } from '../src/services/enabledChannels.js'

test('only the enabled channels are offered and messages without a provider stay visible', () => {
  const whatsapp = { enabled_channels: ['WhatsApp'] }
  assert.equal(channelEnabled(whatsapp, 'WhatsApp'), true)
  assert.equal(channelEnabled(whatsapp, 'Telegram'), false)
  assert.equal(channelEnabled(whatsapp, 'Email'), false)
  assert.equal(channelEnabled(whatsapp, undefined), true)
  assert.equal(channelEnabled({}, 'WhatsApp'), false)
})

test('inbox filter offers All channels only when every provider is enabled', () => {
  assert.deepEqual(mediumOptions({ enabled_channels: ['WhatsApp'] }), ['WhatsApp'])
  assert.deepEqual(mediumOptions({ enabled_channels: ['WhatsApp', 'Email'] }), ['WhatsApp', 'Email'])
  assert.deepEqual(mediumOptions({ enabled_channels: ['WhatsApp', 'Telegram', 'Email'] }),
    [{ label: 'All channels', value: 'all' }, 'WhatsApp', 'Telegram', 'Email'])
})
