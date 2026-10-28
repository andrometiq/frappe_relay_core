import assert from 'node:assert/strict'
import test from 'node:test'

import {
	buildTemplateComponents,
	templateParameterDescriptors,
	templatePreview,
	templateRendering,
} from '../src/services/templateParameters.js'

test('named body placeholders emit exact parameter_name fields', () => {
	const template = {
		parameter_format: 'NAMED',
		body_text: 'Order {{order_id}} for {{customer_name}} is ready',
		components: [
			{
				type: 'BODY',
				text: 'Order {{order_id}} for {{customer_name}} is ready',
				example: {
					body_text_named_params: [
						{ param_name: 'order_id', example: 'A-1' },
						{ param_name: 'customer_name', example: 'Sam' },
					],
				},
			},
		],
	}
	const descriptors = templateParameterDescriptors(template)
	assert.deepEqual(
		descriptors.map((row) => row.parameterName),
		['order_id', 'customer_name'],
	)
	const values = Object.fromEntries(descriptors.map((row) => [row.key, row.example]))
	assert.deepEqual(buildTemplateComponents(descriptors, values), [
		{
			type: 'body',
			parameters: [
				{ type: 'text', text: 'A-1', parameter_name: 'order_id' },
				{ type: 'text', text: 'Sam', parameter_name: 'customer_name' },
			],
		},
	])
	assert.equal(templatePreview(template, descriptors, values), 'Order A-1 for Sam is ready')
})

test('positional placeholders remain provider-compatible without parameter_name', () => {
	const template = {
		parameter_format: 'POSITIONAL',
		body_text: 'Order {{1}} is ready',
		components: [
			{
				type: 'BODY',
				text: 'Order {{1}} is ready',
				example: { body_text: [['A-1']] },
			},
		],
	}
	const descriptors = templateParameterDescriptors(template)
	assert.equal(descriptors[0].parameterName, undefined)
	assert.deepEqual(buildTemplateComponents(descriptors, { [descriptors[0].key]: 'A-2' }), [
		{ type: 'body', parameters: [{ type: 'text', text: 'A-2' }] },
	])
	assert.equal(templatePreview(template, descriptors, {}), 'Order A-1 is ready')
})

test('header media and dynamic buttons retain their provider component shapes', () => {
 const template={components:[{type:'HEADER',format:'IMAGE'},{type:'BODY',text:'Hello {{1}}'},{type:'BUTTONS',buttons:[{type:'URL',text:'Track',url:'https://example.invalid/{{1}}'}]}]}
 const fields=templateParameterDescriptors(template)
 const values=Object.fromEntries(fields.map(field=>[field.key,field.kind==='media'?{id:'123456',filename:'offer.png',size:9}:field.componentType==='BUTTON'?'order-7':'Sam']))
 assert.deepEqual(buildTemplateComponents(fields,values),[
  {type:'header',parameters:[{type:'image',image:{id:'123456'}}]},
  {type:'body',parameters:[{type:'text',text:'Sam'}]},
  {type:'button',sub_type:'url',index:'0',parameters:[{type:'text',text:'order-7'}]},
 ])
 assert.throws(()=>buildTemplateComponents(fields,{}),/required/)
})

test('rendering shows header, body, footer and buttons for Meta-synced templates without examples', () => {
 const template={parameter_format:'NAMED',components:[{type:'HEADER',format:'TEXT',text:'Hi {{name}}'},{type:'BODY',text:'Order {{order}}'},{type:'FOOTER',text:'Thanks'},{type:'BUTTONS',buttons:[{type:'QUICK_REPLY',text:'Yes'}]}]}
 const fields=templateParameterDescriptors(template)
 assert.deepEqual(templateRendering(template,fields,{}),{header:'Hi {{name}}',media:'',mediaUrl:'',body:'Order {{order}}',footer:'Thanks',buttons:[{key:undefined,text:'Yes',icon:'corner-up-left'}]})
 assert.equal(templatePreview(template,fields,{'BODY:1:order':'7'}),'Order 7')
 const media=templateRendering({components:[{type:'HEADER',format:'IMAGE'},{type:'BODY',text:'Plain'}]},[],{})
 assert.equal(media.media,'image'); assert.equal(media.body,'Plain')
 assert.equal(templateRendering({name:'welcome',components:'[]'},[],{}).body,'welcome')
})
