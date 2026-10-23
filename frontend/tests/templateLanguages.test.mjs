import test from 'node:test'
import assert from 'node:assert/strict'
import {templateLanguages,languageLabel} from '../src/services/templateLanguages.js'
import {templateForm,templateRequest} from '../src/services/templateAuthoring.js'
test('language names retain provider codes and preserve existing uncommon languages',()=>{
 const options=templateLanguages('si_LK')
 assert.equal(new Set(options.map(r=>r.value)).size,options.length)
 assert.ok(options.some(r=>r.value==='ta'&&r.label.includes('தமிழ்')&&r.label.includes('Tamil')))
 assert.ok(options.some(r=>r.value==='en_US'&&r.label.includes('English')&&r.label.includes('(en_US)')))
 assert.ok(options.some(r=>r.value==='si_LK'))
 assert.equal(languageLabel('invalid_language_tag'), 'invalid_language_tag')
 const form=templateForm({account_name:'test',template_name:'tamil_greeting',language_code:'ta',category:'UTILITY',components:[{type:'BODY',text:'வணக்கம்'}]})
 assert.equal(templateRequest(form,{submit:true}).template.language_code,'ta')
})
