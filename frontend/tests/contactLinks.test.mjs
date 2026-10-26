import test from 'node:test'
import assert from 'node:assert/strict'
import { businessTypeOptions, isPrimaryLink, linksWith, linksWithout, primaryRequest, recordIcon } from '../src/services/contactLinks.js'

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
