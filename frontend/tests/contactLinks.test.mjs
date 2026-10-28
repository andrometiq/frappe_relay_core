import test from 'node:test'
import assert from 'node:assert/strict'
import { businessTypeOptions, isPrimaryLink, linkFromChoice, linkedLabel, linksWith, linksWithout, primaryRequest, recordIcon, searchLinkChoices } from '../src/services/contactLinks.js'

const customer = { doctype: 'Customer', name: 'C1' }, order = { doctype: 'Sales Order', name: 'SO-1' }

test('adding a link appends it once and removing keeps the other links', () => {
  assert.deepEqual(linksWith([customer], order), [customer, order])
  assert.deepEqual(linksWith([customer, order], { ...order }), [customer, order])
  assert.deepEqual(linksWithout([customer, order], { doctype: 'Customer', name: 'C1' }), [order])
  assert.deepEqual(linksWithout([customer], { doctype: 'Supplier', name: 'C1' }), [customer])
})

test('the primary switch marks one record or clears the mark', () => {
  assert.deepEqual(primaryRequest('CONT-1', order, true), { contact: 'CONT-1', doctype: 'Sales Order', name: 'SO-1' })
  assert.deepEqual(primaryRequest('CONT-1', order, false), { contact: 'CONT-1' })
  assert.equal(isPrimaryLink({ ...order, title: 'Order' }, order), true)
  assert.equal(isPrimaryLink(null, order), false)
  assert.equal(isPrimaryLink(customer, order), false)
})

test('only enabled business types are offered for a new link', () => {
  const types = [{ business_doctype: 'Customer', label: 'Customers', enabled: 1 }, { business_doctype: 'Supplier', enabled: 0 }, { business_doctype: 'Sales Order', enabled: 1 }]
  assert.deepEqual(businessTypeOptions(types), [{ value: 'Customer', label: 'Customers' }, { value: 'Sales Order', label: 'Sales Order' }])
  assert.deepEqual(businessTypeOptions(undefined), [])
})

test('linked record tiles show parties, deliveries and other documents apart', () => {
  assert.deepEqual(recordIcon('Customer'), { icon: 'building', tone: 'green' })
  assert.deepEqual(recordIcon('Delivery Note'), { icon: 'truck', tone: 'purple' })
  assert.deepEqual(recordIcon('Sales Order'), { icon: 'file-text', tone: 'blue' })
  assert.deepEqual(recordIcon(undefined), { icon: 'file-text', tone: 'blue' })
})

test('the chat header counts linked records other than the primary', () => {
  const primary = { doctype: 'Sales Order', name: 'SO-1', title: 'SO-1' }
  assert.equal(linkedLabel({ primary, link_count: 3 }), '+2 linked')
  assert.equal(linkedLabel({ primary, link_count: 1 }), '')
  assert.equal(linkedLabel({ primary: null, link_count: 2 }), '2 linked')
  assert.equal(linkedLabel({ primary: null, link_count: 0 }), '')
  assert.equal(linkedLabel(null), '')
})

test('one link search covers every type, names the type and skips a type that fails', async () => {
  const types = [{ value: 'Customer', label: 'Customer' }, { value: 'Supplier', label: 'Supplier' }]
  const choices = await searchLinkChoices(types, async doctype => {
    if (doctype === 'Supplier') throw Error('Not permitted')
    return [{ name: 'CUST-1', label: 'Anil Garments' }, { name: 'CUST-2' }]
  })
  assert.deepEqual(choices.map(row => [row.label, row.description]), [['Anil Garments', 'Customer'], ['CUST-2', 'Customer']])
  assert.deepEqual(linkFromChoice(choices[0].value), { doctype: 'Customer', name: 'CUST-1' })
  await assert.rejects(searchLinkChoices(types, async () => { throw Error('Offline') }), /Offline/)
  assert.deepEqual(await searchLinkChoices([], async () => []), [])
})
