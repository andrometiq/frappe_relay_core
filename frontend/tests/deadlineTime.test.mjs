import test from 'node:test'
import assert from 'node:assert/strict'
import { deadlineTime } from '../src/components/relativeTime.js'

test('deadline uses an offset-aware instant and a local date with relative text', () => {
  const expires = '2026-10-30T14:00:00+05:30', instant = new Date(expires).getTime()
  const result = deadlineTime(expires, instant - 120000)
  assert.ok(result.includes(new Date(expires).toLocaleString([], {year:'numeric', month:'short', day:'numeric', hour:'2-digit', minute:'2-digit', timeZoneName:'short'})))
  assert.match(result, /in 2 minutes$/)
  assert.match(deadlineTime(expires, instant + 60000), /1 minute ago$/)
  assert.match(deadlineTime(expires, instant), /now$/)
  assert.equal(deadlineTime('invalid'), '')
  assert.equal(deadlineTime(null), '')
})
