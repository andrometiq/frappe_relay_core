import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { activeRailGroup, railGroups } from '../src/services/navigation.js'

const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/SiteApp.vue', import.meta.url), 'utf8')
const rail = css.slice(css.indexOf('/* Desktop rail:'))
const block = (source, selector) => source.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}'))?.[1] || ''
const page = name => ({ name, label: name })
const names = groups => groups.map(group => [group.name, group.pages.map(item => item.name)])

test('the desktop rail is 56px of icons and every item has a tooltip and a spoken name', () => {
  assert.match(css, /\.v1-shell\.relay-shell\{grid-template-columns:56px auto minmax\(0,1fr\)/)
  assert.match(block(rail, '  .v1-shell.relay-shell>.relay-rail'), /width:56px/)
  assert.equal((app.match(/:title="group\.name"/g) || []).length, 2)
  assert.equal((app.match(/:aria-label="group\.name"/g) || []).length, 2)
})

test('rail groups keep the order Inbox, Tickets, Contacts, Templates, Campaigns, Automation, Reports and Settings at the bottom', () => {
  const all = ['Messages', 'Tickets', 'Contacts', 'WhatsApp', 'Business events', 'Flows', 'Skills', 'Knowledge', 'Persona', 'Events', 'Settings', 'Teams', 'Activity'].map(page)
  const groups = railGroups(all, [{ name: 'templates' }, { name: 'campaigns' }])
  assert.deepEqual(names(groups), [['Inbox', ['Messages']], ['Tickets', ['Tickets']], ['Contacts', ['Contacts']], ['Templates', ['WhatsApp']],
    ['Campaigns', ['WhatsApp']], ['Automation', ['Business events', 'Flows', 'Skills', 'Knowledge', 'Persona', 'Events']], ['Reports', ['Activity']], ['Settings', ['Settings', 'Teams']]])
  assert.deepEqual(groups.filter(group => group.bottom).map(group => group.name), ['Settings'])
  assert.equal(groups.find(group => group.name === 'Tickets').icon, 'ticket')
})

test('Campaigns needs its WhatsApp section and WhatsApp tabs light the matching rail group', () => {
  const groups = railGroups(['Messages', 'WhatsApp'].map(page), [{ name: 'templates' }])
  assert.deepEqual(names(groups), [['Inbox', ['Messages']], ['Templates', ['WhatsApp']]])
  const both = railGroups(['WhatsApp'].map(page), [{ name: 'templates' }, { name: 'campaigns' }])
  assert.equal(activeRailGroup(both, 'WhatsApp', 'campaigns').name, 'Campaigns')
  assert.equal(activeRailGroup(both, 'WhatsApp', 'forms').name, 'Templates')
  assert.equal(activeRailGroup(both, 'Messages', ''), undefined)
})

test('a group without allowed pages is hidden and a group opens its first allowed page', () => {
  assert.deepEqual(names(railGroups(['Messages', 'Tickets', 'Contacts', 'Teams'].map(page))),
    [['Inbox', ['Messages']], ['Tickets', ['Tickets']], ['Contacts', ['Contacts']], ['Settings', ['Teams']]])
  assert.match(app, /else view\.value = group\.pages\[0\]\.name/)
  assert.match(app, /currentGroup\.value\?\.pages\.length > 1 \? currentGroup\.value : null/)
  assert.match(app, /<SectionSidebar v-if="sidebarGroup"/)
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

test('the shell keeps no dead brand styles, the inbox pane is called Inbox and the profile dialog is 560px on desktop', () => {
  assert.doesNotMatch(css, /relay-brand|relay-logo/)
  const inbox = readFileSync(new URL('../src/components/messages/InboxDirectory.vue', import.meta.url), 'utf8')
  assert.match(inbox, /<h2>Inbox<\/h2>/)
  assert.match(block(rail, '  .relay-dialog.profile-dialog'), /width:min\(560px,100%\)/)
})
