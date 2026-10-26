import test from 'node:test'
import assert from 'node:assert/strict'
import { navAllowed } from '../src/services/navigation.js'
import { contactInfoRoute, isContactInfoRoute, splitMobileNav, unreadBadge } from '../src/services/mobileNav.js'
import { mediumChips } from '../src/services/enabledChannels.js'

const navigation = [
  { name: 'Messages' }, { name: 'Contacts' }, { name: 'Tickets' }, { name: 'Skills', configure: true },
  { name: 'WhatsApp', channel: 'WhatsApp' }, { name: 'Teams', teams: true }, { name: 'Settings', configure: true },
]
const names = items => items.map(item => item.name)

test('the tab bar shows Inbox, Tickets and WhatsApp and More keeps the other allowed pages', () => {
  const admin = { configure: true, teams: true, enabled_channels: ['WhatsApp'] }
  const { tabs, more } = splitMobileNav(navigation.filter(item => navAllowed(item, admin)))
  assert.deepEqual(names(tabs), ['Messages', 'Tickets', 'WhatsApp'])
  assert.deepEqual(names(more), ['Contacts', 'Skills', 'Teams', 'Settings'])
})

test('the tab bar uses the same gating as the sidebar', () => {
  const user = { configure: false, teams: false, enabled_channels: [] }
  const { tabs, more } = splitMobileNav(navigation.filter(item => navAllowed(item, user)))
  assert.deepEqual(names(tabs), ['Messages', 'Tickets'])
  assert.deepEqual(names(more), ['Contacts'])
})

test('the inbox badge counts unread chats and marks more pages', () => {
  assert.equal(unreadBadge({ items: [] }), '')
  assert.equal(unreadBadge(undefined), '')
  assert.equal(unreadBadge({ items: [{}, {}, {}] }), '3')
  assert.equal(unreadBadge({ items: [{}, {}], next: { after: 'x' } }), '2+')
})

test('contact info is the chat route with info=1', () => {
  const route = contactInfoRoute('#/messages?contact=RELAY-CON-1')
  assert.equal(route, '#/messages?contact=RELAY-CON-1&info=1')
  assert.equal(isContactInfoRoute(route), true)
  assert.equal(isContactInfoRoute('#/messages?contact=RELAY-CON-1'), false)
  assert.equal(contactInfoRoute(route), route)
})

test('channel chips keep switched-off providers visible but disabled', () => {
  assert.deepEqual(mediumChips({ enabled_channels: ['WhatsApp'] }), [
    { value: 'WhatsApp', label: 'WhatsApp', enabled: true },
    { value: 'Email', label: 'Email', enabled: false },
    { value: 'Telegram', label: 'Telegram', enabled: false },
  ])
  assert.deepEqual(mediumChips({ enabled_channels: ['WhatsApp', 'Telegram', 'Email'] }).map(chip => [chip.value, chip.enabled]),
    [['all', true], ['WhatsApp', true], ['Email', true], ['Telegram', true]])
})
