import assert from 'node:assert/strict'
import test from 'node:test'
import { readFile } from 'node:fs/promises'

import { headerFileError, headerLinkError, headerMediaParameter, linkFileName } from '../src/services/templateMedia.js'
import { buildTemplateComponents, templateParameterDescriptors, templateRendering } from '../src/services/templateParameters.js'
import { whatsappCapabilities } from './channelCapabilities.js'

const capabilities = whatsappCapabilities
const file = (name, size = 1024) => ({ name, size })

test('header link must be public https', () => {
	assert.equal(headerLinkError('https://cdn.example.com/offer.png'), '')
	for (const link of ['http://cdn.example.com/a.png', 'cdn.example.com/a.png', 'https://localhost/a.png', 'https://127.0.0.1/a.png',
		'https://127.1/a.png', 'https://10.2.3.4/a.png', 'https://192.168.0.9/a.png', 'https://172.20.1.1/a.png',
		'https://169.254.169.254/x', 'https://[::1]/a.png', 'https://intranet/a.png', 'https://nas.local/a.png',
		'https://user:pw@cdn.example.com/a.png', 'javascript:alert(1)'])
		assert.notEqual(headerLinkError(link), '', link)
})

test('header file must match the header format and the 4 MB limit', () => {
	assert.equal(headerFileError(capabilities, 'image', file('offer.png')), '')
	assert.equal(headerFileError(capabilities, 'document', file('bill.pdf')), '')
	assert.equal(headerFileError(capabilities, 'video', file('clip.mp4')), '')
	assert.match(headerFileError(capabilities, 'image', file('offer.gif')), /Choose/)
	assert.match(headerFileError(capabilities, 'video', file('offer.png')), /Choose/)
	assert.match(headerFileError(capabilities, 'image', file('offer.png', 5 * 1024 * 1024)), /4 MB/)
	assert.match(headerFileError(capabilities, 'image', file('offer.png', 0)), /4 MB/)
})

test('upload and link values become provider header parameters', () => {
	assert.deepEqual(headerMediaParameter('image', { id: '9001', filename: 'a.png', size: 3 }), { type: 'image', image: { id: '9001' } })
	assert.deepEqual(headerMediaParameter('image', { link: 'https://cdn.example.com/a.png' }), { type: 'image', image: { link: 'https://cdn.example.com/a.png' } })
	assert.deepEqual(headerMediaParameter('document', { link: 'https://cdn.example.com/b/March%20bill.pdf', filename: linkFileName('https://cdn.example.com/b/March%20bill.pdf') }),
		{ type: 'document', document: { link: 'https://cdn.example.com/b/March%20bill.pdf', filename: 'March bill.pdf' } })
	assert.equal(headerMediaParameter('image', null), null)
	assert.equal(headerMediaParameter('image', 'https://cdn.example.com/a.png'), null)
})

test('template send needs the header file and shows a chosen link in the preview', () => {
	const template = { components: [{ type: 'HEADER', format: 'DOCUMENT' }, { type: 'BODY', text: 'Bill' }] }
	const fields = templateParameterDescriptors(template)
	assert.throws(() => buildTemplateComponents(fields, {}), /Document file is required/)
	assert.deepEqual(buildTemplateComponents(fields, { [fields[0].key]: { id: '77', filename: 'bill.pdf', size: 4 } }),
		[{ type: 'header', parameters: [{ type: 'document', document: { id: '77', filename: 'bill.pdf' } }] }])
	const image = { components: [{ type: 'HEADER', format: 'IMAGE', example: { header_handle: ['https://scontent.example.com/s.jpg'] } }, { type: 'BODY', text: 'Hi' }] }
	const imageFields = templateParameterDescriptors(image)
	assert.equal(templateRendering(image, imageFields, {}).mediaUrl, 'https://scontent.example.com/s.jpg')
	assert.equal(templateRendering(image, imageFields, { [imageFields[0].key]: { link: 'https://cdn.example.com/a.png' } }).mediaUrl, 'https://cdn.example.com/a.png')
})

test('new message and in-chat template send use the media field for header files', async () => {
	const source = await readFile(new URL('../src/components/messages/StartConversation.vue', import.meta.url), 'utf8')
	assert.match(source, /<TemplateMediaField v-if="field\.kind === 'media'"[^>]*:channel="mediaChannel"/)
	const field = await readFile(new URL('../src/components/messages/TemplateMediaField.vue', import.meta.url), 'utf8')
	for (const text of ['Upload file', 'Use a link', 'template_media.upload', 'Remove '])
		assert.ok(field.includes(text), text)
})
