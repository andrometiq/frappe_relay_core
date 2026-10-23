import test from 'node:test';import assert from 'node:assert/strict';import {parseCsv,recipientsFromCsv,csvTemplate} from '../src/services/campaignCsv.js';
test('CSV preserves quoted commas, newlines and quotes without permitting recipient overrides',()=>{const campaign={operation:'messages.send',arguments:{body:'Hello'}};assert.deepEqual(recipientsFromCsv(campaign,'Contact,Message\r\nA,"Hello,\n""Sam"""'),[{contact:'A',arguments:{body:'Hello,\n"Sam"'}}]);assert.throws(()=>recipientsFromCsv(campaign,'Contact,to\nA,123'),/Unknown/);assert.throws(()=>parseCsv('Contact,Message\nA,"unfinished'),/quote/);assert.throws(()=>recipientsFromCsv(campaign,'Contact\nA\nA'),/different/)});
test('template CSV replaces fixed named and button parameter slots while preserving template identity',()=>{const campaign={operation:'templates.send',arguments:{name:'order',language:'en_US',components:[{type:'body',parameters:[{type:'text',parameter_name:'customer',text:'Sample'}]},{type:'button',sub_type:'url',index:'0',parameters:[{type:'text',text:'default'}]}]}};const rows=recipientsFromCsv(campaign,'Contact,body.customer,button.0.1\nA,Sam,order-123');assert.equal(rows[0].arguments.components[0].parameters[0].text,'Sam');assert.equal(rows[0].arguments.components[1].sub_type,'url');assert.equal(rows[0].arguments.components[1].parameters[0].text,'order-123');assert.equal(parseCsv(csvTemplate(campaign,[{name:'A'}]))[0]['body.customer'],'Sample')});

test('Telegram and email CSV keep channel content and reject destination overrides',()=>{
 const telegram={operation:'telegram.send',arguments:{body:'Default'}};
 assert.deepEqual(recipientsFromCsv(telegram,'Contact,Message\nA,Telegram greeting'),[{contact:'A',arguments:{body:'Telegram greeting'}}]);
 const email={operation:'email.send',arguments:{subject:'Subject',body:'Body'}};
 assert.deepEqual(recipientsFromCsv(email,'Contact,Subject,Message\nA,Update,Email greeting'),[{contact:'A',arguments:{subject:'Update',body:'Email greeting'}}]);
 assert.equal(parseCsv(csvTemplate(email,[{name:'A'}]))[0].Subject,'Subject');
 assert.throws(()=>recipientsFromCsv(email,'Contact,to\nA,other@example.invalid'),/Unknown/);
});
