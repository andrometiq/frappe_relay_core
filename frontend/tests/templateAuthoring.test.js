import assert from 'node:assert/strict'
import test from 'node:test'

import {
	addTemplateButton,
	buildTemplateComponents,
	parseTemplateComponents,
	templateForm,
	templateIssues,
	templatePreview,
	templateRequest,
	templateSampleFields,
} from '../src/services/templateAuthoring.js'

test('edits standard template fields without exposing canonical JSON', () => {
	const form = templateForm({
		account_name: 'ACCOUNT-1',
		template_name: 'order_update',
		language_code: 'en_US',
		category: 'UTILITY',
		components: [
			{ type: 'HEADER', format: 'TEXT', text: 'Order {{1}}' },
			{ type: 'BODY', text: 'Hello {{1}}, order {{2}} is ready' },
			{ type: 'FOOTER', text: 'Essdee' },
			{
				type: 'BUTTONS',
				buttons: [{ type: 'URL', text: 'Track', url: 'https://example.test/{{1}}' }],
			},
		],
	})
	form.header_text = 'Updated order {{1}}'
	form.body_text = 'Hi {{1}}, order {{2}} has shipped'
	form.sample_values.header['1'] = 'A-10'
	form.sample_values.body['1'] = 'Sakthi'
	form.sample_values.body['2'] = 'A-10'
	form.buttons[0].example_value = 'A-10'

	const request = templateRequest(form, { submit: true })
	assert.equal(request.template.components[0].text, 'Updated order {{1}}')
	assert.deepEqual(request.template.components[0].example.header_text, ['A-10'])
	assert.deepEqual(request.template.components[1].example.body_text, [['Sakthi', 'A-10']])
	assert.deepEqual(request.template.components[3].buttons[0].example, ['A-10'])
})

test('preserves complete advanced Meta components while standard fields change', () => {
	const advanced = {
		type: 'CAROUSEL',
		cards: [
			{
				components: [
					{ type: 'HEADER', format: 'IMAGE', example: { header_handle: ['asset'] } },
					{ type: 'BODY', text: 'Card body' },
				],
			},
		],
	}
	const form = templateForm({
		account_name: 'ACCOUNT-1',
		template_name: 'carousel_offer',
		components: [{ type: 'BODY', text: 'Choose an offer' }, advanced],
	})
	form.body_text = 'Choose your offer'
	const components = buildTemplateComponents(form)
	assert.equal(components[0].text, 'Choose your offer')
	assert.deepEqual(components[1], advanced)
	assert.equal(form.advanced_component_count, 1)
})

test('supports authentication and OTP fields through structured controls', () => {
	const form = templateForm(
		{
			account_name: 'ACCOUNT-1',
			template_name: 'login_code',
			language_code: 'en_US',
			category: 'AUTHENTICATION',
			parameter_format: 'POSITIONAL',
			components: [{ type: 'BODY', add_security_recommendation: true }],
		},
		[],
	)
	form.code_expiration_minutes = '10'
	addTemplateButton(form)
	Object.assign(form.buttons[0], {
		type: 'OTP',
		otp_type: 'ZERO_TAP',
		package_name: 'com.example.app',
		signature_hash: 'signature',
	})
	const request = templateRequest(form, { submit: true })
	assert.equal(request.template.components[0].add_security_recommendation, true)
	assert.equal(request.template.components[1].code_expiration_minutes, 10)
	assert.deepEqual(request.template.components[2].buttons[0], {
		type: 'OTP',
		text: '',
		otp_type: 'ZERO_TAP',
		package_name: 'com.example.app',
		signature_hash: 'signature',
	})
})

test('reads named samples and reports the exact structured sample fields', () => {
	const form = templateForm({
		account_name: 'ACCOUNT-1',
		template_name: 'named_update',
		parameter_format: 'NAMED',
		components: [
			{
				type: 'BODY',
				text: 'Hello {{customer_name}}',
				example: {
					body_text_named_params: [{ param_name: 'customer_name', example: 'Sakthi' }],
				},
			},
		],
	})
	assert.equal(form.sample_values.body.customer_name, 'Sakthi')
	assert.deepEqual(templateSampleFields(form), [
		{
			scope: 'body',
			name: 'customer_name',
			key: 'body-customer_name',
			label: 'Body sample for {{customer_name}}',
		},
	])
})

