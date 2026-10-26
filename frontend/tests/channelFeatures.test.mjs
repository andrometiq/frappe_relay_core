import test from 'node:test'
import assert from 'node:assert/strict'
import { channelCan, channelFeature, composerKinds } from '../src/services/enabledChannels.js'
import { attachmentAccept, attachmentFormatError } from '../src/components/messages/attachmentFormats.js'
import { whatsappCapabilities as capabilities } from './channelCapabilities.js'

test('channelCan reads enabled channel features and refuses switched-off channels', () => {
  assert.equal(channelCan(capabilities, 'WhatsApp', 'templates'), true)
  assert.equal(channelCan(capabilities, 'WhatsApp', 'media.voice'), true)
  assert.equal(channelCan(capabilities, 'WhatsApp', 'topics'), false)
  assert.equal(channelCan(capabilities, 'Telegram', 'text'), false)
  assert.equal(channelCan(capabilities, undefined, 'text'), false)
  assert.equal(channelCan({ enabled_channels: ['WhatsApp'] }, 'WhatsApp', 'text'), false)
  assert.equal(channelFeature(capabilities, 'WhatsApp', 'reply_window_hours'), 24)
})

test('an account without the Hub template flag hides templates', () => {
  const flagged = { channels: { WhatsApp: { ...capabilities.channels.WhatsApp, templates: false } } }
  assert.equal(channelCan(flagged, 'WhatsApp', 'templates'), false)
})

test('composer offers every WhatsApp type in private chats and media only in groups', () => {
  assert.deepEqual(composerKinds(capabilities, { provider: 'WhatsApp' }),
    ['text', 'sticker', 'photo', 'video', 'audio', 'voice', 'document', 'location', 'contact'])
  assert.deepEqual(composerKinds(capabilities, { provider: 'WhatsApp', group_id: 'group' }),
    ['text', 'sticker', 'photo', 'video', 'audio', 'voice', 'document'])
  assert.deepEqual(composerKinds(capabilities, { provider: 'Telegram' }), ['text'])
  const textOnly = { channels: { Other: { text: true, media: {}, location: false, contacts: false } } }
  assert.deepEqual(composerKinds(textOnly, { provider: 'Other' }), ['text'])
})

test('attachment hints and checks follow the channel media types', () => {
  assert.equal(attachmentAccept(capabilities, 'WhatsApp', 'photo'), '.jpg,.jpeg,.png')
  assert.equal(attachmentAccept(capabilities, 'WhatsApp', 'voice'), '.mp3,.m4a,.ogg,.oga,.opus,.aac')
  assert.equal(attachmentFormatError(capabilities, 'WhatsApp', 'photo', 'Photo.PNG'), '')
  assert.equal(attachmentFormatError(capabilities, 'WhatsApp', 'photo', 'photo.webp'), 'Choose .jpg, .jpeg, .png for this attachment.')
  assert.equal(attachmentFormatError(capabilities, 'Telegram', 'photo', 'photo.jpg'), 'This attachment type is unavailable for this channel.')
  const anyFile = { channels: { Email: { media: { document: ['*/*'] } } } }
  assert.equal(attachmentAccept(anyFile, 'Email', 'document'), '')
  assert.equal(attachmentFormatError(anyFile, 'Email', 'document', 'report.zip'), '')
})
