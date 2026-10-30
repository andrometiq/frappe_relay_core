import test from 'node:test'
import assert from 'node:assert/strict'
import { avatarInitials, avatarTone } from '../src/ui/avatarIdentity.js'

test('a name always gets the same avatar tone', () => {
  assert.equal(avatarTone('Ravi Kumar'), avatarTone(' ravi kumar '))
  assert.match(avatarTone('Ravi Kumar'), /^relay-tone-[1-7]$/)
})

test('different names spread across the tones', () => {
  const tones = new Set(['Ravi Kumar', 'Meena Agencies', 'Arjun Textiles', 'Lakshmi N', 'Suresh Venkat', 'Green Hosiery', 'Owner Test', 'Priya Sharma'].map(avatarTone))
  assert.ok(tones.size >= 4)
})

test('initials use the first two words', () => {
  assert.equal(avatarInitials('ravi kumar sharma'), 'RK')
  assert.equal(avatarInitials('  '), '')
  assert.equal(avatarTone(''), avatarTone(undefined))
})

test('initials keep whole emoji', () => {
  assert.equal(avatarInitials('😀 Smile'), '😀S')
})

test('phone-only and non-letter labels use the person icon fallback', () => {
  for (const label of ['+91 85499 74206', '918549974206', '(800) 555-0123', '１２３', '☎', '', null]) {
    assert.equal(avatarInitials(label), '')
  }
  assert.equal(avatarInitials('தமிழ் பெயர்'), 'தப')
})
