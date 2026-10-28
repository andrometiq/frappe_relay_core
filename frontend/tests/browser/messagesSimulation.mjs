// Browser UI contract simulation. Real authorization/database behavior is tested
// independently by integration_message_types_site.py; these routes are synthetic.
export default async function testMessages(page, origin = 'http://127.0.0.1:18124') {
  const errors = [], sends = [], reads = [], unexpected = []
  let failure = null
  const contact = 'RELAY-CON-0000000001'
  const msg = (id, kind, detail, provider = 'Telegram') => ({
    name: `RELAY-MSG-${String(id).padStart(10,'0')}`, channel:'RELAY-CH-0000000001',
    direction:'Incoming',status:'Received',message_type:kind,content:kind,
    provider_context:{provider,message_id:id,chat_id:-10001,message_thread_id:7,reply_to_message_id:10,...(provider==='WhatsApp'?{group_id:'group-one'}:{})},
    message_data:{kind,...detail},reactions:{'111':[{type:'emoji',emoji:'👍'}]},
  })
  const rows = [msg(1,'text',{text:'A quoted question'}),msg(2,'sticker',{media:{file_id:'known-sticker'}}),
    msg(3,'location',{location:{latitude:0,longitude:0,name:'Zero point'}}),
    msg(4,'contact',{contacts:[{name:{formatted_name:'<img src=x onerror=alert(1)>'},phones:[{phone:'+919000000055'}],emails:[{email:'safe@example.invalid'}]}]}),
    msg(5,'text',{text:'WhatsApp group question'},'WhatsApp')]
  const onError = error => errors.push(error.message)
  const onRequest = request => { if(!request.url().startsWith(origin)) unexpected.push(request.url()) }
  page.on('pageerror', onError); page.on('request', onRequest)
  await page.route('**/api/method/**', async route => {
    const request = route.request(), url = new URL(request.url()), method = url.pathname.split('/').at(-1)
    if(method === 'relay_core.inbox.presence') return route.fulfill({json:{message:{users:[]}}})
    if(method === 'relay_core.inbox.read' || method === 'relay_core.inbox.update') return route.fulfill({json:{message:{unread:5,assignment:{},can_assign:false}}})
    if(method === 'relay_core.inbox.directory') {
      reads.push(Object.fromEntries(url.searchParams));
      return route.fulfill({json:{message:{items:[{name:contact,display_name:'Synthetic customer'}]}}})
    }
    if(method === 'relay_core.api.messages') {
      reads.push(Object.fromEntries(url.searchParams))
      return route.fulfill({json:{message:{items:rows,first:rows[0].name,last:rows.at(-1).name,has_more:false}}})
    }
    if(method === 'relay_core.messaging.send') {
      const body = request.postDataJSON(); sends.push({body,headers:request.headers()})
      if(failure === 'permission') return route.fulfill({status:403,json:{exc:'PermissionError'}})
      return route.fulfill({json:{message:{status:failure || 'Submitted',message:null,action:'RELAY-MA-1'}}})
    }
    if(method === 'relay_core.messaging.sticker') return route.fulfill({status:404,body:''})
    throw new Error('Unexpected API method ' + method)
  })
  const waitSend = async count => { await page.waitForFunction(() => [...document.querySelectorAll('button')].some(button => button.textContent.trim() === 'Refresh' && !button.disabled)); if(sends.length!==count) throw new Error(`Expected ${count} sends; got ${sends.length}`) }
  try {
    await page.setViewportSize({width:390,height:844}); await page.goto(origin+'/tests/browser/messages.html')
    await page.locator('[data-contact="'+contact+'"]').click()
    await page.getByText('A quoted question',{exact:true}).waitFor()
    if(await page.locator('[data-message-kind="contact"] img').count()) throw new Error('Contact HTML executed')
    await page.getByText('<img src=x onerror=alert(1)>',{exact:true}).waitFor()
    const quote = page.locator('[data-message="'+rows[0].name+'"]')
    await quote.getByRole('button',{name:'Reply',exact:true}).click()
    await page.getByLabel('Message',{exact:true}).fill('A contextual answer')
    await page.getByRole('button',{name:'Send',exact:true}).click(); await waitSend(1)
    if(JSON.stringify(Object.keys(sends[0].body).sort())!==JSON.stringify(['data','kind','message','request_key'])) throw new Error('Browser supplied provider routing')
    if(sends[0].body.message!==rows[0].name || sends[0].body.data.text!=='A contextual answer' || sends[0].headers['x-frappe-csrf-token']!=='synthetic-csrf-token') throw new Error('Reply contract mismatch')
    await quote.getByRole('button',{name:'Add reaction',exact:true}).click();await Promise.all([page.waitForResponse(r=>r.url().includes('relay_core.messaging.send')),page.getByRole('button',{name:'Remove reaction',exact:true}).click()]); await waitSend(2)
    if(sends[1].body.kind!=='reaction' || sends[1].body.data.emoji!=='') throw new Error('Reaction was not cleared')
    await page.locator('.composer-options summary').click()
    await page.getByLabel('Type',{exact:true}).selectOption('location')
    await page.getByLabel('Latitude',{exact:true}).fill('0'); await page.getByLabel('Longitude',{exact:true}).fill('0')
    await page.getByRole('button',{name:'Send',exact:true}).click(); await waitSend(3)
    if(sends[2].body.data.latitude!==0 || sends[2].body.data.longitude!==0) throw new Error('Zero coordinates were changed')
    await page.getByLabel('Type',{exact:true}).selectOption('contact')
    await page.getByLabel('Contact name',{exact:true}).fill('A new person'); await page.getByLabel('Phone number',{exact:true}).fill('+919000000055')
    await page.getByRole('button',{name:'Send',exact:true}).click(); await waitSend(4)
    if(sends[3].body.data.contacts[0].name.formatted_name!=='A new person') throw new Error('Contact card lost name')
    await page.locator('[data-message="'+rows[1].name+'"]').getByRole('button',{name:'Message actions',exact:true}).click();await Promise.all([page.waitForResponse(r=>r.url().includes('relay_core.messaging.send')),page.getByRole('menuitem',{name:'Resend sticker',exact:true}).click()]); await waitSend(5)
    if(sends[4].body.message!==rows[1].name || sends[4].body.data.file_id!=='known-sticker') throw new Error('Sticker source was not retained')
    const group = page.locator('[data-message="'+rows[4].name+'"]')
    await group.getByRole('button',{name:'Message actions',exact:true}).click();
    if(await page.getByRole('menuitem',{name:'React',exact:true}).count()) throw new Error('Unsupported WhatsApp group reaction visible')
    await page.keyboard.press('Escape')
    await group.getByRole('button',{name:'Reply',exact:true}).click()
    const choices = await page.getByLabel('Type',{exact:true}).locator('option').allTextContents()
    if(choices.some(item=>['location','contact'].includes(item))) throw new Error('Unsupported group type visible')
    await quote.getByRole('button',{name:'Reply',exact:true}).click(); await page.getByLabel('Message',{exact:true}).fill('Retain my draft')
    failure = 'Rejected'
    await page.getByRole('button',{name:'Send',exact:true}).click(); await waitSend(6)
    await page.getByText('Delivery not confirmed. Review the action before retrying.',{exact:true}).waitFor()
    const key = sends[5].body.request_key
    if(await page.getByLabel('Message',{exact:true}).inputValue()!=='Retain my draft') throw new Error('Rejected draft lost')
    failure = 'permission'; await page.getByRole('button',{name:'Send',exact:true}).click(); await waitSend(7)
    await page.getByText('You do not have permission for this action.',{exact:true}).waitFor()
    if(sends[6].body.request_key!==key) throw new Error('Unconfirmed retry used a new key')
    for(const width of [320,768,1440]) { await page.setViewportSize({width,height:900}); if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw new Error('Viewport overflow at '+width) }
    if(errors.length || unexpected.length) throw new Error(JSON.stringify({errors,unexpected}))
    return {passed:true,typedSubmissions:sends.length,permissionFailure:true,retryKeyPreserved:true,viewports:[320,390,768,1440],maximumPage:Math.max(...reads.map(r=>Number(r.limit)||0))}
  } finally {
    page.off('pageerror',onError); page.off('request',onRequest); await page.unroute('**/api/method/**')
  }
}
