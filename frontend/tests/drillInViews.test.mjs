import { useLoadMore } from '../src/composables/useLoadMore.js'
import { useDebouncedSearch } from '../src/composables/useDebouncedSearch.js'
import test from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { computed, effectScope, ref, watch } from 'vue'
import { closeRoute, openRoute } from '../src/useViewRoute.js'
import { browser } from './browserHistory.js'
import { hasManyNumbers, numberName, whatsappNumbers } from '../src/services/whatsappNumbers.js'
import { inputTime, siteTime } from '../src/services/campaignAudience.js'
import { emptySettings, emptyTicketFilters, pickerOptions, statusLook } from '../src/services/ticketSettings.js'

const settle = () => new Promise(resolve => setTimeout(resolve, 0))

// Runs a component's <script setup> with the given globals and returns the named bindings after mount.
async function component(t, file, values, bindings) {
  const source = await readFile(new URL('../src/components/' + file, import.meta.url), 'utf8')
  const script = source.match(/<script setup>([\s\S]*?)<\/script>/)[1].replace(/^import[\s\S]*?from .*\n/gm, '')
  const mounted = [], scope = effectScope()
  const globals = { useLoadMore, useDebouncedSearch, computed, ref, watch, openRoute, closeRoute, onMounted: callback => mounted.push(callback), onBeforeUnmount() {},
    useRealtimeRefresh() {}, ...values }
  const make = new Function(...Object.keys(globals), `${script}\nreturn { ${bindings.join(', ')} };`)
  const state = scope.run(() => make(...Object.values(globals)))
  t.after(() => scope.stop())
  for (const callback of mounted) await callback()
  await settle()
  return state
}

function tickets(t, calls = []) {
  const api = async (method, values) => {
    calls.push([method, values])
    if (method === 'tickets.directory') return { items: [{ name: 'T-1' }, { name: 'T-2' }] }
    if (values.name === 'T-MISSING') throw Error('Ticket not found')
    if (method === 'tickets.read') return { name: values.name, status: 'Open' }
    return { items: [], next: null }
  }
  return component(t, 'TicketsWorkspace.vue', { coreApi: api, inject: () => ref({ ai: true }), pickerOptions, statusLook, emptyTicketFilters,
    useTicketSettings: () => ({ settings: ref(emptySettings()), load: async () => {} }) }, ['selected', 'select', 'close', 'error', 'page', 'setFilter'])
}

test('a ticket opened from the list adds one entry, switching replaces it and Back shows the list', async t => {
  const page = browser(t, '#/tickets')
  const state = await tickets(t)
  state.select(state.page.value.items[0])
  state.select(state.page.value.items[1])
  assert.deepEqual(page.entries(), ['#/tickets', '#/tickets?ticket=T-2'])
  page.history.back()
  assert.equal(state.selected.value, null)
})

test('status tabs and Assigned to me filter the ticket list', async t => {
  browser(t, '#/tickets')
  const calls = []
  const state = await tickets(t, calls)
  state.setFilter({ ticket_status: 'Closed', mine: 1 })
  await new Promise(resolve => setTimeout(resolve, 350))
  assert.deepEqual(calls.filter(([method]) => method === 'tickets.directory').at(-1)[1], { query: '', ticket_status: 'Closed', mine: 1 })
})

test('Dismiss returns to the ticket list entry', async t => {
  const page = browser(t, '#/tickets')
  const state = await tickets(t)
  state.select(state.page.value.items[0])
  state.close()
  assert.deepEqual(page.entries(), ['#/tickets'])
  assert.equal(state.selected.value, null)
})

test('a ticket link opens its detail and a missing ticket falls back to the list', async t => {
  browser(t, '#/tickets?ticket=T-2')
  assert.equal((await tickets(t)).selected.value.name, 'T-2')
  const page = browser(t, '#/tickets?ticket=T-MISSING')
  const state = await tickets(t)
  assert.equal(state.selected.value, null)
  assert.equal(state.error.value, 'Ticket not found')
  assert.equal(page.location.hash, '#/tickets')
})

