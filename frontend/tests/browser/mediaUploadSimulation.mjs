export default async function testMedia(page,origin='http://127.0.0.1:18126'){
 const errors=[],uploads=[],sends=[]
 const contacts=[1,2].map(i=>({name:'RELAY-CON-000000000'+i,display_name:i===1?'Telegram contact':'WhatsApp contact'}))
 const rows=contacts.map((c,i)=>({name:'RELAY-MSG-000000000'+(i+1),relay_contact:c.name,channel:'RELAY-CH-000000000'+(i+1),direction:'Incoming',status:'Sent',content:'Media fixture',message_type:'text',message_data:{kind:'text',text:'Media fixture'},provider_context:{provider:i===0?'Telegram':'WhatsApp'}}))
 page.on('pageerror',error=>errors.push(error.message))
 await page.route('**/api/method/**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0];let result
  if(method==='relay_core.inbox.directory')result={items:contacts}
  else if(method==='relay_core.inbox.read'||method==='relay_core.inbox.update')result={unread:1}
  else if(method==='relay_core.inbox.presence')result={users:[]}
  else if(method==='relay_core.api.messages'){const index=request.url().includes(contacts[0].name)?0:1;result={items:[rows[index]],first:rows[index].name,last:rows[index].name,has_more:false}}
  else if(method==='relay_core.attachments.upload'){uploads.push(request.postDataJSON());result={name:'private-'+uploads.length,filename:'evidence.txt',size:8}}
  else if(method==='relay_core.messaging.send'){sends.push(request.postDataJSON());result={status:'Submitted'}}
  else throw Error('Unexpected '+method)
  return route.fulfill({json:{message:result}})
 })
 await page.setViewportSize({width:390,height:844});await page.goto(origin+'/tests/browser/messages.html')
 for(let index=0;index<2;index++){
  if(index)await page.getByRole('button',{name:'Back to contacts',exact:true}).click()
  await page.locator('[data-contact="'+contacts[index].name+'"]').click()
  await page.locator('.composer-options summary').click()
  await page.getByLabel('Type',{exact:true}).selectOption('document')
  await page.locator('input[type=file]').evaluate(node=>{const transfer=new DataTransfer();transfer.items.add(new File(['Evidence'],'evidence.txt',{type:'text/plain'}));node.files=transfer.files;node.dispatchEvent(new Event('change',{bubbles:true}))})
  await page.getByText('evidence.txt',{exact:false}).waitFor()
  await page.getByLabel('Caption',{exact:true}).fill('Evidence caption')
  await page.getByRole('button',{name:'Send',exact:true}).click();await page.getByText('Sent',{exact:true}).waitFor()
 }
 if(uploads.length!==2||sends.length!==2||sends.some((row,index)=>row.message!==rows[index].name||row.data.attachment!=='private-'+(index+1)||row.kind!=='document'))throw Error('Private media source binding failed')
 await page.getByLabel('Type',{exact:true}).selectOption('audio')
 if(await page.getByLabel('Caption',{exact:true}).count())throw Error('WhatsApp audio exposes unsupported caption')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width)}
 if(errors.length)throw Error(errors.join('\n'))
 return {passed:true,telegramUpload:true,whatsappUpload:true,sourceBound:true,viewports:[320,390,768,1440]}
}
