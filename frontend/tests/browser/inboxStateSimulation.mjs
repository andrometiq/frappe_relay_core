export default async function testInboxState(page, origin='http://127.0.0.1:18126') {
 const contact='RELAY-CON-0000000001',other='RELAY-CON-0000000002',updates=[],searches=[],errors=[]
 const name=id=>'RELAY-MSG-'+String(id).padStart(10,'0')
 const row=id=>({name:name(id),channel:'RELAY-CH-0000000001',direction:'Incoming',status:'Received',content:'Read position message '+id,provider_context:{provider:'Telegram',chat_id:123,message_id:id},message_data:{kind:'text',text:'Read position message '+id}})
 const items=Array.from({length:51},(_,i)=>row(i+25))
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/api/method/**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0],body=request.method()==='POST'?request.postDataJSON():Object.fromEntries(new URL(request.url()).searchParams)
  let message
  if(method==='relay_core.inbox.directory'){searches.push(body);message={items:[{name:contact,display_name:'Read restoration customer'},{name:other,display_name:'Second customer'}]}}
  else if(method==='relay_core.inbox.read')message={last_read:body.contact===contact?name(50):null,unread:50,assignment:{}}
  else if(method==='relay_core.api.message_context')message={contact,items,first:name(25),last:name(75),has_more:true,has_newer:true,anchor:name(50)}
  else if(method==='relay_core.api.messages')message={items:[row(100)],first:name(100),last:name(100),has_more:false}
  else if(method==='relay_core.inbox.update'){updates.push(body);message={last_read:body.last_read,unread:0,assignment:{}}}
  else if(method==='relay_core.inbox.presence')message={users:[{name:'fixture@example.invalid',full_name:'Another agent'}]}
  else throw Error('Unexpected method '+method)
  return route.fulfill({json:{message}})
 })
 await page.setViewportSize({width:1440,height:1000})
 await page.goto(origin+'/tests/browser/messages.html')
 await page.locator('[data-contact="'+contact+'"]').click()
 const restored=page.locator('[data-message="'+name(50)+'"]')
 await restored.waitFor()
 await page.waitForFunction(()=>{const node=document.querySelector('.anchored-message'),viewport=document.querySelector('.message-thread');if(!node||!viewport)return false;const a=node.getBoundingClientRect(),b=viewport.getBoundingClientRect();return a.top>=b.top&&a.top<b.bottom})
 await page.getByText('Viewing: Another agent',{exact:true}).waitFor()
 if(!updates.some(row=>row.last_read>=name(50)&&row.last_read<name(75)))throw Error('Visible read position was not saved; offscreen messages may be marked read')
 await page.getByRole('button',{name:'Load newer messages',exact:true}).click()
 await page.getByText('Read position message 100',{exact:true}).waitFor()
 await page.locator('[data-contact="'+other+'"]').click()
 await page.waitForFunction(()=>!document.querySelector('.anchored-message'))
 await page.getByRole('button',{name:'Filters',exact:true}).click()
 await page.getByLabel('Folder',{exact:true}).fill('Follow up')
 await Promise.all([page.waitForResponse(response=>response.url().includes('relay_core.inbox.directory')),page.getByRole('button',{name:'Apply folder',exact:true}).click()])
 await page.waitForFunction(()=>!document.querySelector('button[type="submit"]').disabled)
 if(!searches.some(row=>row.folder==='Follow up'))throw Error('Folder not sent to server')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow at '+width)}
 if(errors.length)throw Error(errors.join('; '))
 return {passed:true,restored:true,visibleRead:true,newerPaging:true,folder:true,presence:true,viewports:[320,390,768,1440]}
}
