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

test('sent templates show rendered parts with a template or campaign caption', async () => {
  const { templateParts } = await import('../src/components/messageContent.js')
  const data = { kind: 'text', text: 'Hi Ravi', template: { name: 'relay_test_marketing', header: 'New stock', footer: 'Essdee', buttons: ['Send catalogue'] } }
  assert.deepEqual(templateParts(data), { header: 'New stock', footer: 'Essdee', buttons: ['Send catalogue'], caption: 'Template · relay_test_marketing' })
  assert.equal(templateParts({ ...data, campaign: 'Winter launch' }).caption, 'Campaign: Winter launch')
  assert.deepEqual(templateParts({ kind: 'text', text: 'Hi', template: { name: 'plain', buttons: 'bad' } }).buttons, [])
  assert.equal(templateParts({ kind: 'text', text: 'Hello' }), null)
})

test('template header media shows from the kept copy or an https link only', async () => {
  const { templateHeaderView } = await import('../src/components/messageContent.js')
  const message = data => ({ name: 'RELAY-MSG-0000000001', message_data: JSON.stringify({ kind: 'text', text: 'Hi', ...data }) })
  const header = (parameter, extra = {}) => message({ ...extra, template: { name: 'offer', components: [{ type: 'header', parameters: [parameter] }] } })
  assert.deepEqual(templateHeaderView(header({ type: 'image', image: { link: 'https://cdn.example.com/offer.png' } })),
    { type: 'image', fileName: '', kept: false, link: 'https://cdn.example.com/offer.png' })
  assert.deepEqual(templateHeaderView(header({ type: 'video', video: { id: '456' } })), { type: 'video', fileName: '', kept: true, link: '' })
  assert.deepEqual(templateHeaderView(header({ type: 'document', document: { link: 'https://cdn.example.com/March%20bill.pdf', filename: 'March bill.pdf' } }, { attachment: 'FILE-1' })),
    { type: 'document', fileName: 'March bill.pdf', kept: true, link: 'https://cdn.example.com/March%20bill.pdf' })
  for (const link of ['http://cdn.example.com/a.png', 'javascript:alert(1)', 'data:image/png;base64,AA'])
    assert.equal(templateHeaderView(header({ type: 'image', image: { link } })).link, '')
  assert.deepEqual(templateHeaderView(message({ template: { name: 'order', document: { file_name: 'Order.pdf' } } })), { type: 'document', fileName: 'Order.pdf', kept: false, link: '' })
  assert.equal(templateHeaderView({ ...header({ type: 'image', image: { id: '1' } }), _pending: true }).kept, false)
  assert.equal(templateHeaderView(message({ template: { name: 'plain' } })), null)
})

test('every message with a file offers a download, template headers included', async () => {
  const { attachmentDownloadURL } = await import('../src/components/messageContent.js')
  const core = '/api/method/relay_core.attachments.read?message=RELAY-MSG-0000000001&download=1'
  const message = data => ({ name: 'RELAY-MSG-0000000001', message_data: JSON.stringify(data) })
  const header = parameter => ({ kind: 'text', text: 'Hi', template: { name: 'offer', components: [{ type: 'header', parameters: [parameter] }, { type: 'body', parameters: [{ type: 'text', text: 'Ravi' }] }] } })
  assert.equal(attachmentDownloadURL(message({ kind: 'document', media: { id: '1' } })), core)
  assert.equal(attachmentDownloadURL(message({ ...header({ type: 'document', document: { id: '9', filename: 'Order_ORD-1.pdf' } }), attachment: 'FILE-1' })), core)
  assert.equal(attachmentDownloadURL(message(header({ type: 'image', image: { id: '456' } }))), core)
  assert.equal(attachmentDownloadURL(message(header({ type: 'document', document: { link: 'https://cdn.example.com/bill.pdf', filename: 'bill.pdf' } }))), 'https://cdn.example.com/bill.pdf')
  assert.equal(attachmentDownloadURL(message(header({ type: 'image', image: { link: 'javascript:alert(1)' } }))), null)
  assert.equal(attachmentDownloadURL(message({ kind: 'text', text: 'Hi', template: { name: 'plain' } })), null)
  assert.equal(attachmentDownloadURL({ ...message({ kind: 'document' }), _pending: true }), null)
})
