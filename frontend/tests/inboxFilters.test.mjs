import test from 'node:test'
import assert from 'node:assert/strict'
import { EMPTY_FILTERS, NO_RECORD, TABS, channelOptions, filterChips, filterParams, loadFilters, saveFilters, storageKey, withoutFilter, withoutFilters } from '../src/services/inboxFilters.js'

const CHANNELS = [
  { name: 'WA-1', label: 'Sales line', address: '+91 1', medium: 'WhatsApp' },
  { name: 'WA-2', label: 'Support line', address: '+91 2', medium: 'WhatsApp' },
  { name: 'TG-1', label: 'Bot', address: '123', medium: 'Telegram' },
]
const memory = () => { const store = new Map(); return { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), store } }

test('the inbox has All, Unread and Not linked tabs, and a saved Read tab falls back to All', () => {
  assert.deepEqual(TABS.map(([value, label]) => [value, label]), [['all', 'All'], ['unread', 'Unread'], ['unlinked', 'Not linked']])
  const storage = memory()
  storage.setItem(storageKey('ann@x'), JSON.stringify({ tab: 'read' }))
  assert.equal(loadFilters(storage, 'ann@x').tab, 'all')
})

test('filters persist per user and survive a blocked or damaged store', () => {
  const storage = memory()
  const filters = { tab: 'unlinked', channels: ['WA-2'], businessType: 'Customer', businessName: 'CUST-1', businessLabel: 'Acme' }
  saveFilters(storage, 'ann@x', filters)
  assert.deepEqual(loadFilters(storage, 'ann@x'), filters)
  assert.deepEqual(loadFilters(storage, 'bob@x'), EMPTY_FILTERS, 'Another user starts with no filters')
  storage.setItem(storageKey('bob@x'), '{not json')
  assert.deepEqual(loadFilters(storage, 'bob@x'), EMPTY_FILTERS)
  storage.setItem(storageKey('bob@x'), JSON.stringify({ tab: 'mine', channels: 'WA-1', businessType: NO_RECORD, businessName: 'X' }))
  assert.deepEqual(loadFilters(storage, 'bob@x'), { ...EMPTY_FILTERS, businessType: NO_RECORD }, 'Old tabs and bad values fall back')
  const blocked = { getItem() { throw Error('SecurityError') }, setItem() { throw Error('QuotaExceeded') } }
  assert.deepEqual(loadFilters(blocked, 'ann@x'), EMPTY_FILTERS)
  assert.doesNotThrow(() => saveFilters(blocked, 'ann@x', filters))
  assert.doesNotThrow(() => saveFilters(undefined, 'ann@x', filters))
})

test('channel choices follow the medium and only offered channels are sent', () => {
  const capabilities = { inbox_channels: CHANNELS }
  assert.deepEqual(channelOptions(capabilities, 'WhatsApp').map(row => row.name), ['WA-1', 'WA-2'])
  assert.equal(channelOptions(capabilities, 'all').length, 3)
  assert.deepEqual(channelOptions({}, 'all'), [])
  const filters = { ...EMPTY_FILTERS, channels: ['TG-1', 'WA-2'] }
  assert.deepEqual(filterParams(filters, channelOptions(capabilities, 'WhatsApp')), { channels: '["WA-2"]' })
  assert.deepEqual(filterParams(filters, channelOptions(capabilities, 'Email')), {}, 'No offered channel means every channel')
})

test('a business type, one record or no record become request parameters', () => {
  assert.deepEqual(filterParams({ ...EMPTY_FILTERS, businessType: 'Customer' }, []), { business_type: 'Customer' })
  assert.deepEqual(filterParams({ ...EMPTY_FILTERS, businessType: 'Customer', businessName: 'CUST-1' }, []), { business_type: 'Customer', business_name: 'CUST-1' })
  assert.deepEqual(filterParams({ ...EMPTY_FILTERS, businessType: NO_RECORD, businessName: 'stale' }, []), { business_type: NO_RECORD })
  assert.deepEqual(filterParams({ ...EMPTY_FILTERS, businessName: 'stale' }, []), {})
})

test('active filters show as removable chips', () => {
  const filters = { tab: 'unread', channels: ['WA-1', 'WA-2'], businessType: 'Customer', businessName: 'CUST-1', businessLabel: 'Acme' }
  assert.deepEqual(filterChips(filters, CHANNELS), [{ key: 'channels', label: 'Sales line, Support line' }, { key: 'business', label: 'Customer: Acme' }])
  assert.deepEqual(filterChips({ ...EMPTY_FILTERS, businessType: 'Supplier' }, CHANNELS), [{ key: 'business', label: 'Any Supplier' }])
  assert.deepEqual(filterChips({ ...EMPTY_FILTERS, businessType: NO_RECORD }, CHANNELS), [{ key: 'business', label: 'No business record' }])
  assert.deepEqual(filterChips(EMPTY_FILTERS, CHANNELS), [])
  assert.deepEqual(withoutFilter(filters, 'channels'), { ...filters, channels: [] })
  assert.deepEqual(withoutFilter(filters, 'business'), { ...filters, businessType: '', businessName: '', businessLabel: '' })
  assert.deepEqual(withoutFilters(filters), { ...EMPTY_FILTERS, tab: 'unread' })
})
