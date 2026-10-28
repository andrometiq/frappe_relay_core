import assert from 'node:assert/strict'
import test from 'node:test'

import { templateParameterDescriptors, templateRendering } from '../src/services/templateParameters.js'
import { templateForm, templatePreview } from '../src/services/templateAuthoring.js'
import { templateBody, templateHeader } from '../src/services/templateList.js'

const positional = {
	name: 'hr_late_punch_lunch', language: 'en', status: 'APPROVED', category: 'UTILITY', parameter_format: 'POSITIONAL',
	components: [
		{ type: 'BODY', text: 'Dear {{1}}\nPunch on {{2}} at {{3}} (lunch {{4}})', example: { body_text: [['Anas', '10-02-2002', '2:45 PM', '1:00 PM']] } },
		{ type: 'FOOTER', text: 'Essdee Knitting Mills Private Limited' },
	],
}
const named = {
	name: 'order_ready', language: 'en', status: 'APPROVED', category: 'UTILITY', parameter_format: 'NAMED',
	components: [
		{ type: 'HEADER', format: 'TEXT', text: 'Order {{order_id}}', example: { header_text_named_params: [{ param_name: 'order_id', example: 'A-1' }] } },
		{ type: 'BODY', text: 'Hi {{customer_name}}, order {{order_id}} is ready', example: { body_text_named_params: [{ param_name: 'customer_name', example: 'Sam' }, { param_name: 'order_id', example: 'A-1' }] } },
		{ type: 'BUTTONS', buttons: [{ type: 'QUICK_REPLY', text: 'Thanks' }, { type: 'URL', text: 'Track', url: 'https://x.test/{{1}}', example: ['abc'] }] },
	],
}
const image = {
	name: 'hindi_offer', language: 'hi', status: 'APPROVED', category: 'MARKETING', parameter_format: 'POSITIONAL',
	components: [
		{ type: 'HEADER', format: 'IMAGE', example: { header_handle: ['https://scontent.whatsapp.net/a.jpg'] } },
		{ type: 'BODY', text: 'नमस्ते {{1}}, आपका ऑर्डर तैयार है', example: { body_text: [['राज']] } },
	],
}
const render = (template, values = {}) => templateRendering(template, templateParameterDescriptors(template), values)

test('positional body shows its examples and footer', () => {
	const view = render(positional)
	assert.equal(view.body, 'Dear Anas\nPunch on 10-02-2002 at 2:45 PM (lunch 1:00 PM)')
	assert.equal(view.footer, 'Essdee Knitting Mills Private Limited')
})
test('typed values win over examples', () => {
	const descriptors = templateParameterDescriptors(positional)
	const view = templateRendering(positional, descriptors, { [descriptors[0].key]: 'Ravi' })
	assert.match(view.body, /^Dear Ravi/)
})
test('named header, body and button labels', () => {
	const view = render(named)
	assert.equal(view.header, 'Order A-1')
	assert.equal(view.body, 'Hi Sam, order A-1 is ready')
	assert.deepEqual(view.buttons.map((button) => button.text), ['Thanks', 'Track'])
})
test('image header keeps its example url; Hindi body is filled', () => {
	const view = render(image)
	assert.equal(view.media, 'image')
	assert.equal(view.mediaUrl, 'https://scontent.whatsapp.net/a.jpg')
	assert.equal(view.body, 'नमस्ते राज, आपका ऑर्डर तैयार है')
})
test('list helpers read the same rows', () => {
	assert.match(templateBody(positional), /^Dear \{\{1\}\}/)
	assert.equal(templateHeader(image), 'Image header')
	assert.equal(templateHeader(named), 'Order {{order_id}}')
})
test('detail preview of a Meta row shows examples and media', () => {
	for (const row of [positional, named, image]) {
		const view = templatePreview(templateForm(row))
		assert.equal(view.body, render(row).body)
	}
	assert.equal(templatePreview(templateForm(image)).mediaUrl, 'https://scontent.whatsapp.net/a.jpg')
})
test('components arriving as a JSON string still render', () => {
	const view = render({ ...positional, components: JSON.stringify(positional.components) })
	assert.match(view.body, /^Dear Anas/)
})
