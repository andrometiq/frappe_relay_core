import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

await import('vue') // Vue loads before the minimal browser stubs below.

// A browser that chose dark, with a profile still on the default System theme.
const stored = new Map([['theme', 'dark']])
globalThis.localStorage = { getItem: key => stored.get(key) ?? null, setItem: (key, value) => stored.set(key, String(value)) }
globalThis.window = globalThis
globalThis.matchMedia = () => ({ matches: false, addEventListener() {} })
globalThis.addEventListener = () => {}
globalThis.document = { documentElement: { dataset: {}, style: {} }, getElementById: () => null }
let profile = { user: 'agent@example.invalid', theme: 'System', density: 'Comfortable', user_image: 'https://photos.example.invalid/a.jpg', job_title: '' }
const requests = []
globalThis.fetch = async (url, options = {}) => {
  const method = url.split('/api/method/relay_core.')[1].split('?')[0]
  const body = options.body ? JSON.parse(options.body) : null
  requests.push({ method, body })
  if (method === 'user_profiles.update') profile = { ...profile, ...body }
  return { ok: true, status: 200, json: async () => ({ message: method === 'user_profiles.cards' ? { items: [] } : { ...profile } }) }
}
const { changedFields, loadMyProfile, loadStartPreferences, myProfile, profilesChanged, saveMyProfile } = await import('../src/services/userProfiles.js')
const html = document.documentElement

test('start keeps the browser theme while the profile theme is System', async () => {
  await loadStartPreferences()
  assert.equal(html.dataset.theme, 'dark')
  assert.equal(stored.get('theme'), 'dark')
  assert.equal(html.dataset.density, 'comfortable')
})

test('reading the profile and profile broadcasts never change the theme', async () => {
  await loadMyProfile()
  profilesChanged({ kind: 'user_profiles' })
  profilesChanged({ kind: 'reconnect' })
  assert.equal(html.dataset.theme, 'dark')
  assert.equal(stored.get('theme'), 'dark')
  assert.ok(!requests.some(request => request.method === 'user_profiles.update'))
})

test('only changed fields are sent, so an external photo is never resent', () => {
  const form = { ...myProfile.value, job_title: 'Sales coordinator' }
  assert.deepEqual(changedFields(form, myProfile.value), { job_title: 'Sales coordinator' })
})

test('an explicit save applies the saved theme and density', async () => {
  await saveMyProfile({ job_title: 'Sales' })
  assert.equal(html.dataset.theme, 'dark')
  await saveMyProfile({ theme: 'Light', density: 'Compact' })
  assert.equal(html.dataset.theme, 'light')
  assert.equal(html.dataset.density, 'compact')
})

test('the profile dialog restores the theme on Cancel, keeps the preview on Save and uploads the photo to the User record', () => {
  const dialog = readFileSync(new URL('../src/components/shell/ProfileDialog.vue', import.meta.url), 'utf8')
  assert.match(dialog, /shown = \{ theme: theme\.value, density: document\.documentElement\.dataset\.density \}/)
  assert.match(dialog, /function cancel\(\) \{\n  restore\(\)/)
  assert.match(dialog, /const values = changedFields\(form\.value, myProfile\.value\)/)
  assert.match(dialog, /doctype: 'User', docname: form\.value\.user, fieldname: 'user_image'/)
  assert.match(dialog, /shown = null\n    applyPreferences\(form\.value\)/, 'Save keeps the theme on screen even when it equals the saved one')
  assert.doesNotMatch(dialog, /restore\(values\)|loadStartPreferences/)
})

test('closing the profile with unsaved edits asks before discarding them', () => {
  const dialog = readFileSync(new URL('../src/components/shell/ProfileDialog.vue', import.meta.url), 'utf8')
  assert.match(dialog, /@update:model-value="value => value \|\| dismiss\(\)"/)
  assert.match(dialog, /if \(dirty\.value && !window\.confirm\('Discard your profile changes\?'\)\) return/)
  assert.match(dialog, /Object\.keys\(changedFields\(form\.value, myProfile\.value\)\)\.length > 0 \|\| clearAfter\.value !== null/)
})