test('fails closed on malformed storage and incomplete submission fields', () => {
	assert.throws(() => templateForm({ components: '[{"type":"BODY"}' }), /invalid data/)
	assert.throws(() => parseTemplateComponents([{ type: 'HEADER', format: 'TEXT' }]), /BODY/)
	const form = templateForm({
		account_name: 'ACCOUNT-1',
		template_name: 'order_update',
		components: [{ type: 'BODY', text: 'Order {{1}} is ready' }],
	})
	assert.throws(() => templateRequest(form, { submit: true }), /Body sample/)
	form.sample_values.body['1'] = 'A-2'
	form.template_name = 'Bad Name'
	assert.throws(() => templateRequest(form, { submit: true }), /lowercase/)
})

function namedForm(body) {
	const form = templateForm({ account_name: 'current-account', template_name: 'order_update', language_code: 'en_US',
		parameter_format: 'NAMED', components: [{ type: 'BODY', text: body }] })
	form.sample_values.body = { customer_name: 'Asha', order_id: 'SO-12' }
	return form
}

test('flags the Meta rules that cause template rejections', () => {
	assert.match(templateIssues(namedForm('{{customer_name}}, your order is ready')).join(' '), /very start or end/)
	assert.match(templateIssues(namedForm('Your order is ready {{order_id}}')).join(' '), /very start or end/)
	assert.match(templateIssues(namedForm('Hello {{Customer Name}}, ready')).join(' '), /lowercase letters/)
	assert.match(templateIssues(namedForm('Hi {{1}}, ready')).join(' '), /named like/)
	const missing = namedForm('Hi {{customer_name}}, order {{order_id}} is ready')
	missing.sample_values.body = {}
	assert.match(templateIssues(missing).join(' '), /Body sample for \{\{customer_name\}\}/)
	const positional = templateForm({ account_name: 'a', template_name: 'gap', components: [{ type: 'BODY', text: 'Hi {{1}} and {{3}} ok' }] })
	assert.match(templateIssues(positional).join(' '), /without gaps/)
	const long = namedForm('Hi {{customer_name}} ' + 'x'.repeat(1030) + ' ok')
	long.footer_text = 'Thanks {{customer_name}}'
	long.buttons = [{ type: 'URL', text: 'Track my order right now please', url: 'ftp://bad' }, { type: 'PHONE_NUMBER', text: 'Call', phone_number: '12' }]
	const issues = templateIssues(long).join(' ')
	for (const rule of [/at most 1024/, /Footer cannot contain variables/, /at most 25 characters/, /https:\/\//, /country code/]) assert.match(issues, rule)
	assert.throws(() => templateRequest(namedForm('{{customer_name}} hi'), { submit: true }), /very start or end/)
	assert.deepEqual(templateIssues(namedForm('Hi {{customer_name}}, order {{order_id}} is ready.')), [])
})

test('sends Meta parameter format in lowercase', () => {
	const request = templateRequest(namedForm('Hi {{customer_name}}, order {{order_id}} is ready.'), { submit: true })
	assert.equal(request.template.parameter_format, 'named')
	assert.deepEqual(request.template.components[0].example.body_text_named_params,
		[{ param_name: 'customer_name', example: 'Asha' }, { param_name: 'order_id', example: 'SO-12' }])
})

test('preview fills examples, media header and button icons', () => {
	const form = namedForm('Hi {{customer_name}}, order {{order_id}} is ready.')
	form.header_type = 'IMAGE'
	form.footer_text = 'Essdee'
	form.buttons = [{ type: 'URL', text: 'Track' }, { type: 'QUICK_REPLY', text: 'Thanks' }]
	assert.deepEqual(templatePreview(form), { header: '', media: 'image', body: 'Hi Asha, order SO-12 is ready.', footer: 'Essdee',
		buttons: [{ key: undefined, text: 'Track', icon: 'external-link' }, { key: undefined, text: 'Thanks', icon: 'corner-up-left' }] })
})
