import test from 'node:test'
import assert from 'node:assert/strict'
import { movedRoute, routeTab } from '../src/useViewRoute.js'

test('old screen hashes redirect to their new section tabs', () => {
  assert.equal(movedRoute('#/templates'), '/whatsapp')
  assert.equal(movedRoute('#/campaigns'), '/whatsapp?tab=campaigns')
  assert.equal(movedRoute('#/campaigns?x=1'), '/whatsapp?tab=campaigns')
  assert.equal(movedRoute('#/incoming'), '/contacts?tab=unlinked')
})

test('current hashes are not redirected', () => {
  for (const hash of ['#/whatsapp', '#/whatsapp?tab=campaigns', '#/messages', '', '#/']) assert.equal(movedRoute(hash), null)
})

test('redirect targets open the matching WhatsApp tab and template links keep the default tab', () => {
  assert.equal(routeTab('#' + movedRoute('#/campaigns'), 'templates'), 'campaigns')
  assert.equal(routeTab('#' + movedRoute('#/templates'), 'templates'), 'templates')
  assert.equal(routeTab('#/whatsapp?template=123&edit=1', 'templates'), 'templates')
  assert.equal(routeTab('#/whatsapp?tab=account', 'templates'), 'account')
})