function campaigns(t, capabilities = {}, calls = []) {
  const campaign = ref(null), error = ref('')
  const workspace = {
    busy: ref(false), error, items: ref([]), campaign, sheet: ref(null), templates: ref([]), filter: ref(''), replyWindow: ref(null),
    refresh() {}, loadTemplates(channel) { calls.push(['templates', channel]) },
    async create(values) { calls.push(['create', values]); campaign.value = { name: 'C-NEW', counts: {} }; return campaign.value },
    async open(name) { if (name === 'C-MISSING') error.value = 'Campaign not found'; else campaign.value = { name, counts: {} } },
  }
  const values = { inject: () => ref(capabilities), useCampaigns: () => workspace, channelFeature: () => false, messageTypes: () => [],
    placeholders: () => [], missingMapping: () => [], hasManyNumbers, numberName, whatsappNumbers, campaignMessage: () => ({}),
    inputTime, siteTime }
  return component(t, 'CampaignsWorkspace.vue', values, ['campaign', 'creating', 'openCampaign', 'startCreate', 'back', 'ready', 'title',
    'template', 'number', 'chooseNumber', 'create'])
}

test('a campaign on a site with two numbers names its number and lists that number\'s templates', async t => {
  browser(t, '#/whatsapp?tab=campaigns')
  const calls = []
  const state = await campaigns(t, { whatsapp_numbers: [{ name: 'WA-1', label: 'Sales line' }, { name: 'WA-2', label: 'Support line' }] }, calls)
  state.startCreate()
  assert.deepEqual(calls, [])
  state.title.value = 'Winter launch'; state.template.value = 'offer|en'
  assert.equal(Boolean(state.ready.value), false)
  state.chooseNumber('WA-2')
  assert.equal(state.template.value, '')
  state.template.value = 'offer|en'
  assert.equal(Boolean(state.ready.value), true)
  await state.create()
  assert.deepEqual(calls, [['templates', 'WA-2'], ['create', { title: 'Winter launch', template_name: 'offer', language: 'en', channel: 'WA-2' }]])
})

test('a one-number site creates a campaign as before', async t => {
  browser(t, '#/whatsapp?tab=campaigns')
  const calls = []
  const state = await campaigns(t, { whatsapp_numbers: [{ name: 'WA-1', label: 'Sales line' }] }, calls)
  state.startCreate()
  state.title.value = 'Winter launch'; state.template.value = 'offer|en'
  assert.equal(Boolean(state.ready.value), true)
  await state.create()
  assert.deepEqual(calls, [['templates', undefined], ['create', { title: 'Winter launch', template_name: 'offer', language: 'en' }]])
})

test('a campaign opened from the list adds one entry and Back shows the list', async t => {
  const page = browser(t, '#/whatsapp?tab=campaigns')
  const state = await campaigns(t)
  state.openCampaign('C-1')
  await settle()
  assert.equal(page.location.hash, '#/whatsapp?tab=campaigns&campaign=C-1')
  page.history.back()
  assert.equal(state.campaign.value, null)
  state.startCreate()
  state.back()
  assert.deepEqual(page.entries(), ['#/whatsapp?tab=campaigns'])
  assert.equal(state.creating.value, false)
})

test('a campaign link opens it and a missing campaign falls back to the list', async t => {
  browser(t, '#/whatsapp?tab=campaigns&campaign=C-2')
  assert.equal((await campaigns(t)).campaign.value.name, 'C-2')
  const page = browser(t, '#/whatsapp?tab=campaigns&campaign=C-MISSING')
  const state = await campaigns(t)
  assert.equal(state.campaign.value, null)
  assert.equal(page.location.hash, '#/whatsapp?tab=campaigns')
})

function teams(t) {
  const api = async method => {
    if (method === 'api.business_types') return ['Customer']
    if (method === 'business_groups.directory') return { field: 'territory', items: [{ value: 'North', label: 'North' }, { value: 'South', label: 'South' }] }
    return { items: [], next: null }
  }
  return component(t, 'TeamsWorkspace.vue', { coreApi: api }, ['selected', 'groups', 'choose', 'clearSelection'])
}

test('a business group opened from the list adds one entry, switching replaces it and Back shows the groups', async t => {
  const page = browser(t, '#/teams')
  const state = await teams(t)
  state.choose(state.groups.value[0])
  state.choose(state.groups.value[1])
  assert.deepEqual(page.entries(), ['#/teams', '#/teams?business_doctype=Customer&group=South'])
  page.history.back()
  assert.equal(state.selected.value, null)
})

test('the mobile back button returns to the group list entry and a missing group link falls back', async t => {
  const page = browser(t, '#/teams')
  const state = await teams(t)
  state.choose(state.groups.value[0])
  state.clearSelection()
  assert.deepEqual(page.entries(), ['#/teams'])
  const missing = browser(t, '#/teams?business_doctype=Customer&group=West')
  assert.equal((await teams(t)).selected.value, null)
  assert.equal(missing.location.hash, '#/teams')
})
