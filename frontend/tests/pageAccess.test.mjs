import test from 'node:test'
import assert from 'node:assert/strict'
import { deniedReason } from '../src/services/pageAccess.js'

const manager = { manage: true, teams: false, teams_enabled: false, ai: false, skills: false, configure: false, flows: true, business_events: true, billing: true }

test('a closed page names the role it needs or the switch that is off', () => {
  assert.match(deniedReason({ name: 'Settings', configure: true }, manager), /System Manager role/)
  assert.match(deniedReason({ name: 'Teams', teams: true }, manager), /^Teams are turned off .* Settings, under Features\.$/)
  assert.match(deniedReason({ name: 'Teams', teams: true }, { manage: false }), /Relay Communication Manager role/)
  assert.match(deniedReason({ name: 'Skills', ai: true, skills: true }, manager), /^AI features are turned off/)
  assert.match(deniedReason({ name: 'Flows', flows: true }, {}), /Relay Communication Manager role/)
  assert.match(deniedReason({ name: 'WhatsApp', channel: 'WhatsApp' }, manager), /WhatsApp is turned off/)
  assert.equal(deniedReason({ name: 'Tickets' }, manager), '')
})
