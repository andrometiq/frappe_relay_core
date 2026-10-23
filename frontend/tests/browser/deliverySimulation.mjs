export default async function testDelivery(page, origin='http://127.0.0.1:18126') {
 const saves=[],errors=[];let fail=true,resolved=false
 page.on('pageerror',e=>errors.push(e.message))
 await page.addInitScript(()=>{window.frappe={csrf_token:'synthetic-csrf-token',session:{user:'Administrator'}}})
 await page.route('**/api/method/**',async route=>{
  const request=route.request(),method=request.url().split('/').at(-1).split('?')[0]
  if(method==='relay_core.delivery.page')return route.fulfill({json:{message:{deliveries:resolved?[]:[{id:'42',state:'uncertain',error:'Provider outcome not confirmed'}]}}})
  if(method==='relay_core.delivery.resolve'){
   saves.push({body:request.postDataJSON(),headers:request.headers()})
   if(fail)return route.fulfill({status:403,json:{exc:'PermissionError'}})
   resolved=true;return route.fulfill({json:{message:{resolved:true}}})
  }
  throw Error('Unexpected method '+method)
 })
 await page.goto(origin+'/relay#/delivery')
 await page.getByRole('button',{name:'Resolve outcome',exact:true}).click()
 await page.getByLabel('Provider message ID (required except reactions)',{exact:true}).fill('wamid.verified')
 await page.getByLabel('Verification evidence',{exact:true}).fill('Verified in provider message history')
 await page.getByRole('button',{name:'Record resolution',exact:true}).click()
 await page.getByText('You do not have permission for this action.',{exact:true}).waitFor()
 if(await page.getByLabel('Verification evidence',{exact:true}).inputValue()!=='Verified in provider message history')throw Error('Lost evidence draft')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width)}
 fail=false;await page.getByRole('button',{name:'Record resolution',exact:true}).click()
 await page.getByText('No deliveries on this page.',{exact:true}).waitFor()
 if(saves.length!==2||saves[1].body.channel!=='WhatsApp'||saves[1].body.provider_id!=='wamid.verified'||saves[1].headers['x-frappe-csrf-token']!=='synthetic-csrf-token')throw Error('Resolution contract failed')
 if(errors.length)throw Error(errors.join('\n'))
 return {passed:true,evidenceRetained:true,providerReceipt:true,viewports:[320,390,768,1440]}
}
