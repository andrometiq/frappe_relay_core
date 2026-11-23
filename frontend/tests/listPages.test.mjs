import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ROLE_COLUMNS, ROLE_MATRIX, accessChanges, filterAccessRows, labelList, roleBadges, seesAllTypes } from '../src/services/accessRoles.js'
import { filterTemplates, templateCounts, templateStatusGroup } from '../src/services/templateList.js'
import { emptyTicketFilters, ticketViewFilters, ticketViewKey, ticketViews } from '../src/services/ticketSettings.js'
import { settingsRoute, settingsSections, settingsTab } from '../src/services/settingsSections.js'

const source = path => readFileSync(new URL('../src/' + path, import.meta.url), 'utf8')

const people = [
  { user: 'a@x', full_name: 'Anitha K', role: 'User', team_user: true, teams: ['Sales'], business_types: ['Customer'] },
  { user: 'p@x', full_name: 'Prakash', role: 'User', team_user: false, teams: ['Sales', 'Dispatch'], business_types: [] },
  { user: 'v@x', full_name: 'Vijay R', role: 'Manager', team_user: false, teams: [], business_types: [] },
  { user: 's@x', full_name: 'Sys', role: 'System Manager', team_user: false, teams: [], business_types: [] },
]

test('access rows filter by name, role, Team User, team and business type', () => {
  const names = filters => filterAccessRows(people, filters).map(row => row.full_name)
  assert.deepEqual(names({ query: 'prak' }), ['Prakash'])
  assert.deepEqual(names({ query: 'V@X' }), ['Vijay R'])
  assert.deepEqual(names({ role: 'Team User' }), ['Anitha K'])
  assert.deepEqual(names({ role: 'Manager' }), ['Vijay R'])
  assert.deepEqual(names({ team: 'Dispatch' }), ['Prakash'])
  assert.deepEqual(names({ businessType: 'Customer' }), ['Anitha K', 'Vijay R', 'Sys'], 'Managers see every type')
})

test('only changed access parts are sent, so a locked role is never resent', () => {
  const saved = people[1]
  assert.deepEqual(accessChanges(saved, { ...saved, teams: ['Dispatch', 'Sales'] }), {}, 'Order does not matter')
  assert.deepEqual(accessChanges(saved, { ...saved, teams: ['Sales'], business_types: ['Customer'] }), { teams: ['Sales'], business_types: ['Customer'] })
  assert.deepEqual(accessChanges(saved, { ...saved, role: 'Manager', team_user: true }), { role: 'Manager', team_user: 1 })
  assert.deepEqual(accessChanges(people[0], { ...people[0], team_user: false }), { team_user: 0 })
})

test('role badges, labels and the role matrix describe only existing roles', () => {
  assert.deepEqual(roleBadges(people[0]).map(badge => badge.label), ['User', 'Team User'])
  assert.deepEqual(roleBadges({ role: '', team_user: false }).map(badge => badge.label), ['No access'])
  assert.equal(seesAllTypes(people[2]), true)
  assert.equal(seesAllTypes(people[0]), false)
  assert.equal(labelList(['Sales', 'Ghost'], [{ value: 'Sales', label: 'Sales team' }]), 'Sales team, Ghost')
  assert.deepEqual(ROLE_COLUMNS, ['User', 'Team User', 'Manager'])
  assert.ok(ROLE_MATRIX.every(row => ROLE_COLUMNS.every(role => role in row)))
  assert.doesNotMatch(JSON.stringify(ROLE_MATRIX), /priority|overdue|export|away|auto-assign|read rate/i)
})

const templates = [
  { id: '1', name: 'order_ready', category: 'UTILITY', status: 'APPROVED', language: 'en_US' },
  { id: '2', name: 'festival', category: 'MARKETING', status: 'PENDING', language: 'ta' },
  { id: '3', name: 'appeal', category: 'MARKETING', status: 'IN_APPEAL', language: 'en_US' },
  { id: '4', name: 'login_otp', category: 'AUTHENTICATION', status: 'REJECTED', language: 'en_US' },
  { id: '5', name: 'old', category: 'UTILITY', status: 'PAUSED', language: 'en_US' },
  { id: '6', name: 'odd', category: '', status: 'PENDING_DELETION', language: 'en_US' },
]

test('template statuses fold into sidebar groups with counts per group and category', () => {
  assert.equal(templateStatusGroup('approved'), 'APPROVED')
  assert.equal(templateStatusGroup('IN_APPEAL'), 'REVIEW')
  assert.equal(templateStatusGroup('DISABLED'), 'PAUSED')
  assert.equal(templateStatusGroup('PENDING_DELETION'), 'OTHER')
  const counts = templateCounts(templates)
  assert.deepEqual([counts.ALL, counts.APPROVED, counts.REVIEW, counts.REJECTED, counts.PAUSED, counts.OTHER], [6, 1, 2, 1, 1, 1])
  assert.deepEqual(counts.categories, { UTILITY: 2, MARKETING: 2, AUTHENTICATION: 1 })
  assert.deepEqual(filterTemplates(templates, { group: 'REVIEW' }).map(row => row.id), ['2', '3'])
  assert.deepEqual(filterTemplates(templates, { group: 'REVIEW', category: 'MARKETING', language: 'ta' }).map(row => row.id), ['2'])
})

