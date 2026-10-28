import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { railGroups } from '../src/services/navigation.js'

const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/SiteApp.vue', import.meta.url), 'utf8')
const rail = css.slice(css.indexOf('/* Desktop rail:'))
const block = (source, selector) => source.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}'))?.[1] || ''
const page = name => ({ name, label: name })
const names = groups => groups.map(group => [group.name, group.pages.map(item => item.name)])

test('the desktop rail is 72px wide and every item shows its label and a tooltip', () => {
  assert.match(block(rail, '.v1-shell.relay-shell'), /grid-template-columns:72px minmax\(0,1fr\)/)
  assert.match(app, /class="rail-label">\{\{ group\.name \}\}/)
  assert.equal((app.match(/:title="group\.name"/g) || []).length, 2)
  assert.ok(!/rail-label[^{]*\{[^}]*(opacity:0|display:none)/.test(rail), 'labels are never hidden')
})

test('rail groups keep the order Chats, Tickets, Contacts, WhatsApp, Automation and Settings at the bottom', () => {
  const all = ['Messages', 'Tickets', 'Contacts', 'WhatsApp', 'Business events', 'Flows', 'Skills', 'Settings', 'Teams', 'Activity'].map(page)
  const groups = railGroups(all)
  assert.deepEqual(names(groups), [['Chats', ['Messages']], ['Tickets', ['Tickets']], ['Contacts', ['Contacts']], ['WhatsApp', ['WhatsApp']],
    ['Automation', ['Business events', 'Flows', 'Skills']], ['Settings', ['Settings', 'Teams', 'Activity']]])
  assert.deepEqual(groups.filter(group => group.bottom).map(group => group.name), ['Settings'])
  assert.equal(groups.find(group => group.name === 'Tickets').icon, 'ticket')
})

test('a group without allowed pages is hidden and a group opens its first allowed page', () => {
  assert.deepEqual(names(railGroups(['Messages', 'Tickets', 'Contacts', 'Teams'].map(page))),
    [['Chats', ['Messages']], ['Tickets', ['Tickets']], ['Contacts', ['Contacts']], ['Settings', ['Teams']]])
  assert.match(app, /@click="view = group\.pages\[0\]\.name"/)
  assert.match(app, /v-if="currentGroup\?\.pages\.length > 1" class="v1-tabs workspace-subtabs"/)
})

test('the Chats badge and the inbox Unread tab read one count', () => {
  const counts = readFileSync(new URL('../src/composables/useQueueCounts.js', import.meta.url), 'utf8')
  const inbox = readFileSync(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
  assert.match(counts, /useQueueCounts\(medium, INBOX_ROWS\)/)
  assert.match(inbox, /\.\.\.params\.value, \.\.\.INBOX_ROWS/)
  assert.match(app, /useUnreadChats\(/)
  assert.match(app, /:badge="inboxBadge"/)
})

test('the phone layout keeps the bottom tab bar and hides the rail', () => {
  const mobile = readFileSync(new URL('../src/mobile.css', import.meta.url), 'utf8')
  assert.match(mobile, /\.v1-shell\.relay-shell>\.app-nav,\.v1-shell\.relay-shell>\.relay-nav-backdrop\{display:none!important\}/)
  assert.match(app, /<MobileTabBar v-if="isMobile && ready"/)
})
