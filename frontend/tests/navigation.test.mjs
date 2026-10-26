import test from 'node:test'
import assert from 'node:assert/strict'
import { navAllowed } from '../src/services/navigation.js'

const settings = { name: 'Settings', configure: true }
const activity = { name: 'Activity', configure: true }
const teams = { name: 'Teams', teams: true }
const inbox = { name: 'Messages' }
const whatsapp = { name: 'WhatsApp', channel: 'WhatsApp' }
const channels = { enabled_channels: ['WhatsApp'] }

test('a WhatsApp User sees only the open pages', () => {
  const user = { ...channels, manage: false, configure: false, teams: false, billing: false }
  assert.deepEqual([inbox, whatsapp, teams, settings, activity].filter(item => navAllowed(item, user)), [inbox, whatsapp])
})

test('a WhatsApp Manager gets Teams but not Settings or Activity', () => {
  const manager = { ...channels, manage: true, configure: false, teams: true, billing: true }
  assert.equal(navAllowed(teams, manager), true)
  assert.equal(navAllowed(settings, manager), false)
  assert.equal(navAllowed(activity, manager), false)
  assert.equal(navAllowed({ name: 'Billing', billing: true }, manager), true)
})

test('a System Manager sees every page and disabled channels stay hidden', () => {
  const admin = { manage: true, configure: true, teams: true, billing: true, enabled_channels: [] }
  assert.equal([inbox, teams, settings, activity].every(item => navAllowed(item, admin)), true)
  assert.equal(navAllowed(whatsapp, admin), false)
  assert.equal(navAllowed(teams, undefined), false)
})
