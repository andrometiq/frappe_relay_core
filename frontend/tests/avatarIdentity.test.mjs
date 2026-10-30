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

test('every avatar tone is a colour, not grey', async () => {
  const { readFile } = await import('node:fs/promises')
  const css = await readFile(new URL('../src/style.css', import.meta.url), 'utf8')
  const tones = [...css.matchAll(/\.relay-tone-\d\{--relay-tone:#([0-9a-f]{6})\}/gi)].map(match => match[1].match(/../g).map(hex => parseInt(hex, 16)))
  assert.equal(tones.length, 7)
  for (const [red, green, blue] of tones) assert.ok(Math.max(red, green, blue) - Math.min(red, green, blue) >= 80, `#${[red, green, blue].map(value => value.toString(16).padStart(2, '0')).join('')} is too grey`)
})

test('contact chips and the new conversation contact list use the coloured avatar', async () => {
  const { readFile } = await import('node:fs/promises')
  const read = path => readFile(new URL('../src/components/' + path, import.meta.url), 'utf8')
  assert.match(await read('ConnectedMessages.vue'), /<Avatar class="contact-chip-avatar" size="sm" :label="contact\.label"/)
  assert.match(await read('messages/StartConversation.vue'), /<Avatar class="contact-chip-avatar" size="sm" :label="row\.label"/)
  assert.doesNotMatch(await read('messages/StartConversation.vue'), /slice\(0, 1\)\.toUpperCase\(\)/)
})
