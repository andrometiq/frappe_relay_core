import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const css = readFileSync(new URL('../src/style.css', import.meta.url), 'utf8')
const app = readFileSync(new URL('../src/SiteApp.vue', import.meta.url), 'utf8')
const rail = css.slice(css.indexOf('/* Desktop sidebar: an icon rail'))
const block = (source, selector) => source.match(new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '\\{([^}]*)\\}'))?.[1] || ''

test('the desktop sidebar is a 56px rail that overlays the content when it expands', () => {
  assert.ok(rail.startsWith('/* Desktop sidebar'), 'rail rules exist')
  assert.match(rail, /@media\(min-width:769px\)/)
  assert.match(block(rail, '.v1-shell.relay-shell'), /grid-template-columns:56px minmax\(0,1fr\)/)
  assert.match(block(rail, '.v1-shell.relay-shell>.app-nav'), /position:relative;z-index:30;width:56px/)
  assert.match(block(rail, '.v1-shell.relay-shell>.app-nav:is(:hover,:has(:focus-visible))'), /width:232px/)
})

test('hover and keyboard focus expand the rail; a mouse click alone does not keep it open', () => {
  assert.ok(rail.includes(':is(:hover,:has(:focus-visible))'))
  assert.ok(!/:focus-within/.test(rail))
})

test('the animation is short and switched off for reduced motion', () => {
  const durations = [...rail.matchAll(/(\d+)ms/g)].map(match => Number(match[1]))
  assert.ok(durations.every(ms => ms <= 180), `durations ${durations}`)
  assert.match(rail, /prefers-reduced-motion:reduce\)\{\s*[^}]*transition:none!important/)
})

test('labels fade in the rail, and the unread badge stays visible on the icon', () => {
  assert.equal((app.match(/class="relay-nav-label"/g) || []).length, 3)
  assert.match(rail, /\.relay-nav-label[^{]*\{opacity:0/)
  assert.match(block(rail, '.v1-shell.relay-shell .app-nav:not(:hover,:has(:focus-visible)) .nav-count'), /position:absolute/)
  assert.ok(!/nav-count[^{]*\{[^}]*(opacity:0|display:none)/.test(rail))
})

test('the phone layout keeps the bottom tab bar and hides the sidebar', () => {
  const mobile = readFileSync(new URL('../src/mobile.css', import.meta.url), 'utf8')
  assert.match(mobile, /\.v1-shell\.relay-shell>\.app-nav,\.v1-shell\.relay-shell>\.relay-nav-backdrop\{display:none!important\}/)
  assert.match(app, /<MobileTabBar v-if="isMobile && ready"/)
})
