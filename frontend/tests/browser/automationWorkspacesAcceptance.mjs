import assert from 'node:assert/strict'

// UI interaction fixture only. Connected worker/provider acceptance is Hub steps 13–14.
export default async function automationWorkspacesAcceptance(browser, origin) {
  const page = await browser.newPage()
  const errors = [], writes = [], reads = []
  let status = 'Open', assigned = 'owner@example.invalid'
  let businessName = 'Local supplier'
  const ticket = () => ({ name: 'RELAY-TKT-0000000001', subject: 'Supplier ledger doubt', brief: 'Review October entries.',
    creation: '2026-10-01 12:00:00', business_doctype: 'Supplier', business_name: businessName, category: 'Support',
    status, assigned_to: assigned, can_assign: true, messages: [{ message: 'RELAY-MSG-0000000001', channel: 'WhatsApp' }] })
  const skill = { name: 'RELAY-AIS-0000000001', title: 'Supplier ledger', enabled: 0, business_doctype: 'Supplier',
    channel: '', run_as_user: '', handoff_owner: '', ai_model: '', mode: 'Shadow', daily_limit: 100, instructions: 'Offer a range and confirm.',
    allowed_tools: JSON.stringify([{ name: 'supplier_ledger', method: 'get_list', doctype: 'GL Entry', scope_field: 'party', fields: ['debit', 'credit'] }]) }
  const rule = { name: 'RELAY-BER-0000000001', title: 'Delivery update', enabled: 0, source_doctype: 'Delivery Note',
    event: 'on_submit', business_doctype: 'Customer', recipient_field: 'customer', channel:'Local support-001', template: 'fixture-template', parameter_mapping: '["name","items_summary"]' }
  page.on('pageerror', error => errors.push(error.message))
  await page.addInitScript(() => { window.frappe = { session: { user: 'Administrator' }, csrf_token: 'fixture-only' } })
  await page.route('**/api/method/**', async route => {
    const request = route.request(), url = new URL(request.url()), method = url.pathname.split('/').at(-1)
    const args = request.method() === 'POST' ? request.postDataJSON() : Object.fromEntries(url.searchParams)
    if (request.method() === 'POST') writes.push({ method, args })
    else reads.push({method,args})
    let result
    switch (method) {
      case 'relay_core.api.channel_options': result = {items:[{name:'Local support-001',channel:'WhatsApp',enabled:1}]}; break
      case 'relay_core.display.titles': result = {items:JSON.parse(args.records).map(row => ({...row,title:row.doctype === 'Supplier' ? businessName : row.name}))}; break
      case 'relay_core.api.capabilities': result = { configure: true, manage: true }; break
      case 'relay_core.collaboration.notifications': result = { items: [] }; break
      case 'relay_core.tickets.directory': result = { items: !args.status || args.status === status ? [ticket()] : [] }; break
      case 'relay_core.tickets.read': result = ticket(); break
      case 'relay_core.tickets.transcript': result = {items:[{name:'RELAY-MSG-0000000001',content:'Please check October',direction:'Incoming',status:'Sent',creation:'2026-10-01 12:00:00'}],next:null}; break
      case 'relay_core.tickets.ai_history': result = {items:[{name:'RELAY-AR-0000000001',event:'Supplier ledger',status:'Completed',creation:'2026-10-01 12:00:00',read_count:1,actions:[],deliveries:[]}],next:null}; break
      case 'relay_core.tickets.deliveries': result = {items:[],next:null}; break
      case 'relay_core.tickets.assign': assigned = args.user; result = ticket(); break
      case 'relay_core.tickets.update_status': status = args.status; result = ticket(); break
      case 'relay_core.ai.configuration.editor_options': result = {items:args.kind === 'message' ? [{value:'RELAY-MSG-0000000001',label:'Please check October'}] : []}; break
      case 'relay_core.ai.configuration.directory': result = { items: [skill] }; break
      case 'relay_core.ai.configuration.test_skill': result = { mode: 'Shadow', reply: 'Shall I check October?', handoff: false, reason: '' }; break
      case 'relay_core.business_events.directory': result = { items: [rule] }; break
      case 'relay_core.business_events.template_preview': result = { body: 'Delivered {{1}}: {{2}}' }; break
      default: errors.push('Unexpected API: ' + method); result = {}
    }
    await route.fulfill({ json: { message: result } })
  })
  async function responsive(screen) {
    for (const width of [375, 768, 1440]) {
      await page.setViewportSize({ width, height: 900 })
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, `${screen}: overflow at ${width}`)
      if (width !== 768) await page.screenshot({ path: `.runtime/relay-polish-${screen}-${width}.png`, fullPage: true })
    }
  }
  await page.goto(origin + '/site.html#/tickets')
  await page.getByRole('button', { name: /Supplier ledger doubt/ }).click()
  assert.equal(await page.getByRole('link', { name: /Open conversation/ }).getAttribute('href'), '#/messages?message=RELAY-MSG-0000000001')
  await page.getByRole('region',{name:'Episode transcript'}).getByText('Please check October',{exact:true}).waitFor()
  await page.getByRole('region',{name:'AI history'}).getByText('Supplier ledger',{exact:true}).waitFor()
  for(const method of ['transcript','ai_history','deliveries'])assert.ok(reads.some(row=>row.method==='relay_core.tickets.'+method && row.args.name===ticket().name))
  await responsive('tickets')
  for (const name of ['Local supplier with a very long registered business name '.repeat(2), 'Supplier' + 'x'.repeat(130)]) {
    businessName = name
    await page.reload()
    await page.setViewportSize({ width: 375, height: 900 })
    const badge = page.locator('.ticket-business-badge')
    await badge.waitFor()
    await page.waitForFunction(value => document.querySelector('.ticket-business-badge')?.textContent.trim() === value, name.trim())
    assert.equal(await badge.innerText(), name.trim())
    assert.equal(await badge.evaluate(el => {
      const card = el.closest('.ticket-card').getBoundingClientRect(), bounds = el.getBoundingClientRect()
      return bounds.left >= card.left && bounds.right <= card.right
    }), true, 'Long business badge must fit the 375px card without clipping')
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, 'Long business name overflows at 375px')
    await page.getByRole('button', { name: /Supplier ledger doubt/ }).click()
  }
  await page.screenshot({ path: '.runtime/relay-polish-tickets-long-name-375.png', fullPage: true })
  await page.getByLabel('Assign to user', { exact: true }).fill('agent@example.invalid')
  await page.getByRole('button', { name: 'Assign', exact: true }).click()
  await page.getByRole('button', { name: 'Close ticket', exact: true }).click()
  await page.getByRole('button', { name: 'Dismiss', exact: true }).click()
  await page.getByRole('button', { name: 'Open', exact: true }).click()
  await page.getByRole('heading', { name: 'No matching tickets' }).waitFor()
  await page.getByRole('button', { name: 'Clear filters' }).click()
  await page.getByRole('button', { name: /Supplier ledger doubt/ }).waitFor()
  await page.goto(origin + '/site.html#/skills')
  await page.getByRole('button', { name: 'Open event: Supplier ledger' }).click()
  await page.getByRole('combobox', {name:'Incoming message',exact:true}).click()
  await page.getByRole('option',{name:'Please check October'}).click()
  await page.getByRole('button', { name: 'Run preview' }).click()
  await page.getByText('Shall I check October?', { exact: true }).waitFor()
  await responsive('skills')
  await page.goto(origin + '/site.html#/business-events')
  await page.getByRole('button', { name: /Delivery update/ }).click()
  await page.getByText('Delivered [name]: [items_summary]', { exact: true }).waitFor()
  await page.getByLabel('Template parameters in order (one source field per line)').fill('name\ntotal_qty')
  await page.getByText('Delivered [name]: [total_qty]', { exact: true }).waitFor()
  await responsive('events')
  assert.equal(writes.length, 3)
  assert.deepEqual(writes.map(row => row.method), ['relay_core.tickets.assign', 'relay_core.tickets.update_status', 'relay_core.ai.configuration.test_skill'])
  assert.deepEqual(errors, [])
  await page.close()
  return { passed: true, ticketAssignment: true, ticketClose: true, emptyState: true, shadowResult: true, livePreview: true, widths: [375, 768, 1440] }
}