const settings = { statuses: [{ name: 'Open', state: 'Open' }, { name: 'Waiting', state: 'Open' }, { name: 'Done', state: 'Closed' }] }
const dashboard = {
  totals: { open: 5, assigned: 3, unassigned: 2, resolved_today: 1 },
  statuses: [{ ticket_status: 'Open', tickets: 3 }, { ticket_status: 'Waiting', tickets: 2 }, { ticket_status: 'Done', tickets: 7 }],
  assignees: [{ assigned_to: 'me@x', tickets: 2 }, { assigned_to: 'other@x', tickets: 1 }, { assigned_to: null, tickets: 2 }],
  business_types: [{ business_doctype: 'Customer', tickets: 4 }, { business_doctype: null, tickets: 1 }],
}

test('ticket views take their counts from the dashboard numbers', () => {
  const sections = ticketViews(dashboard, settings, 'me@x', [{ value: 'Customer', label: 'Customer' }, { value: 'Supplier', label: 'Supplier' }])
  const counts = Object.fromEntries(sections.flatMap(section => section.items).map(item => [item.key, item.count]))
  assert.deepEqual(counts, { all: 12, open: 5, mine: 2, unassigned: 2, resolved: 7, 'type:Customer': 4, 'type:Supplier': 0 })
  assert.equal(sections[1].title, 'Business type')
  const unknown = ticketViews(null, settings, 'me@x', [])
  assert.equal(unknown.length, 1, 'No business type section without types')
  assert.ok(unknown[0].items.every(item => item.count === null), 'Counts stay unknown until the dashboard loads')
})

test('a view matches the list filters, keeps the search and ignores the status pick', () => {
  const sections = ticketViews(dashboard, settings, 'me@x', [{ value: 'Customer', label: 'Customer' }])
  const items = Object.fromEntries(sections.flatMap(section => section.items).map(item => [item.key, item]))
  assert.equal(ticketViewKey(sections, emptyTicketFilters()), 'all')
  const unassigned = ticketViewFilters(items.unassigned, { ...emptyTicketFilters(), query: 'parcel', mine: 1 })
  assert.deepEqual(unassigned, { query: 'parcel', ticket_status: '', mine: 0, state: 'Open', assigned_to: '' })
  assert.equal(ticketViewKey(sections, unassigned), 'unassigned')
  assert.equal(ticketViewKey(sections, { ...unassigned, ticket_status: 'Waiting' }), 'unassigned')
  assert.equal(ticketViewKey(sections, { ...emptyTicketFilters(), state: 'Open', mine: '1' }), 'mine')
  assert.equal(ticketViewKey(sections, ticketViewFilters(items['type:Customer'], emptyTicketFilters())), 'type:Customer')
  assert.equal(ticketViewKey(sections, { ...emptyTicketFilters(), assigned_to: 'a@x' }), '', 'A dashboard filter is no view')
})

test('settings sections follow the person and the enabled channels', () => {
  const keys = capabilities => settingsSections(capabilities).flatMap(section => section.items.map(item => item.key))
  const manager = { manage: true, configure: false, enabled_channels: ['WhatsApp', 'Email'] }
  assert.deepEqual(keys(manager), ['overview', 'whatsapp', 'email', 'access', 'business-types', 'replies', 'tickets', 'features', 'hub'])
  assert.ok(keys({ ...manager, configure: true }).includes('billing'))
  assert.deepEqual(keys({ manage: false, enabled_channels: ['WhatsApp'] }), ['access'], 'Everyone else sees only Access')
  assert.equal(settingsTab(settingsSections(manager), 'hub'), 'hub')
  assert.equal(settingsTab(settingsSections(manager), 'billing'), 'overview', 'A tab the person may not open falls back')
  assert.deepEqual(['access', 'overview', 'hub'].map(settingsRoute), ['#/teams', '#/settings', '#/settings?tab=hub'])
})

test('long names shrink with an ellipsis, Desk links are touch targets and contact endpoints stay linked', () => {
  const css = source('pages.css')
  assert.match(css, /\.page-person>span\{min-width:0;overflow:hidden\}/)
  assert.match(css, /\.page-person>span>:is\(b,small,span\)\{overflow:hidden;text-overflow:ellipsis\}/)
  assert.match(source('components/AccessWorkspace.vue'), /:title="row\.full_name"[\s\S]*:title="row\.user"/)
  assert.match(css, /\.desk-link\{display:inline-flex;align-items:center;min-height:40px\}/)
  assert.equal((source('components/SavedRepliesWorkspace.vue').match(/class="desk-link /g) || []).length, 2)
  assert.match(source('components/SiteSettings.vue'), /label: 'Contact numbers and addresses'[^}]*href: '\/desk\/relay-contact-endpoint'/)
  const dashboard = source('components/tickets/TicketDashboard.vue')
  assert.doesNotMatch(dashboard, /coreApi|useRealtimeRefresh/, 'The dashboard reads counts from the page')
})

test('list pages use the shared sidebar and side panel, and tables stack into cards on phones', () => {
  for (const file of ['components/whatsapp/WhatsAppTemplates.vue', 'components/TicketsWorkspace.vue', 'components/settings/SettingsLayout.vue']) {
    assert.match(source(file), /<PageSidebar /, file)
  }
  assert.match(source('components/AccessWorkspace.vue'), /<SidePanel /)
  assert.match(source('components/whatsapp/TemplateEditor.vue'), /<SidePanel wide /)
  const css = source('pages.css')
  assert.match(css, /@media\(max-width:768px\)\{[\s\S]*\.page-table thead\{display:none\}/)
  assert.match(css, /\.side-panel\.is-sheet\{position:fixed;inset:0/)
  for (const file of ['components/TicketsWorkspace.vue', 'components/AccessWorkspace.vue', 'components/SiteSettings.vue', 'components/whatsapp/WhatsAppTemplates.vue']) {
    assert.doesNotMatch(source(file), /setInterval|setTimeout\(\s*load/, file + ' does not poll')
  }
})
