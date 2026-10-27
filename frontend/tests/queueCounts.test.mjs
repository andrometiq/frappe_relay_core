import test from 'node:test'
import assert from 'node:assert/strict'
import { EMPTY_COUNTS, countLabel, queueCountParams, sharedQueueCounts } from '../src/services/queueCounts.js'

test('queue counts are exact below a thousand and hidden at zero', () => {
  assert.equal(countLabel(0), '')
  assert.equal(countLabel(undefined), '')
  assert.equal(countLabel(-2), '')
  assert.equal(countLabel(8), '8')
  assert.equal(countLabel(999), '999')
})

test('large queue counts stay short enough for a phone tab', () => {
  assert.equal(countLabel(1583), '1.6K')
  assert.equal(countLabel(12407), '12.4K')
})

test('counts follow the chosen channel and drop the all-channels choice', () => {
  assert.deepEqual(queueCountParams('Telegram'), { medium: 'Telegram' })
  assert.deepEqual(queueCountParams('all'), {})
  assert.deepEqual(queueCountParams(undefined), {})
})

test('inbox filters narrow the counts with or without a medium', () => {
  const filters = { channels: '["WA-2"]', business_type: 'Customer', business_name: 'CUST-1' }
  assert.deepEqual(queueCountParams('WhatsApp', filters), { medium: 'WhatsApp', ...filters })
  assert.deepEqual(queueCountParams('all', { business_type: 'none' }), { business_type: 'none' })
  assert.deepEqual(queueCountParams('WhatsApp', {}), { medium: 'WhatsApp' })
})

test('views with the same filters share one count; other filters get their own', async () => {
  const reads = []
  const acquire = sharedQueueCounts(async params => { reads.push(params); return {} }, () => () => {})
  const one = acquire('WhatsApp', { business_type: 'Customer' }), two = acquire('WhatsApp', { business_type: 'Customer' })
  acquire('WhatsApp', { business_type: 'Supplier' })
  assert.equal(one.counts, two.counts)
  assert.deepEqual(reads, [{ medium: 'WhatsApp', business_type: 'Customer' }, { medium: 'WhatsApp', business_type: 'Supplier' }])
})

test('views of one channel share a single count read and live refresh', async () => {
  const reads = [], refreshers = [], stopped = []
  const acquire = sharedQueueCounts(async params => { reads.push(params); return { unread: reads.length } },
    load => { refreshers.push(load); return () => stopped.push(load) })
  const badge = acquire('WhatsApp'), tabs = acquire('WhatsApp'), all = acquire('all')
  await Promise.resolve()
  assert.deepEqual(reads, [{ medium: 'WhatsApp' }, {}])
  assert.equal(refreshers.length, 2)
  assert.equal(badge.counts, tabs.counts)
  assert.equal(badge.counts.value.unread, 1)
  await refreshers[0]()
  assert.equal(tabs.counts.value.unread, 3)
  badge.release(); badge.release()
  assert.equal(stopped.length, 0)
  tabs.release()
  assert.deepEqual(stopped, [refreshers[0]])
  acquire('WhatsApp')
  assert.equal(reads.length, 4)
  all.release()
})

test('a failed count read shows empty counts instead of stale ones', async () => {
  let fail = false
  let refresh
  const acquire = sharedQueueCounts(async () => { if (fail) throw Error('offline'); return { unread: 5 } }, load => { refresh = load; return () => {} })
  const lease = acquire('WhatsApp')
  await Promise.resolve(); await Promise.resolve()
  assert.equal(lease.counts.value.unread, 5)
  fail = true
  await refresh()
  assert.deepEqual(lease.counts.value, { ...EMPTY_COUNTS })
})
