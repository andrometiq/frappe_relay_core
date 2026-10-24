import assert from 'node:assert/strict'

// Exercises the actual worktree site build with bounded, non-sending API fixtures.
export default async function workspaceDensityAcceptance(browser, origin) {
  const page = await browser.newPage(), errors = []
  await page.addInitScript(() => sessionStorage.clear())
  page.on('pageerror', error => errors.push(error.message))
  const contact = 'RELAY-CON-0000000001', channel = 'RELAY-CH-0000000001'
  let provider = 'Telegram'
  const message = () => ({name:'RELAY-MSG-0000000001', relay_contact:contact, channel, channel_title:'Customer support',
    sender_endpoint:provider === 'Email' ? 'maya@example.invalid' : '123456', direction:'Incoming', status:'Received',
    content:'Order 42, amount 1250', creation:'2026-10-25 12:00:00', message_type:'text',
    message_data:{kind:'text',text:'Order 42, amount 1250'},
    provider_context:{provider, subject:'Order 42', to:['support@example.invalid','colleague@example.invalid'],
      cc:['help@example.invalid'], mailbox_addresses:['support@example.invalid','help@example.invalid']}})
  await page.route('**/api/method/**', async route => {
    const url = new URL(route.request().url()), method = url.pathname.split('/').at(-1)
    const args = route.request().method() === 'POST' ? route.request().postDataJSON() : Object.fromEntries(url.searchParams)
    let data = {}
    switch (method) {
      case 'relay_core.api.capabilities': data = {manage:true, configure:true}; break
      case 'relay_core.collaboration.notifications': data = {items:[]}; break
      case 'relay_core.display.titles': data = {items:JSON.parse(args.records).map(row => ({...row,title:row.doctype === 'Relay Channel' ? 'Customer support' : 'Maya Rao'}))}; break
      case 'relay_core.api.channel_options': data = {items:[{name:channel,channel:provider,enabled:1}]}; break
      case 'relay_core.ai.configuration.directory': data = {items:Array.from({length:45}, (_,i) => ({name:`RELAY-AIS-${String(i).padStart(10,'0')}`,title:`Order assistance ${i+1}`,business_doctype:'Customer',channel,mode:'Shadow',enabled:0,instructions:'Help with order totals.',allowed_tools:'[]'}))}; break
      case 'relay_core.business_events.directory': data = {items:Array.from({length:45}, (_,i) => ({name:`RELAY-BER-${String(i).padStart(10,'0')}`,title:`Delivery update ${i+1}`,source_doctype:'Delivery Note',business_doctype:'Customer',event:'on_submit',enabled:0,parameter_mapping:'[]'}))}; break
      case 'relay_core.inbox.directory': data = {items:[{name:contact,display_name:'Maya Rao',provider,latest_preview:'Order 42, amount 1250',unread:2}]}; break
      case 'relay_core.api.contact_profile': data = {name:contact,display_name:'Maya Rao',contact:'maya'}; break
      case 'relay_core.api.messages': data = {items:Array.from({length:15}, (_,i) => ({...message(),name:`RELAY-MSG-${String(i+1).padStart(10,'0')}`})),has_more:false}; break
      case 'relay_core.api.message_snapshots': data = {items:[]}; break
      case 'relay_core.inbox.read': data = {unread:2,assignment:{},can_assign:true}; break
      case 'relay_core.inbox.presence': data = {users:[]}; break
      case 'relay_core.api.conversation_channels': data = {items:[{value:channel,label:provider}]}; break
      case 'relay_core.messaging.pending_messages':
      case 'relay_core.messaging.action_snapshots': data = {items:[]}; break
      case 'relay_core.message_reads.cursors': data = {readers:[]}; break
      case 'relay_core.email_preferences.read': data = {signature:''}; break
      case 'relay_core.inbox.view_state':
      case 'relay_core.inbox.update':
      case 'relay_core.inbox.save_view':
      case 'relay_core.inbox.typing':
      case 'relay_core.message_reads.mark': break
      default: errors.push('Unexpected API: '+method)
    }
    await route.fulfill({json:{message:data}})
  })
  const overflow = async () => assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false)
  for (const theme of ['light','dark']) {
    await page.setViewportSize({width:1440,height:900})
    for (const route of ['skills','business-events']) {
      await page.goto(origin+'/site.html#/'+route)
      await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme)
      await page.locator('.v1-list-card').first().waitFor()
      assert.ok(await page.locator('.v1-list-card').first().evaluate(el => el.clientHeight < 90))
      assert.ok(await page.locator('.v1-detail-grid').evaluate(el => el.clientHeight > 650))
      await page.locator('.v1-list-card').first().click()
      const bounds = await page.locator('.v1-detail-grid').evaluate(el => [...el.children].map(child => ({height:child.clientHeight,scroll:child.scrollHeight,overflow:getComputedStyle(child).overflowY})))
      assert.ok(bounds.every(pane => pane.height > 650 && pane.overflow === 'auto'))
      assert.ok(bounds[0].scroll > bounds[0].height)
      await overflow()
      await page.screenshot({path:`.runtime/density-${route}-${theme}.png`})
      await page.setViewportSize({width:390,height:844}); await overflow()
      await page.setViewportSize({width:1440,height:900})
    }
    for (provider of ['Telegram','Email']) {
      for (const width of [390,1440]) {
        await page.setViewportSize({width,height:844})
        await page.goto(origin+'/site.html?density='+provider+width+theme+'#/messages')
        await page.evaluate(theme => document.documentElement.dataset.theme = theme, theme)
        await page.locator('.directory-contact').click()
        await page.getByLabel('Message',{exact:true}).waitFor({timeout:5000}).catch(error => { console.error({provider,width,theme,errors}); throw error })
        const header = await page.locator('.conversation-heading').boundingBox()
        const composer = await page.locator('.message-composer').boundingBox()
        const thread = await page.locator('.message-thread').boundingBox()
        assert.ok(header.height <= 58, 'Single conversation header')
        assert.ok(composer.height <= 68, `Collapsed ${provider} composer: ${composer.height}`)
        assert.ok(thread.height >= 550, 'Thread keeps most of the viewport')
        assert.equal(await page.getByRole('button',{name:'Search conversation',exact:true}).count(), 0)
        await page.getByRole('button',{name:'Conversation actions'}).click()
        assert.equal(await page.getByRole('menuitem',{name:'Search conversation',exact:true}).isVisible(), true)
        await page.keyboard.press('Escape')
        await page.getByLabel('Message',{exact:true}).fill('Please check order 42')
        if (provider === 'Email') {
          await page.getByRole('button',{name:'Reply all',exact:true}).click()
          assert.equal(await page.getByLabel('CC',{exact:true}).inputValue(),'colleague@example.invalid')
          assert.equal(await page.getByLabel('To',{exact:true}).inputValue(),'maya@example.invalid')
        }
        await overflow()
        assert.ok((await page.locator('.message-thread').boundingBox()).height >= 360)
        // Let the shared button background transition settle before inspecting themes.
        await page.waitForTimeout(180)
        await page.screenshot({path:`.runtime/density-${provider}-${theme}-${width}.png`})
      }
    }
  }
  assert.deepEqual(errors, [])
  await page.close()
  return {themes:2,viewports:[390,1440],independentPanes:true,collapsedComposer:true,replyAll:true}
}
