import assert from 'node:assert/strict'

// UI interaction fixture only. Connected worker/provider acceptance is Hub steps 13–14.
export default async function automationWorkspacesAcceptance(browser, origin) {
  const page = await browser.newPage()
  const errors = [], writes = []
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
    let result
    switch (method) {
      case 'relay_core.api.channel_options': result = {items:[{name:'Local support-001',channel:'WhatsApp',enabled:1}]}; break
      case 'relay_core.display.titles': result = {items:JSON.parse(args.records).map(row => ({...row,title:row.doctype === 'Supplier' ? businessName : row.name}))}; break
      case 'relay_core.api.capabilities': result = { configure: true, manage: true }; break
      case 'relay_core.collaboration.notifications': result = { items: [] }; break
      case 'relay_core.tickets.directory': result = { items: !args.status || args.status === status ? [ticket()] : [] }; break
      case 'relay_core.tickets.read': result = ticket(); break
      case 'relay_core.tickets.assign': assigned = args.user; result = ticket(); break
      case 'relay_core.tickets.update_status': status = args.status; result = ticket(); break
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
  await page.getByRole('button', { name: /Supplier ledger.*Disabled/ }).click()
  await page.getByLabel('Incoming message reference').fill('RELAY-MSG-0000000001')
  await page.getByRole('button', { name: 'Run shadow test' }).click()
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
