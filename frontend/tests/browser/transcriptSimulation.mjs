export default async function testTranscript(page,origin='http://127.0.0.1:18126'){
 const errors=[],transcript='Please check my invoice. <script>unsafe()</script>'
 page.on('pageerror',e=>errors.push(e.message))
 await page.route('**/api/method/**',async route=>{const method=route.request().url().split('/').at(-1).split('?')[0];if(method!=='relay_core.automation.service.runs')throw Error('Unexpected '+method);return route.fulfill({json:{message:{items:[{id:'RELAY-AR-0000000001',name:'RELAY-AR-0000000001',status:'Shadow',message:'RELAY-MSG-0000000001',delivery:'No reply',transcript}],previous:null,next:null}}})})
 await page.goto(origin+'/relay#/automation');await page.getByRole('button',{name:'Read transcript',exact:true}).click();await page.getByText(transcript,{exact:true}).waitFor()
 if(await page.getByRole('link',{name:'RELAY-MSG-0000000001',exact:true}).getAttribute('href')!=='#/messages?message=RELAY-MSG-0000000001')throw Error('Message navigation lost')
 for(const width of [320,390,768,1440]){await page.setViewportSize({width,height:900});if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1))throw Error('Overflow '+width)}
 if(errors.length)throw Error(errors.join('\n'))
 return {passed:true,transcriptEscaped:true,messageNavigation:true,viewports:[320,390,768,1440]}
}
