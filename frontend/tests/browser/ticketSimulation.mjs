import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'

// Uses the built worktree UI with real yrp.site APIs supplied by the site harness.
export default async function testTickets(page, fixture) {
  page.setDefaultTimeout(12000)
  const errors=[], reads=[]
  let socket, connections=0, nextConnection
  page.on('pageerror',error=>errors.push(error.message))
  page.on('request',request=>{
    if(request.url().includes('/api/method/relay_core.tickets.'))reads.push(request)
  })
  await page.routeWebSocket(/\/socket.io\//,ws=>{
    socket=ws; connections++; nextConnection?.()
    ws.send('0'+JSON.stringify({sid:'ticket-local',upgrades:[],pingInterval:25000,pingTimeout:20000}))
    ws.onMessage(message=>{
      if(String(message).startsWith('40/yrp.site'))ws.send('40/yrp.site,'+JSON.stringify({sid:'ticket-local'}))
      if(message==='2')ws.send('3')
    })
  })
  await page.goto(fixture.origin+'/site.html#/tickets')
  console.log('Browser loaded ticket workspace')
  await page.getByLabel('Assignee',{exact:true}).fill(fixture.actor)
  await page.getByRole('button',{name:'Apply',exact:true}).click()
  const open=page.getByRole('button',{name:'Open ticket: '+fixture.subject,exact:true})
  await open.waitFor()
  await open.focus();await page.keyboard.press('Enter')
  console.log('Browser opened fixture ticket')
  const detail=page.locator('.ticket-detail'), history=page.getByRole('region',{name:'AI history'})
  await detail.getByRole('button',{name:'Older AI history',exact:true}).click()
  await history.getByText(fixture.event,{exact:true}).waitFor()
  await detail.getByText('AI active',{exact:true}).waitFor()
  await history.getByText('1 read completed. Raw results are kept private.',{exact:true}).waitFor()
  assert.ok((await history.innerText()).includes('Create draft · Completed'))
  assert.ok((await history.innerText()).includes('Reply · Approved'))
  assert.ok((await history.innerText()).includes('Reply delivery · Uncertain'))
  const draft=detail.getByRole('link',{name:'Payment Entry · '+fixture.draft_title+' · Draft',exact:true})
  assert.equal(await draft.getAttribute('href'),'/app/payment-entry/'+encodeURIComponent(fixture.draft))
  assert.ok(!(await draft.innerText()).includes(fixture.draft),'draft captions must use the human title')
  const transcript=page.getByRole('region',{name:'Episode transcript'})
  await transcript.getByText('/support',{exact:true}).waitFor()
  await transcript.getByRole('button',{name:'More messages',exact:true}).click()
  await transcript.getByText('Sim history line 59',{exact:true}).waitFor()
  assert.equal(await transcript.locator('li').count(),60)
  await page.getByRole('region',{name:'Episode deliveries'}).getByText(/Lifecycle notice · Suppressed/).waitFor()
  assert.ok(!(await detail.innerText()).includes('Sim private accounting values'))
  for(const width of [320,390,768,1440]) {
    await page.setViewportSize({width,height:900})
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false,'overflow '+width)
  }
  const deniedClaim='**/api/method/relay_core.tickets.claim'
  await page.route(deniedClaim,route=>route.fulfill({status:403,json:{exc_type:'PermissionError'}}))
  await detail.getByRole('button',{name:'Take over',exact:true}).click()
  await page.getByText('You do not have permission for this action.',{exact:true}).waitFor()
  await detail.getByText('AI active',{exact:true}).waitFor()
  await page.unroute(deniedClaim)
  await detail.getByRole('button',{name:'Take over',exact:true}).focus();await page.keyboard.press('Enter')
  await detail.getByText('You took over. AI is stopped for this conversation.',{exact:true}).waitFor()
  await detail.getByText('Staff took over',{exact:true}).waitFor()
  assert.equal(await detail.getByRole('button',{name:'Take over',exact:true}).count(),0)
  assert.ok((await history.innerText()).includes('Reply · Stopped'))
  assert.ok((await history.innerText()).includes('Approval invalidated'))
  const before=reads.length
  socket.send('42/yrp.site,'+JSON.stringify(['relay_changed',{kind:'tickets'}]))
  await page.waitForResponse(response=>response.url().includes('tickets.ai_history')&&response.ok())
  assert.ok(reads.length>before)
  await transcript.getByText('Sim history line 59',{exact:true}).waitFor()
  assert.equal(await transcript.locator('li').count(),60)
  await history.getByText(fixture.event,{exact:true}).waitFor()
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Start work'&&!b.disabled))
  const refreshed=page.waitForResponse(response=>response.url().includes('tickets.transcript')&&new URL(response.url()).searchParams.has('after')&&response.ok())
  const reconnected=new Promise(resolve=>{nextConnection=resolve})
  socket.close()
  await Promise.race([reconnected,new Promise((_,reject)=>setTimeout(()=>reject(new Error('Socket reconnect timed out')),10000))])
  await refreshed
  await page.waitForFunction(()=>[...document.querySelectorAll('button')].some(b=>b.textContent.trim()==='Start work'&&!b.disabled))
  await transcript.getByText('Sim history line 59',{exact:true}).waitFor()
  assert.ok(connections>=2)
  await page.waitForTimeout(500)
  const settled=reads.length
  await page.waitForTimeout(1800)
  assert.equal(reads.length,settled,'ticket polling is forbidden')
  // Permission revocation must remove the stale transcript and draft links.
  await page.route('**/api/method/relay_core.tickets.ai_history*',route=>route.fulfill({status:403,json:{exc_type:'PermissionError'}}))
  socket.send('42/yrp.site,'+JSON.stringify(['relay_changed',{kind:'tickets'}]))
  await page.getByText('You do not have permission for this action.',{exact:true}).waitFor()
  assert.equal(await detail.count(),0)
  assert.deepEqual(errors,[])
  console.log('PASS built UI + yrp.site HTTP: history, transcript, draft navigation, keyboard takeover, approval invalidation, 320/390/768/1440px; Socket.IO update/reconnect, no polling, permission-revocation clearing')
}

if(process.argv[1] && import.meta.url===pathToFileURL(process.argv[1]).href) {
  let input='';for await(const chunk of process.stdin)input+=chunk
  const {chromium}=await import('../../../.runtime/browser/node_modules/playwright/index.mjs')
  const browser=await chromium.launch({executablePath:process.env.CHROME_PATH||'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']})
  try {await testTickets(await browser.newPage({viewport:{width:390,height:900}}),JSON.parse(input))}
  finally {await browser.close()}
}
