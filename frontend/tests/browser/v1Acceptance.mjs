import assert from 'node:assert/strict'

// Run with an already installed Playwright driver; no project dependencies added.
export default async function v1Acceptance(browser, origin = 'http://127.0.0.1:18147') {
  const page = await browser.newPage()
  const errors = [], requests = []
  page.on('pageerror', e => errors.push(e.message))
  const contact = 'RELAY-CON-0000000001', channel = 'RELAY-CH-0000000001'
  const message = { name: 'RELAY-MSG-0000000001', relay_contact: contact, frappe_contact: 'V1 Asha', contact_label: 'V1 Asha', channel, sender_endpoint: '15550000001', content: 'V1 local fixture: order 42, amount 1250', direction: 'Incoming', status: 'Received', creation: '2026-10-24 12:00:00', provider_context: { provider: 'WhatsApp' }, message_type: 'text', message_data: { kind: 'text', text: 'V1 local fixture: order 42, amount 1250' } }
  const secondContact = 'RELAY-CON-0000000002'
  const secondMessage = { ...message, name: 'RELAY-MSG-0000000002', relay_contact: secondContact, frappe_contact: 'V1 Bala', contact_label: 'V1 Bala', sender_endpoint: '15550000002', creation: '2026-10-24 12:01:00', content: 'V1 Bala order 43', message_data: { kind: 'text', text: 'V1 Bala order 43' } }
  const unread = new Map([[contact, 2], [secondContact, 1]])
  const notes = []
  const template = { id: 'v1-template', name: 'order_update', status: 'REJECTED', rejected_reason: 'Missing variable sample', language: 'en_US', category: 'UTILITY', components: [{ type: 'BODY', text: 'Order {{1}} is ready', example: { body_text: [['42']] } }] }
  let rejectSave = false
  await page.addInitScript(() => { window.frappe = { session: { user: 'Administrator' }, csrf_token: 'local-fixture' } })
  await page.route('**/api/method/**', async route => {
    const url = new URL(route.request().url()), method = url.pathname.split('/').at(-1)
    const args = route.request().method() === 'POST' ? route.request().postDataJSON() : Object.fromEntries(url.searchParams)
    requests.push({ method, args })
    let data
    switch (method) {
      case 'relay_core.display.titles': data = {items: JSON.parse(args.records).map(row => ({...row, title:row.name}))}; break
      case 'relay_core.api.channel_options': data = {items:[{name:channel,channel:'WhatsApp',enabled:1}]}; break
      case 'relay_core.api.capabilities': data = { manage: true, configure: true }; break
      case 'relay_core.collaboration.notifications': data = { items: [{ name: 'V1 Notification', relay_contact: secondContact, contact_name: 'V1 Bala', body: 'V1 note for Bala', kind: 'Mention', is_read: 0 }] }; break
      case 'relay_core.collaboration.mark_notification': data = {}; break
      case 'relay_core.inbox.directory': data = { items: [message, secondMessage].map(row => ({ name: row.relay_contact, contact: row.frappe_contact, display_name: row.contact_label, unread: unread.get(row.relay_contact), latest_preview: row.content })).filter(row => (args.mode !== 'unread' || row.unread) && (!args.query || row.display_name.includes(args.query))) }; break
      case 'relay_core.api.business_types': data = ['Customer']; break
      case 'relay_core.business_groups.directory': data = { field: 'territory', items: [{ value: 'V1 North', label: 'V1 North' }] }; break
      case 'relay_core.business_groups.records': data = { items: [{ name: 'V1 Customer', label: 'V1 Customer', unread: 2 }], next: null }; break
      case 'relay_core.business_inbox.context': data = { title: 'V1 Customer', contact_count: 3 }; break
      case 'relay_core.business_inbox.contacts': data = { items: [{ value: 'V1 Asha', label: 'V1 Asha', has_phone: true, description: '+15550000001' }, { value: 'V1 Bala', label: 'V1 Bala', has_phone: true, description: '+15550000002' }, { value: 'V1 New contact', label: 'V1 New contact', has_phone: true, description: '+15550000003' }] }; break
      case 'relay_core.business_inbox.messages': data = { items: [message, secondMessage], first: message.name, last: secondMessage.name, ingestion_cursor: secondMessage.name, has_more: false }; break
      case 'relay_core.api.contact_profile': data = {name:args.contact, contact:args.contact === secondContact ? 'V1 Bala' : 'V1 Asha', display_name:args.contact === secondContact ? 'V1 Bala' : 'V1 Asha'}; break
      case 'relay_core.api.contact_directory':
        if (args.query === 'failure') { await route.fulfill({status:417,json:{_server_messages:JSON.stringify([JSON.stringify({message:'Contact search is temporarily unavailable'})])}}); return }
        data = {items:args.query === 'no-match' ? [] : [{name:'V1 Asha',full_name:'V1 Asha',mobile_no:'+15550000001'}]}; break
      case 'relay_core.api.messages': {
        const row = args.contact === secondContact ? secondMessage : message
        if (args.contact === secondContact) await new Promise(resolve => setTimeout(resolve, 120))
        data = { items: [row], first: row.name, last: row.name, ingestion_cursor: row.name, has_more: false }; break
      }
      case 'relay_core.business_inbox.view_state':
      case 'relay_core.inbox.view_state': data = {}; break
      case 'relay_core.business_inbox.presence':
      case 'relay_core.inbox.presence': data = { users: [] }; break
      case 'relay_core.inbox.read': data = { unread: 2, can_assign: true, assignment: {} }; break
      case 'relay_core.api.conversation_channels': data = { items: [{ value: channel, label: 'WhatsApp' }] }; break
      case 'relay_core.messaging.pending_messages': data = { items: [] }; break
      case 'relay_core.messaging.action_snapshots': data = { items: [] }; break
      case 'relay_core.messaging.reply_window': data = { open: true, remaining_seconds: 3600 }; break
      case 'relay_core.api.message_snapshots': data = { items: [message] }; break
      case 'relay_core.message_reads.cursors':
      case 'relay_core.business_inbox.readers': data = { readers: [] }; break
      case 'relay_core.messaging.actions': data = { items: [{ name: 'RELAY-MA-0000000001', status: 'Rejected', preview: 'Order 42 is ready', error: 'Provider rejected the request', creation: '2026-10-24 12:00:00', can_retry: true }] }; break
      case 'relay_core.messaging.retry': data = { status: 'Queued' }; break
      case 'relay_core.collaboration.comments': data = { items: notes.filter(row => row.contact === args.contact) }; break
      case 'relay_core.collaboration.add':
        assert.equal(args.contact, secondContact)
        assert.deepEqual(args.messages, [secondMessage.name])
        notes.push({ ...args, name: 'V1 Note', author_name: 'Local fixture' }); data = {}; break
      case 'relay_core.conversation_start.options': data = [{ value: 'endpoint-' + args.contact, label: '+1 555 000 0099', provider: 'WhatsApp', window: { open: true } }]; break
      case 'relay_core.conversation_start.send': assert.equal(args.contact, secondContact); data = { status: 'Queued' }; break
      case 'relay_core.teams.directory': data = { items: [{ name: 'V1 Support', title: 'V1 Support' }] }; break
      case 'relay_core.teams.read': data = { name: 'V1 Support', title: 'V1 Support', members: ['agent@example.invalid'] }; break
      case 'relay_core.teams.agents': data = [{ name: 'agent@example.invalid', full_name: 'V1 Agent' }]; break
      case 'relay_core.teams.save':
        if (rejectSave) { await route.fulfill({ status: 417, json: { _server_messages: JSON.stringify([JSON.stringify({ message: 'The user needs a Relay communication role' })]) } }); return }
        data = args; break
      case 'relay_core.settings.connection': data = { url: 'https://hub.example.invalid/mcp', account: 'v1-local', token_configured: true, callback_configured: false, can_configure: true }; break
      case 'relay_core.whatsapp.connection': data = { configured: true }; break
      case 'relay_core.whatsapp.execute': data = args.operation === 'capabilities' ? { templates: true } : args.operation === 'templates.list' ? { data: [template] } : { profile: { display_phone_number: '+1 555 000 0099', verified_name: 'V1 Fixture', quality_rating: 'GREEN' }, status: 'ready', last_success: '2026-10-24T12:00:00Z' }; break
      case 'relay_core.api.contact_details': data = { name: 'V1 Asha', label: 'V1 Asha', phone: '+15550000001', links: [{ doctype: 'Customer', name: 'V1 Customer' }], endpoints: [{ name: 'endpoint', channel, endpoint: '15550000001', verified: true, creation: '2026-10-24', modified: '2026-10-24' }] }; break
      case 'relay_core.enrollment.pending': data = { items: [{ event: 'event', endpoint: '15550000002', medium: 'WhatsApp', preview: 'Local unmatched sender', ambiguous: true }] }; break
      case 'relay_core.operations.recovery_status': data = { mode: 'Frappe scheduler', inactive: false, reasons: [], items: [{ label: 'Message receipt recovery', state: 'Completed recently', last_started: '2026-10-24 12:00:00' }], checked_at: '2026-10-24 12:01:00' }; break
      case 'relay_core.operations.callback_status': data = { latest: { creation: '2026-10-24', projection_status: 'Failed' }, items: [{ name: 'RELAY-EVT-0000000001', projection_status: 'Failed', creation: '2026-10-24' }] }; break
      case 'relay_core.delivery.page': data = { deliveries: [{ id: 1, state: 'uncertain', error: 'Timeout; acceptance unknown' }] }; break
      case 'relay_core.whatsapp.metadata_status': data = { status: 'ready', template_count: 1 }; break
      case 'relay_core.canned_replies.directory': data = { items: [{ name: 'V1 Reply', title: 'Order status', body: 'Order 42 is ready.', published: true }], can_configure: true }; break
      case 'frappe.client.get': data = { name: args.name, contact: args.name === secondContact ? 'V1 Bala' : 'V1 Asha', display_name: args.name === secondContact ? 'V1 Bala' : 'V1 Asha' }; break
      case 'frappe.client.get_list':
        if (args.filters?.includes('failure')) { await route.fulfill({status: 417, json: {_server_messages: JSON.stringify([JSON.stringify({message:'Contact search is temporarily unavailable'})])}}); return }
        if (args.filters?.includes('no-match')) { data = []; break }
        data = args.doctype === 'Contact' ? [{ name: 'V1 Asha', full_name: 'V1 Asha', mobile_no: '+15550000001' }] : [{ ...message, direction: 'Outgoing', status: 'Failed' }]; break
      // Presence/read-cursor writes remain intercepted; no external delivery is possible.
      case 'relay_core.inbox.update':
      case 'relay_core.message_reads.mark': {
        const ids = args.messages ? JSON.parse(args.messages) : args.last_read ? [args.last_read] : []
        const expected = args.contact === secondContact ? secondMessage : message
        assert.ok(ids.every(id => id === expected.name), 'Read inputs must belong to their contact')
        if (ids.length) unread.set(args.contact, 0)
        data = { unread: unread.get(args.contact) }; break
      }
      case 'relay_core.business_inbox.mark_visible': data = {}; break
      case 'relay_core.inbox.typing':
      case 'relay_core.inbox.save_view':
      case 'relay_core.business_inbox.read':
      case 'relay_core.business_inbox.typing':
      case 'relay_core.business_inbox.save_view': data = {}; break
      default: errors.push('Unexpected API: ' + method); data = {}
    }
    await route.fulfill({ json: { message: data } })
  })
  const overflow = async label => {
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1), false, label + ': horizontal page overflow')
  }
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(origin)
  await page.getByRole('button', { name: 'Unread', exact: true }).click()
  await page.getByRole('button', { name: 'V1 Asha', exact: false }).click()
  await page.getByRole('button', { name: 'Mark read', exact: true }).click()
  await page.locator('.directory-contact').filter({ hasText: 'V1 Asha' }).waitFor({ state: 'detached' })
  await page.getByLabel('Message', { exact: true }).fill('Draft for Asha only')
  await page.getByRole('button', { name: 'Businesses', exact: true }).click()
  await page.getByRole('button', { name: 'V1 Customer', exact: false }).click()
  await page.getByRole('button', { name: 'V1 Asha', exact: false }).click()
  await page.getByLabel('Message', { exact: true }).fill('Never send this to the new contact')
  await page.getByRole('button', { name: 'V1 New contact', exact: false }).click()
  assert.equal(await page.getByLabel('Message', { exact: true }).count(), 0)
  await page.getByRole('button', { name: 'Message V1 New contact', exact: true }).waitFor()
  await page.getByRole('button', { name: 'V1 Asha', exact: false }).click()
  assert.equal(await page.getByLabel('Message', { exact: true }).inputValue(), 'Never send this to the new contact')
  await page.getByRole('button', { name: 'Conversation actions', exact: true }).click()
  await page.getByRole('menuitem', { name: 'Delivery failures and retry', exact: true }).click()
  await page.getByRole('button', { name: 'Review retry', exact: true }).click()
  await page.getByRole('button', { name: 'Retry rejected send', exact: true }).click()
  await page.getByText('Message status: Queued', { exact: true }).waitFor()
  await page.keyboard.press('Escape')
  await page.locator('.business-contact-strip').getByRole('button', { name: 'All', exact: false }).click()
  await page.locator(`[data-message="${message.name}"]`).getByRole('button', { name: 'Reply', exact: true }).click()
  const readRequest = page.waitForRequest(request => request.url().endsWith('relay_core.inbox.update') && request.postDataJSON()?.last_read)
  await page.getByRole('button', { name: 'Mark read', exact: true }).click()
  assert.equal((await readRequest).postDataJSON().last_read, message.name)
  // Keep A as the recipient while discussing B's message in the mixed timeline.
  const touchTargets = async (selector, reopen) => {
    for (const width of [390, 1440]) {
      if (reopen) {
        await page.keyboard.press('Escape')
        await page.locator(selector).first().waitFor({ state: 'hidden' })
      }
      await page.setViewportSize({ width, height: 1000 })
      if (reopen) await reopen()
      await page.locator(selector).first().waitFor()
      const sizes = await page.locator(selector).evaluateAll(nodes => nodes.filter(node => node.getClientRects().length).map(node => ({ text: node.textContent, width: node.getBoundingClientRect().width, height: node.getBoundingClientRect().height })))
      assert.ok(sizes.length)
      assert.deepEqual(sizes.filter(size => size.height < 40 || size.width < 40), [], 'Overlay touch targets at ' + width)
      await overflow('Overlay at ' + width)
    }
  }
  await touchTargets('.relay-menu button', () => page.locator(`[data-message="${secondMessage.name}"]`).getByRole('button', { name: 'Message actions', exact: true }).click())
  await page.getByRole('menuitem', { name: 'Discuss internally', exact: true }).click()
  await page.getByRole('textbox', { name: 'Internal note', exact: true }).fill('Local note for Bala only')
  await page.getByRole('button', { name: 'Add internal note', exact: true }).click()
  await page.getByText('Local note for Bala only', { exact: true }).waitFor()
  await page.getByRole('button', { name: 'Clear linked messages', exact: true }).waitFor({ state: 'detached' })
  await page.getByRole('button', { name: 'Close internal notes', exact: true }).click()
  await page.locator('.v1-queues').getByRole('button', { name: 'All', exact: true }).click()
  await page.locator('.directory-contact').filter({ hasText: 'V1 Asha' }).click()
  await page.getByRole('heading', { name: 'V1 Asha', exact: true }).waitFor()
  assert.equal(await page.getByRole('heading', { name: 'V1 Customer', exact: true }).count(), 0)
  await page.getByLabel('Message', { exact:true }).focus()
  await page.locator('.business-recipient-bar').getByRole('button', { name: 'Change', exact: true }).click()
  await page.getByRole('button', { name: 'New message', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await dialog.getByLabel('Message', { exact: true }).waitFor()
  await dialog.getByRole('combobox', { name: 'Contact', exact: true }).fill('V1 Bala')
  await dialog.getByRole('option', { name: 'V1 Bala', exact: true }).click()
  await dialog.getByLabel('Message', { exact: true }).fill('Local send for Bala only')
  await touchTargets('.relay-dialog button, .relay-dialog input, .relay-dialog select')
  await dialog.getByRole('button', { name: 'Send message', exact: true }).click()
  await page.getByRole('heading', { name: 'V1 Bala', exact: true }).waitFor()
  assert.equal(new URLSearchParams((await page.evaluate(() => location.hash)).split('?')[1]).get('contact'), secondContact)
  // Notifications must work after mounting Inbox and when reopening the same contact.
  await page.goto(origin + '/#/settings')
  for (let attempt = 0; attempt < 2; attempt++) {
    await page.getByRole('button', { name: 'Notifications', exact: true }).click()
    await page.getByText('V1 note for Bala', { exact: true }).click()
    await page.getByRole('textbox', { name: 'Internal note', exact: true }).waitFor()
    await page.getByRole('heading', { name: 'V1 Bala', exact: true }).waitFor()
    assert.equal(await page.evaluate(() => location.hash.includes('notes=')), false)
    await page.getByRole('button', { name: 'Close internal notes', exact: true }).click()
  }
  for (const width of [320, 390, 640, 768, 1440]) {
    await page.setViewportSize({ width, height: 1000 })
    for (const [route, text] of [['messages','Inbox'], ['contacts','Contacts & links'], ['whatsapp','Templates'], ['teams','Teams & access'], ['settings','Settings & setup'], ['activity','Activity & health']]) {
      await page.goto(origin + '/#/' + route)
      await page.getByRole('heading', { name: text, exact: true }).first().waitFor()
      await page.waitForTimeout(160)
      await overflow(route + ' at ' + width)
      assert.equal(await page.getByLabel('Notifications', { exact: true }).isVisible(), true)
    }
  }
  await page.setViewportSize({ width: 390, height: 844 })
  await page.getByRole('button', { name: 'Open navigation', exact: true }).click()
  await page.getByRole('button', { name: 'Settings & setup', exact: true }).click()
  await page.getByRole('heading', { name: 'Setup checklist' }).waitFor()
  await page.goto(origin + '/#/whatsapp')
  await page.getByText('order_update', { exact: true }).waitFor()
  assert.equal(await page.getByRole('cell').filter({ hasText: 'English' }).isVisible(), true)
  await page.getByText('order_update', { exact: true }).click()
  await page.getByText('Missing variable sample', { exact: true }).waitFor()
  await page.goto(origin + '/#/contacts')
  await page.getByLabel('Search Frappe Contacts', { exact: true }).fill('no-match')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await page.getByText('No contacts match this search.', { exact: true }).waitFor()
  await page.getByLabel('Search Frappe Contacts', { exact: true }).fill('failure')
  await page.getByRole('button', { name: 'Search', exact: true }).click()
  await page.getByText('Contact search is temporarily unavailable', { exact: true }).waitFor()
  await page.goto(origin + '/#/teams')
  await page.getByRole('button', { name: 'V1 Support', exact: false }).click()
  rejectSave = true
  await page.getByRole('button', { name: 'Save team', exact: true }).click()
  await page.getByText('The user needs a Relay communication role', { exact: true }).first().waitFor()
  await page.goto(origin + '/#/teams?business_doctype=Customer&group=V1%20North')
  await page.getByRole('heading', { name: 'V1 North', exact: true }).waitFor()
  assert.deepEqual(errors, [])
  await page.screenshot({ path: '.runtime/v1-mobile.png' })
  await page.setViewportSize({ width: 1440, height: 1000 })
  await page.goto(origin + '/#/settings')
  await page.getByRole('heading', { name: 'Setup checklist' }).waitFor()
  await page.screenshot({ path: '.runtime/v1-desktop.png' })
  await page.close()
  return { viewports: [320, 390, 640, 768, 1440], screens: 6, recipientReset: true, reviewedRetry: true, inlineServerError: true, restoredBusinessGroup: true, unreadRefresh: true, contactScopedReadsAndNotes: true, sendNavigation: true, notificationNotes: true, clearedBusinessContext: true, overlayTouchTargets: true, requests: requests.length }
}
