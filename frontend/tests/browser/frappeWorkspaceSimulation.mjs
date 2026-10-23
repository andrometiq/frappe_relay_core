export default async function testWorkspace(page,origin='http://127.0.0.1:18126'){
 const errors=[],calls=[],contact='RELAY-CON-0000000001';let sends=0
 const rows=[{name:'RELAY-MSG-0000000001',channel:'RELAY-CH-0000000001',content:'Hello, could you help me check the delivery date for our order?',direction:'Incoming',status:'Received',message_type:'text',provider_context:{provider:'WhatsApp',message_id:'fixture-incoming'},message_data:{kind:'text',text:'Hello, could you help me check the delivery date for our order?'}},{name:'RELAY-MSG-0000000002',channel:'RELAY-CH-0000000001',content:'Of course. I will check with the dispatch team and share an update.',direction:'Outgoing',status:'Sent',message_type:'text',provider_context:{provider:'WhatsApp',message_id:'fixture-outgoing'},message_data:{kind:'text',text:'Of course. I will check with the dispatch team and share an update.'}}]
 page.on('pageerror',e=>errors.push(e.message))
 await page.addInitScript(()=>{window.frappe={session:{user:'Administrator'},csrf_token:'synthetic-csrf-token'}})
 await page.route('**/api/method/**',async route=>{const request=route.request(),method=request.url().split('/').at(-1).split('?')[0];calls.push(method);let data
 if(method==='relay_core.inbox.directory')data={items:[{name:contact,display_name:'Asha Textiles'},{name:'RELAY-CON-0000000002',display_name:'Ravi Kumar'},{name:'RELAY-CON-0000000003',display_name:'Northstar Trading'}]}
 else if(method==='relay_core.inbox.read'||method==='relay_core.inbox.update')data={unread:0,can_assign:false,assignment:{}}
 else if(method==='relay_core.inbox.presence')data={users:[]}
 else if(method==='relay_core.api.messages')data={items:rows,has_more:false,first:rows[0].name,last:rows[1].name}
 else if(method==='relay_core.messaging.send'){if(request.headers()['x-frappe-csrf-token']!=='synthetic-csrf-token')throw Error('Missing CSRF');sends++;data={status:'Submitted'}}
 else throw Error('Unexpected API '+method)
 await route.fulfill({json:{message:data}})
 })
 await page.setViewportSize({width:1440,height:960});await page.goto(origin+'/relay#/messages')
 await page.getByText('Select a conversation',{exact:true}).waitFor()
 if(await page.getByRole('button',{name:'Settings',exact:true}).count()||await page.getByLabel('Hub MCP URL',{exact:true}).count())throw Error('Configuration leaked into app')
 await page.locator('[data-contact="'+contact+'"]').click();await page.getByText(rows[0].content,{exact:true}).waitFor()
 await page.locator('[data-message="'+rows[0].name+'"]').getByRole('button',{name:'Reply',exact:true}).click()
 await page.getByLabel('Message',{exact:true}).fill('I will send you an update shortly.')
 await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByText('Sent',{exact:true}).waitFor()
 if(sends!==1)throw Error('Reply did not submit once')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Horizontal overflow '+width)}
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Toggle navigation',exact:true}).click();await page.getByRole('button',{name:'Inbox',exact:true}).waitFor({state:'visible'});await page.getByRole('button',{name:'Close navigation',exact:true}).click()
 await page.setViewportSize({width:1440,height:960})
 if(errors.length)throw Error(errors.join('\n'))
 return {passed:true,replySubmitted:true,noConfigurationRequests:!calls.some(m=>m.includes('settings')),viewports:[320,390,768,1440]}
}