// Step 11 interaction acceptance. Real HTTP contracts also run on yrp.site.
export async function aiEventEditorAcceptance(browser, origin) {
  const page = await browser.newPage({viewport:{width:1440,height:900}})
  const errors=[], writes=[]
  let reads=0, failSave=false, socket, connections=0
  const skill={name:'RELAY-AIS-0000000001',title:'Supplier ledger',business_doctype:'Supplier',channel:'RELAY-CH-0000000001',
    target:'Explain my ledger',instructions:'Ask for dates and search only this sender',reply_style:'Brief',exact_trigger:'/ledger',
    enabled:0,mode:'Shadow',daily_limit:25,search_confirmation:'Always',execution_policy:'Execute',run_as_user:'owner@example.invalid',handoff_owner:'owner@example.invalid',ai_model:'model-key',
    allowed_tools:JSON.stringify([{name:'supplier_ledger',method:'get_list',doctype:'GL Entry',scope_field:'party',fields:['debit','credit'],identity_anchor:'Supplier',identity_fields:{WhatsApp:'alias'},company_field:'company'}]),allowed_actions:'[{"action":"reply"}]'}
  const options={doctype:[['Supplier','Supplier'],['GL Entry','GL Entry']],field:[['debit','Debit'],['credit','Credit']],identity:[['alias','Alias']],scope:[['party','Party']],company:[['company','Company']],user:[['owner@example.invalid','Maya Rao']],model:[['model-key','Local model']],message:[['RELAY-MSG-0000000001','Please explain my October ledger']],draft_doctype:[['Payment Entry','Payment Entry']],draft_field:[['paid_amount','Paid amount'],['posting_date','Posting date']],action:[['create_draft','Create draft'],['reply','Reply']]}
  page.on('pageerror',e=>errors.push(e.message))
  await page.route('**/site.html',async route=>{
    const response=await route.fetch()
    await route.fulfill({response,body:(await response.text()).replace('id="app"','id="app" data-site="yrp.site"')})
  })
  await page.routeWebSocket(/\/socket.io\//, ws=>{
    socket=ws;connections++
    ws.send('0'+JSON.stringify({sid:'local-editor',upgrades:[],pingInterval:25000,pingTimeout:20000}))
    ws.onMessage(message=>{if(String(message).startsWith('40/yrp.site'))ws.send('40/yrp.site,'+JSON.stringify({sid:'local-event'}));if(message==='2')ws.send('3')})
  })
  await page.route('**/api/method/**',async route=>{
    const request=route.request(), url=new URL(request.url()), method=url.pathname.split('/').at(-1)
    const args=request.method()==='POST'?request.postDataJSON():Object.fromEntries(url.searchParams)
    if(request.method()==='POST')writes.push({method,args})
    let result={}
    switch(method){
      case 'relay_core.api.capabilities':result={configure:true,manage:true};break
      case 'relay_core.collaboration.notifications':result={items:[]};break
      case 'relay_core.api.channel_options':result={items:[{name:skill.channel,title:'Supplier support',channel:'WhatsApp',enabled:1}]};break
      case 'relay_core.display.titles':result={items:JSON.parse(args.records).map(row=>({...row,title:row.doctype==='Relay Channel'?'Supplier support':'Maya Rao'}))};break
      case 'relay_core.ai.configuration.directory':reads++;result={items:[skill],next:null};break
      case 'relay_core.ai.configuration.editor_options':{
        const selected=args.selected?JSON.parse(args.selected):null
        result={items:(options[args.kind]||[]).filter(([value,label])=>selected?selected.includes(value):label.toLowerCase().includes((args.query||'').toLowerCase())).map(([value,label])=>({value,label,required:args.kind==='draft_field'&&value==='posting_date',approval:'None'}))};break
      }
      case 'relay_core.ai.configuration.save':
        if(failSave){await route.fulfill({status:403,json:{exc_type:'PermissionError'}});return}
        Object.assign(skill,args.values);result={name:skill.name};break
      case 'relay_core.ai.configuration.test_skill':result={mode:'Shadow',identity_scope:{identity:'Authenticated sender',provider:'WhatsApp',company:'Local Company',business_type:'Supplier',execution_user:'Maya Rao'},match:{selected:'Supplier ledger',reason:'Exact event trigger'},search:{purpose:'Review October ledger',reference:'supplier_ledger',fields:['debit','credit']},actions:[],reply:'Shall I check October?',reason:''};break
      default:errors.push('Unexpected API '+method)
    }
    await route.fulfill({json:{message:result}})
  })
  await page.goto(origin+'/site.html#/skills')
  await page.getByRole('button',{name:'Open event: Supplier ledger',exact:true}).focus();await page.keyboard.press('Enter')
  await page.getByLabel('Target',{exact:true}).waitFor()
  await page.getByRole('combobox',{name:'Incoming message',exact:true}).focus()
  await page.getByRole('option',{name:'Please explain my October ledger'}).waitFor();await page.keyboard.press('Enter')
  await page.getByRole('button',{name:'Run preview',exact:true}).click()
  await page.getByText('Shall I check October?',{exact:true}).waitFor()
  await page.getByLabel('Reply style',{exact:true}).fill('Short clear words')
  assert.equal(await page.getByRole('button',{name:'Run preview',exact:true}).isDisabled(),true)
  assert.equal(await page.getByText('Shall I check October?',{exact:true}).count(),0)
  const before=reads
  socket.close()
  await new Promise(resolve=>setTimeout(resolve,2500))
  assert.ok(connections>=2);assert.ok(reads>before)
  assert.equal(await page.getByLabel('Reply style',{exact:true}).inputValue(),'Short clear words')
  const settled=reads
  await new Promise(resolve=>setTimeout(resolve,1200));assert.equal(reads,settled,'No polling')
  await page.getByRole('button',{name:'Add create draft',exact:true}).click()
  await page.getByRole('combobox',{name:'Draft DocType',exact:true}).click();await page.getByRole('option',{name:'Payment Entry',exact:true}).click()
  await page.getByRole('combobox',{name:'Draft fields (include required fields)',exact:true}).click();await page.getByRole('option',{name:'Paid amount',exact:true}).click()
  await page.getByRole('button',{name:'Move up',exact:true}).last().click()
  const writeCount=writes.length
  await page.getByRole('button',{name:'Save',exact:true}).click()
  await page.getByText('Include required draft fields: Posting date',{exact:true}).waitFor()
  assert.equal(writes.length,writeCount)
  await page.getByRole('combobox',{name:'Draft fields (include required fields)',exact:true}).click();await page.getByRole('option',{name:/Posting date/}).click()
  failSave=true
  await page.getByRole('button',{name:'Save',exact:true}).click();await page.getByText('You do not have permission for this action.',{exact:true}).waitFor()
  assert.equal(await page.getByLabel('Reply style',{exact:true}).inputValue(),'Short clear words')
  failSave=false
  await page.getByRole('button',{name:'Save',exact:true}).click();await page.getByText('Saved.',{exact:true}).waitFor()
  const saved=writes.filter(row=>row.method.endsWith('.save')).at(-1).args.values
  assert.deepEqual(JSON.parse(saved.allowed_actions).map(row=>row.action),['create_draft','reply'])
  assert.deepEqual(JSON.parse(saved.allowed_tools)[0].identity_fields,{WhatsApp:'alias'})
  for(const theme of ['light','dark'])for(const width of [1440,390]){
    await page.setViewportSize({width,height:900});await page.evaluate(theme=>document.documentElement.dataset.theme=theme,theme)
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1),false)
    assert.ok(await page.locator('.v1-detail-grid').evaluate(el=>el.clientHeight>650))
    assert.ok(await page.locator('form.workflow-card').evaluate(el=>el.clientHeight>650&&getComputedStyle(el).overflowY==='auto'))
    assert.equal(await page.locator('.event-toolbar').evaluate(el=>el.clientHeight<60),true)
    assert.doesNotMatch(await page.locator('.event-workspace').innerText(),/RELAY-[A-Z]+-\d+|model-key|owner@example/)
    await page.locator('form.workflow-card').evaluate(el=>el.scrollTop=0)
    await page.screenshot({path:`.runtime/ai-event-${theme}-${width}.png`,fullPage:true})
  }
  assert.deepEqual(errors,[]);await page.close()
  return {passed:true,widths:[390,1440],themes:['light','dark'],keyboard:true,reconnect:true,saveDenial:true,nonSendingPreview:true}
}
