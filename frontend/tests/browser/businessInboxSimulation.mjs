export default async function testBusiness(page,origin='http://127.0.0.1:18126'){
 const errors=[],sends=[],type='Customer',business='CUSTOMER-001'
 page.on('pageerror',e=>errors.push(e.message))
 const rows=[1,2].map(i=>({name:'RELAY-MSG-000000000'+i,relay_contact:'RELAY-CON-000000000'+i,contact_label:'Contact '+i,channel:'RELAY-CH-0000000001',direction:'Incoming',status:'Sent',content:'Business message '+i,message_type:'text',provider_context:{provider:'Telegram'},message_data:{kind:'text',text:'Business message '+i}}))
 await page.route('**/api/method/**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0];let result
  if(method==='relay_core.inbox.directory')result={items:[]}
  else if(method==='relay_core.api.business_types')result=[type]
  else if(method==='relay_core.business_inbox.records')result={items:[{name:business}]}
  else if(method==='relay_core.business_inbox.messages')result={items:rows,first:rows[0].name,last:rows[1].name,has_more:false}
  else if(method==='relay_core.messaging.send'){sends.push(request.postDataJSON());result={status:'Submitted'}}
  else throw Error('Unexpected '+method)
  return route.fulfill({json:{message:result}})
 })
 await page.setViewportSize({width:390,height:844});await page.goto(origin+'/tests/browser/messages.html')
 await page.getByRole('button',{name:'By business',exact:true}).click();await page.getByLabel('Business type',{exact:true}).selectOption(type)
 await page.getByRole('button',{name:business,exact:true}).click()
 for(const row of rows)await page.locator('[data-message="'+row.name+'"]').getByText(row.contact_label+' ·',{exact:true}).waitFor()
 await page.locator('[data-message="'+rows[0].name+'"]').getByRole('button',{name:'Reply',exact:true}).click()
 const textareas=page.locator('textarea');await textareas.last().fill('Reply to Contact 1')
 await page.getByRole('button',{name:'Send',exact:true}).click()
 await page.getByText('Sent',{exact:true}).waitFor()
 if(sends.length!==1||sends[0].message!==rows[0].name)throw Error('Business reply selected wrong Contact')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width)}
 if(errors.length)throw Error(errors.join('\n'))
 return {passed:true,multipleContacts:true,replyRouting:true,viewports:[320,390,768,1440]}
}
