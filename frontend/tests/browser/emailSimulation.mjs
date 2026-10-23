export default async function testEmail(page,origin='http://127.0.0.1:18126'){
 const contact='RELAY-CON-0000000001',message='RELAY-MSG-0000000001',sends=[],requests=[],errors=[]
 let reject=false
 page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith(origin))requests.push(r.url())})
 const row={name:message,channel:'RELAY-CH-0000000001',sender_endpoint:'sender@example.invalid',direction:'Incoming',status:'Received',content:'An email question',message_type:'text',provider_context:{provider:'Email',subject:'Invoice question',message_id:'<source@example.invalid>'},message_data:{kind:'text',text:'An email question',email:{subject:'Invoice question',html:'<p>HTML email preview</p><script>fetch("https://never.example.invalid/")</script><img src="https://never.example.invalid/tracker">',attachments:[]}}}
 await page.route('**/api/method/**',async route=>{const request=route.request(),method=request.url().split('/').at(-1).split('?')[0];let result
  if(method==='relay_core.inbox.directory')result={items:[{name:contact,display_name:'Email customer'}]}
  else if(method==='relay_core.inbox.read'||method==='relay_core.inbox.update')result={unread:1,assignment:{}}
  else if(method==='relay_core.inbox.presence')result={users:[]}
  else if(method==='relay_core.api.messages')result={items:[row],first:message,last:message,has_more:false}
  else if(method==='relay_core.email_preferences.read')result={signature:'Regards,\nRelay agent'}
  else if(method==='relay_core.email_preferences.save')result={saved:true}
  else if(method==='relay_core.email.send'){sends.push({body:request.postDataJSON(),headers:request.headers()});if(reject)return route.fulfill({status:403,json:{exc:'PermissionError'}});result={sent:true}}
  else throw Error('Unexpected method '+method)
  return route.fulfill({json:{message:result}})
 })
 await page.setViewportSize({width:390,height:844});await page.goto(origin+'/tests/browser/messages.html');await page.locator('[data-contact="'+contact+'"]').click()
 await page.getByLabel('To',{exact:true}).waitFor();await page.getByRole('button',{name:'View HTML email',exact:true}).click()
 const frame=page.locator('iframe[title="Email HTML preview"]');if(await frame.getAttribute('sandbox')!=='' )throw Error('Email preview is not sandboxed')
 await page.getByRole('button',{name:'Email options',exact:true}).click()
 await page.getByRole('button',{name:'Insert signature',exact:true}).click()
 if(!(await page.getByLabel('Email message',{exact:true}).inputValue()).includes('Regards,'))throw Error('Signature not inserted')
 await page.getByLabel('CC',{exact:true}).fill('cc@example.invalid');await page.getByLabel('BCC',{exact:true}).fill('bcc@example.invalid')
 await page.getByLabel('Email message',{exact:true}).fill('Keep this draft')
 reject=true
 await Promise.all([page.waitForResponse(r=>r.url().includes('relay_core.email.send')),page.getByRole('button',{name:'Send email',exact:true}).click()])
 await page.getByText('You do not have permission for this action.',{exact:true}).waitFor()
 if(await page.getByLabel('Email message',{exact:true}).inputValue()!=='Keep this draft')throw Error('Failed send erased draft')
 reject=false
 await Promise.all([page.waitForResponse(r=>r.url().includes('relay_core.email.send')),page.getByRole('button',{name:'Send email',exact:true}).click()])
 await page.getByText('Email submitted',{exact:true}).waitFor()
 if(sends[0].body.request_key!==sends[1].body.request_key||sends[1].headers['x-frappe-csrf-token']!=='synthetic-csrf-token'||sends[1].body.message!==message||sends[1].body.bcc[0]!=='bcc@example.invalid')throw Error('Email retry/routing/CSRF contract changed')
 await page.getByRole('button',{name:'Forward instead',exact:true}).click()
 if(await page.getByLabel('To',{exact:true}).inputValue()!==''||!(await page.getByLabel('Email message',{exact:true}).inputValue()).includes('An email question'))throw Error('Forward draft is incomplete')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow at '+width)}
 if(errors.length||requests.length)throw Error(JSON.stringify({errors,requests}))
 return {passed:true,sandboxedHTML:true,signature:true,forward:true,draftRetained:true,stableRetry:true,viewports:[320,390,768,1440]}
}
