import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
const tokens = theme => Object.fromEntries([...css.match(new RegExp(`\\[data-theme="${theme}"\\] \\{([^}]+)`))[1].matchAll(/(--[\w-]+):([^;]+);/g)].map(([, key, value]) => [key, value]))
const light = tokens('light')
const themes = { light, dark: { ...light, ...tokens('dark') } }
function colour(theme, value) {
  const resolved = value.startsWith('--') ? theme[value] : value
  if (resolved.startsWith('var(')) return colour(theme, resolved.slice(4, -1))
  assert.match(resolved, /^#[0-9a-f]{3,6}$/i)
  const hex = resolved.slice(1)
  return (hex.length === 3 ? [...hex].map(c => c + c).join('') : hex).match(/../g).map(c => parseInt(c, 16) / 255)
}
function contrast(theme, fg, bg) {
  const luminance = value => colour(theme, value).map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4).reduce((sum, c, i) => sum + c * [0.2126, 0.7152, 0.0722][i], 0)
  const values = [luminance(fg), luminance(bg)].sort((a, b) => b - a)
  return (values[0] + 0.05) / (values[1] + 0.05)
}
const pairs = [
  ['Internal note', '--relay-note-ink', '--relay-note-bg'],
  ['Open / in progress', '--ink-blue-3', '--surface-blue-1'],
  ['Closed / pending / legacy amber', '--ink-gray-6', '--surface-gray-2'],
  ['Success', '--ink-green-2', '--surface-green-1'],
  ['Warning', '--relay-warning-ink', '--relay-warning-bg'],
  ['Failure', '--ink-red-3', '--surface-red-1'],
  ['Solid blue', '--relay-accent-ink', '--relay-accent'],
  ['Solid green', '--relay-on-solid', '--relay-green'],
  ['Solid red', '--relay-on-solid', '--relay-red'],
  ['Solid note', '--relay-note-on-solid', '--relay-note-ink'],
  ['Modal placeholder', '--relay-ink-4', '--surface-modal'],
  ['Note placeholder', '--relay-note-ink', '--surface-white'],
  ['Incoming timestamp', '--relay-ink', '--relay-bubble-in'],
  ['Outgoing timestamp', '#fff', '--relay-bubble-out'],
  ['Unassigned / favourite', '--ink-gray-6', '--surface-white'],
]
for (const [name, theme] of Object.entries(themes)) {
  test(`${name} semantic text meets WCAG AA (4.5:1)`, t => {
    for (const [label, fg, bg] of pairs) {
      const ratio = contrast(theme, fg, bg)
      t.diagnostic(`${label}: ${ratio.toFixed(2)}:1`)
      assert.ok(ratio >= 4.5, `${label}: ${ratio}`)
    }
  })
  test(`${name} secondary text and placeholders remain legible on workspace surfaces`, () => {
    for (const bg of ['--relay-wall', '--relay-layer', '--relay-layer-strong', '--surface-white', '--surface-modal', '--surface-gray-1', '--surface-gray-2', '--surface-gray-3', '--surface-selected']) {
      assert.ok(contrast(theme, '--relay-ink-4', bg) >= 4.5, bg)
    }
  })
}
